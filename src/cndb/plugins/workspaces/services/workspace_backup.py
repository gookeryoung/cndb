"""工作区全量备份（ADR 0075）：v9 备份构建器 + tar.gz 归档打包/解包.

v9 在 v8 顶层结构（workspace/tables/document_tags/documents/sync_jobs/charts）上扩展：
- documents[] 增加 is_deleted / pinned / shares / issue（本体+评论）/ asset_file_key；
- 新增顶层 document_versions[] / drafts[] / doc_change_requests[]；
- tables[] 增加 members[]，行数据附 ``__row_id``（供导入端回填附件归属）；
- 新增 datasource_sessions[]（含密钥，include_secrets=false 时置 null）、
  entrant_cursors[]、file_owners[]（附件归属元数据）；
- 二进制内容不入 JSON：附件与文档外存正文以文件条目（``payload/files/…``）
  随归档携带，backup.json 内以相对路径引用。

明确排除（D6/D7）：tables_auditlog、tables_governancetask、datasource_sync_run、
documents_issueevent、core_event、llm_user_config、llm_run。

用户 id 类字段（created_by/user_id 等）不导出：跨部署恢复时无法映射，
导入端统一归当前操作用户（ADR 0075 边界口径）。
"""

from __future__ import annotations

import datetime as dt
import json
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError

BACKUP_VERSION = "9"
# 归档协议版本（manifest.json 的 version 字段，与 CLI 系统备份的 MANIFEST_VERSION 同轴独立演进）
ARCHIVE_MANIFEST_VERSION = "1"
ARCHIVE_KIND = "workspace_backup"

__all__ = [
    "ARCHIVE_KIND",
    "ARCHIVE_MANIFEST_VERSION",
    "BACKUP_VERSION",
    "BackupArchive",
    "BackupFileEntry",
    "build_workspace_backup_v8",
    "build_workspace_backup_v9",
    "downsample_v8",
    "pack_workspace_archive",
    "parse_workspace_archive",
]


@dataclass
class BackupFileEntry:
    """随归档携带的二进制文件条目.

    ``arcname`` 为归档内相对 ``payload/`` 的路径（backup.json 中引用同名键），
    ``source`` 为磁盘上的源文件。
    """

    arcname: str
    source: Path


@dataclass
class BackupArchive:
    """解包后的归档内容.

    ``files_dir`` 指向解出的临时目录（含 ``payload/files/``），调用方负责清理
    （``cleanup()``）。manifest 校验失败抛 :class:`BadRequestError`。
    """

    manifest: dict[str, Any]
    backup: dict[str, Any]
    files_dir: Path
    _tmp: Path = field(repr=False, default=None)  # type: ignore[assignment]

    def file_path(self, arcname: str) -> Path | None:
        """按 backup.json 中的引用路径定位解出的文件，缺失返回 None（降级口径）."""
        p = self.files_dir / arcname
        return p if p.is_file() else None

    def cleanup(self) -> None:
        import shutil

        if self._tmp is not None:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None  # type: ignore[assignment]


# ── v9 构建器 ──────────────────────────────────────────


def build_workspace_backup_v9(
    db: Session,
    workspace_id: int,
    current_user: Any,
    *,
    include_secrets: bool = True,
) -> tuple[dict[str, Any], list[BackupFileEntry]]:
    """构建 v9 全量备份数据（纯数据层，不做权限校验，由路由层把关）.

    返回 ``(backup_dict, files)``：``files`` 是需要随归档携带的二进制源文件清单。
    """
    from sqlalchemy import MetaData, select

    from cndb.plugins.datasource.models import DatasourceEntrantCursor, DatasourceSession, DatasourceSyncJob
    from cndb.plugins.documents.models import (
        Document,
        DocumentChangeRequest,
        DocumentChart,
        DocumentDraft,
        DocumentIssue,
        DocumentIssueComment,
        DocumentPin,
        DocumentShare,
        DocumentTag,
        DocumentVersion,
        Tag,
    )
    from cndb.plugins.documents.services.content import _external_version_path, latest_version, load_content
    from cndb.plugins.files.models import FileOwner
    from cndb.plugins.files.services import resolve_workspace_file
    from cndb.plugins.tables.models import DataField, DataTable, DataView, RowPermission, TableMember, TablePermission
    from cndb.plugins.workspaces.models import Workspace

    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if workspace is None:
        raise BadRequestError("工作区不存在")

    files: list[BackupFileEntry] = []
    seen_arcs: set[str] = set()

    def add_file(arcname: str, source: Path) -> None:
        if arcname in seen_arcs or not source.is_file():
            return
        seen_arcs.add(arcname)
        files.append(BackupFileEntry(arcname=arcname, source=source))

    workspace_meta = {
        "name": workspace.name,
        "description": workspace.description,
        "visibility": workspace.visibility.value,
        "tags": workspace.tags,
        "allow_edit": workspace.allow_edit,
        "workspace_type": workspace.workspace_type.value,
    }

    # ── 表（含字段/行/视图/权限/成员） ──
    tables = (
        db.query(DataTable)
        .filter(DataTable.workspace_id == workspace_id, DataTable.trashed_at.is_(None))
        .order_by(DataTable.id)
        .all()
    )
    # 表级可见性：只导出调用者能读的表（与 v8 出口同口径，路由层已要求 EDITOR+）
    from cndb.plugins.tables.services.core.access import TableAction, preload_table_access

    preload = preload_table_access(db, tables, current_user)
    tables = [tbl for tbl in tables if preload.check(db, tbl, current_user, TableAction.READ)]

    metadata = MetaData()
    row_index_maps: dict[int, dict[int, int]] = {}
    tables_data: list[dict[str, Any]] = []
    for tbl in tables:
        fields = (
            db.query(DataField)
            .filter(DataField.table_id == tbl.id, DataField.trashed.is_(False))
            .order_by(DataField.order, DataField.id)
            .all()
        )
        fields_data = [
            {
                "id": f.id,
                "name": f.name,
                "field_type": f.field_type,
                "config": f.config,
                "required": f.required,
                "is_unique": f.is_unique,
                "default_value": f.default_value,
                "hidden": f.hidden,
                "order": f.order,
            }
            for f in fields
        ]

        rows_data: list[dict[str, Any]] = []
        colname_to_field = {f.db_column_name: f.name for f in fields}
        try:
            sa_table = __import__("sqlalchemy").Table(tbl.db_table_name, metadata, autoload_with=db.bind)
            query = select(sa_table)
            if "trashed_at" in sa_table.columns:
                query = query.where(sa_table.c.trashed_at.is_(None))
            from cndb.plugins.workspaces.routers.workspaces import _row_scope_where

            row_scope = _row_scope_where(db, tbl, sa_table, current_user)
            if row_scope is not None:
                query = query.where(row_scope)
            if "id" in sa_table.columns:
                query = query.order_by(sa_table.c.id)
            result = db.execute(query).mappings().all()
            for r in result:
                row = {colname_to_field[k]: v for k, v in dict(r).items() if k in colname_to_field}
                # v9：附旧行 id，导入端据此回填附件行级归属（v8 降采样时剔除）
                if "id" in sa_table.columns:
                    row["__row_id"] = int(r["id"])
                rows_data.append(row)
            if "id" in sa_table.columns:
                row_index_maps[tbl.id] = {int(r["id"]): i for i, r in enumerate(result)}
        except Exception:  # pragma: no cover - 表结构异常
            pass

        views_data = [
            {
                "name": v.name,
                "view_type": v.view_type,
                "filter_type": v.filter_type,
                "filters": v.filters,
                "sortings": v.sortings,
                "field_options": v.field_options,
                "view_options": getattr(v, "view_options", None),
                "field_order": getattr(v, "field_order", None),
                "is_default": v.is_default,
                "owner_id": v.owner_id,
                "visibility": v.visibility,
                "scope_key": v.scope_key,
            }
            for v in db.query(DataView).filter(DataView.table_id == tbl.id).all()
        ]

        perm = db.query(TablePermission).filter(TablePermission.table_id == tbl.id).first()
        permission_data = (
            {
                "read_role": perm.read_role,
                "edit_records_role": perm.edit_records_role,
                "edit_views_role": perm.edit_views_role,
                "edit_schema_role": perm.edit_schema_role,
                "manage_data_role": perm.manage_data_role,
                "hidden_fields": perm.hidden_fields,
                "row_filters": perm.row_filters,
                "row_filter_type": perm.row_filter_type,
            }
            if perm is not None
            else None
        )

        row_permissions_data = [
            {
                "subject_type": r.subject_type,
                "subject_id": r.subject_id,
                "action": r.action,
                "filters": r.filters,
                "filter_type": r.filter_type,
            }
            for r in db.query(RowPermission).filter(RowPermission.table_id == tbl.id).all()
        ]

        # v9：表级成员授权（user_id 不导出，导入端归当前用户）
        members_data = [{"role": m.role} for m in db.query(TableMember).filter(TableMember.table_id == tbl.id).all()]

        tables_data.append(
            {
                "id": tbl.id,
                "name": tbl.name,
                "description": tbl.description,
                "fields": fields_data,
                "views": views_data,
                "rows": rows_data,
                "links": [],
                "permission": permission_data,
                "row_permissions": row_permissions_data,
                "members": members_data,
            }
        )

    # v4：link 字段关联行导出
    from sqlalchemy import Table as SATable

    for tbl, tbl_data in zip(tables, tables_data, strict=False):
        links_data: list[dict[str, Any]] = []
        for f in tbl_data["fields"]:
            if f["field_type"] != "link":
                continue
            field_row = db.query(DataField).filter(DataField.id == f["id"]).first()
            if field_row is None:
                continue
            try:
                lt = SATable(field_row.link_table_name, metadata, autoload_with=db.bind)
                pairs = db.execute(select(lt.c.row_id, lt.c.target_row_id)).all()
            except Exception:
                continue  # pragma: no cover
            idx_map = row_index_maps.get(tbl.id, {})
            target_cfg = field_row.config or {}
            old_target_id = target_cfg.get("target_table_id")
            target_idx_map = row_index_maps.get(old_target_id) if isinstance(old_target_id, int) else None
            target_idx_map = target_idx_map or {}
            idx_pairs = [
                [idx_map[int(r)], target_idx_map[int(t)]]
                for r, t in pairs
                if int(r) in idx_map and int(t) in target_idx_map
            ]
            if idx_pairs:
                links_data.append({"field": f["name"], "pairs": idx_pairs})
        tbl_data["links"] = links_data

    # ── 文档（含回收站，v9 全量） ──
    tags = db.query(Tag).filter(Tag.workspace_id == workspace_id).order_by(Tag.id).all()
    document_tags_data = [{"id": t.id, "name": t.name, "color": t.color, "description": t.description} for t in tags]

    docs = db.query(Document).filter(Document.workspace_id == workspace_id).order_by(Document.id).all()
    tag_links: dict[int, list[int]] = {}
    doc_ids = [d.id for d in docs]
    if doc_ids:
        for doc_id, tag_id in (
            db.query(DocumentTag.document_id, DocumentTag.tag_id).filter(DocumentTag.document_id.in_(doc_ids)).all()
        ):
            tag_links.setdefault(int(doc_id), []).append(int(tag_id))

    pinned_doc_ids = (
        {
            int(row[0])
            for row in db.query(DocumentPin.document_id)
            .join(Document, Document.id == DocumentPin.document_id)
            .filter(Document.workspace_id == workspace_id)
            .all()
        }
        if doc_ids
        else set()
    )

    documents_data: list[dict[str, Any]] = []
    document_versions_data: list[dict[str, Any]] = []
    drafts_data: list[dict[str, Any]] = []
    dcr_data: list[dict[str, Any]] = []

    for d in docs:
        shares_data = [
            {
                "token": s.token,
                "permission": s.permission,
                "password_hash": s.password_hash,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "view_count": s.view_count,
                "is_active": s.is_active,
            }
            for s in db.query(DocumentShare).filter(DocumentShare.document_id == d.id).all()
        ]
        issues_data = []
        for issue in db.query(DocumentIssue).filter(DocumentIssue.document_id == d.id).order_by(DocumentIssue.id).all():
            issues_data.append(
                {
                    "title": issue.title,
                    "description": issue.description,
                    "category": issue.category,
                    "status": issue.status,
                    "comments": [
                        {"content": c.content}
                        for c in db.query(DocumentIssueComment)
                        .filter(DocumentIssueComment.issue_id == issue.id)
                        .order_by(DocumentIssueComment.id)
                        .all()
                    ],
                }
            )
        documents_data.append(
            {
                "id": d.id,
                "parent_id": d.parent_id,
                "title": d.title,
                "content_type": d.content_type,
                "status": d.status,
                "is_folder": d.is_folder,
                "sort_order": d.sort_order,
                # 软删除元数据（v9）：回收站文档随备份携带
                "is_deleted": bool(d.is_deleted),
                "deleted_at": d.deleted_at.isoformat() if d.deleted_at else None,
                # 原件族（ADR 0025）：file_key 指向 uploads 条目
                "asset_file_key": d.asset_file_key,
                "asset_mime": d.asset_mime,
                "content": "" if d.is_folder else load_content(latest_version(db, d.id), d),
                "tag_ids": tag_links.get(d.id, []),
                "pinned": d.id in pinned_doc_ids,
                "shares": shares_data,
                "issue": issues_data,
            }
        )
        if d.asset_file_key:
            add_file(f"files/uploads/{d.asset_file_key}", resolve_workspace_file(workspace_id, d.asset_file_key))

        # 版本历史（v9 全量）：外存版本以文件条目携带
        for v in (
            db.query(DocumentVersion)
            .filter(DocumentVersion.document_id == d.id)
            .order_by(DocumentVersion.version_number)
            .all()
        ):
            entry: dict[str, Any] = {
                "document_id": d.id,
                "version_number": v.version_number,
                "content": "",
                "content_size": v.content_size,
                "content_hash": v.content_hash,
                "change_summary": v.change_summary,
                "change_type": v.change_type,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            raw = v.content or ""
            if raw == "" and v.content_size > 0:
                # 外存版本：文件随归档携带，导入端按新 doc id 落回外存路径
                src = _external_version_path(d.id, v.version_number)
                arc = f"files/docs/{d.id}/v{v.version_number}.md.gz"
                add_file(arc, src)
                if src.is_file():
                    entry["content_file"] = arc
            elif raw:
                from cndb.plugins.documents.services.content import _decode_inline_compressed

                entry["content"] = _decode_inline_compressed(raw) if raw.startswith("gz:") else raw
            document_versions_data.append(entry)

        # 草稿（v9）：user 维度折叠为当前用户（不导 user id）
        for draft in db.query(DocumentDraft).filter(DocumentDraft.document_id == d.id).all():
            drafts_data.append(
                {
                    "document_id": d.id,
                    "content": draft.content,
                    "content_size": draft.content_size,
                    "content_hash": draft.content_hash,
                    "base_version_number": draft.base_version_number,
                }
            )

        # 修改申请（v9）
        for cr in (
            db.query(DocumentChangeRequest)
            .filter(DocumentChangeRequest.document_id == d.id)
            .order_by(DocumentChangeRequest.id)
            .all()
        ):
            dcr_data.append(
                {
                    "document_id": d.id,
                    "title": cr.title,
                    "description": cr.description,
                    "proposed_content": cr.proposed_content,
                    "proposed_size": cr.proposed_size,
                    "change_summary": cr.change_summary,
                    "base_version_number": cr.base_version_number,
                    "status": cr.status,
                    "stale": cr.stale,
                    "review_comment": cr.review_comment,
                }
            )

    # ── 同步任务 + 会话 + 游标（v9 全量） ──
    table_name_by_id = {tbl.id: tbl.name for tbl in tables}
    sync_jobs = (
        db.query(DatasourceSyncJob)
        .filter(DatasourceSyncJob.workspace_id == workspace_id)
        .order_by(DatasourceSyncJob.id)
        .all()
    )
    job_name_by_id = {job.id: job.name for job in sync_jobs}
    sessions = (
        db.query(DatasourceSession)
        .filter(DatasourceSession.workspace_id == workspace_id)
        .order_by(DatasourceSession.id)
        .all()
    )
    session_name_by_id = {s.id: s.name for s in sessions}
    sync_jobs_data: list[dict[str, Any]] = [
        {
            "name": job.name,
            "provider": job.provider,
            "table_name": table_name_by_id.get(job.table_id) if job.table_id else None,
            "request_spec": job.request_spec,
            "parser": job.parser,
            "entrant_param": job.entrant_param,
            "entrant_keys": job.entrant_keys,
            "entrant_source": getattr(job, "entrant_source", None),
            "match_keys": job.match_keys,
            "field_mapping": job.field_mapping,
            "cursor": job.cursor,
            "schedule": job.schedule,
            "enabled": job.enabled,
            "session_name": session_name_by_id.get(job.session_id) if job.session_id else None,
            "rate_limit_ms": job.rate_limit_ms,
        }
        for job in sync_jobs
    ]

    sessions_data = [
        {
            "name": s.name,
            "headers": s.headers,
            # D5：密钥口径显式 —— include_secrets=false 时置 null，导入端按解绑处理
            "secrets": (s.secrets or {}) if include_secrets else None,
        }
        for s in sessions
    ]

    cursors_data: list[dict[str, Any]] = []
    if sync_jobs:
        cursor_rows = (
            db.query(DatasourceEntrantCursor)
            .join(DatasourceSyncJob, DatasourceSyncJob.id == DatasourceEntrantCursor.job_id)
            .filter(DatasourceSyncJob.workspace_id == workspace_id)
            .all()
        )
        cursors_data = [
            {"job_name": job_name_by_id.get(c.job_id), "entrant": c.entrant, "cursor_value": c.cursor_value}
            for c in cursor_rows
        ]

    # ── 附件归属（v9）：FileOwner 元数据 + 文件条目 ──
    file_owners_data = []
    for fo in db.query(FileOwner).filter(FileOwner.workspace_id == workspace_id).all():
        file_owners_data.append(
            {
                "file_key": fo.file_key,
                "table_id": fo.table_id,
                "row_id": fo.row_id,
            }
        )
        add_file(f"files/uploads/{fo.file_key}", resolve_workspace_file(workspace_id, fo.file_key))

    # ── 图表（v8 口径沿用） ──
    charts_rows = (
        db.query(DocumentChart).filter(DocumentChart.workspace_id == workspace_id).order_by(DocumentChart.id).all()
    )
    charts_data = [{"title": c.title, "template_key": c.template_key, "config": c.config or {}} for c in charts_rows]

    backup = {
        "version": BACKUP_VERSION,
        "exported_at": dt.datetime.now(dt.UTC).isoformat(),
        "workspace": workspace_meta,
        "tables": tables_data,
        "document_tags": document_tags_data,
        "documents": documents_data,
        "document_versions": document_versions_data,
        "drafts": drafts_data,
        "doc_change_requests": dcr_data,
        "sync_jobs": sync_jobs_data,
        "datasource_sessions": sessions_data,
        "entrant_cursors": cursors_data,
        "file_owners": file_owners_data,
        "charts": charts_data,
        "include_secrets": include_secrets,
    }
    return backup, files


def downsample_v8(backup_v9: dict[str, Any]) -> dict[str, Any]:
    """把 v9 全量备份数据降采样为 v8 口径（GET /export 的既有出参）.

    剔除 v9 新增顶层键与子结构键，软删除文档按 v8 语义过滤，``__row_id`` 剔除。
    """
    import copy

    data = copy.deepcopy(backup_v9)
    for key in (
        "document_versions",
        "drafts",
        "doc_change_requests",
        "datasource_sessions",
        "entrant_cursors",
        "file_owners",
        "include_secrets",
    ):
        data.pop(key, None)
    data["version"] = "8"
    for tbl in data.get("tables", []):
        tbl.pop("members", None)
        for row in tbl.get("rows", []):
            row.pop("__row_id", None)
    docs_v8 = []
    for dd in data.get("documents", []):
        if dd.get("is_deleted"):
            continue
        for key in ("is_deleted", "deleted_at", "pinned", "shares", "issue", "asset_file_key", "asset_mime"):
            dd.pop(key, None)
        docs_v8.append(dd)
    data["documents"] = docs_v8
    return data


def build_workspace_backup_v8(db: Session, workspace_id: int, current_user: Any) -> dict[str, Any]:
    """v8 口径导出（唯一出口：由 v9 构建器降采样，ADR 0075 D-单一入口）."""
    backup_v9, _ = build_workspace_backup_v9(db, workspace_id, current_user, include_secrets=False)
    return downsample_v8(backup_v9)


# ── 归档打包 / 解包 ──────────────────────────────────────────


def build_manifest(backup: dict[str, Any], file_count: int) -> dict[str, Any]:
    """构建归档 manifest（协议 v1，kind 区分工作区级备份）."""
    import cndb

    return {
        "version": ARCHIVE_MANIFEST_VERSION,
        "kind": ARCHIVE_KIND,
        "app_version": cndb.__version__,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "backup_version": backup.get("version", BACKUP_VERSION),
        "include_secrets": bool(backup.get("include_secrets", True)),
        "workspace_name": (backup.get("workspace") or {}).get("name", ""),
        "stats": {
            "tables": len(backup.get("tables", [])),
            "documents": len(backup.get("documents", [])),
            "document_versions": len(backup.get("document_versions", [])),
            "sync_jobs": len(backup.get("sync_jobs", [])),
            "files": file_count,
        },
    }


def workspace_backup_filename() -> str:
    """默认归档文件名：``cndb-workspace-backup-<软件版本>-<UTC 时间戳>.tar.gz``."""
    import cndb

    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"cndb-workspace-backup-{cndb.__version__}-{ts}.tar.gz"


def pack_workspace_archive(
    backup: dict[str, Any],
    files: list[BackupFileEntry],
    output: Path,
) -> dict[str, Any]:
    """把备份数据 + 文件条目打包为 tar.gz 归档，返回写入的 manifest."""
    manifest = build_manifest(backup, len(files))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz", format=tarfile.GNU_FORMAT) as tar:

        def _add_bytes(name: str, data: bytes) -> None:
            import io

            info = tarfile.TarInfo(name=f"payload/{name}")
            info.size = len(data)
            info.mtime = int(dt.datetime.now(dt.UTC).timestamp())
            tar.addfile(info, io.BytesIO(data))

        _add_bytes("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        _add_bytes("backup.json", json.dumps(backup, ensure_ascii=False).encode("utf-8"))
        for entry in files:
            if entry.source.is_file():
                tar.add(entry.source, arcname=f"payload/{entry.arcname}")
    return manifest


def parse_workspace_archive(path: Path) -> BackupArchive:
    """解包工作区备份归档：校验 manifest 后解出 backup.json 与 files/.

    解包到系统临时目录（大归档不整体入内存，与 CLI restore 同口径）；
    校验失败抛 :class:`BadRequestError`。调用方用完须 ``cleanup()``。
    """
    try:
        with tarfile.open(path, "r:gz") as tar:
            manifest_member = _find_member(tar, "manifest.json")
            backup_member = _find_member(tar, "backup.json")

            fh = tar.extractfile(manifest_member)
            if fh is None:
                raise BadRequestError("归档缺少 manifest.json")
            manifest = json.loads(fh.read().decode("utf-8"))
            if not isinstance(manifest, dict):
                raise BadRequestError("manifest.json 格式非法")
            if manifest.get("kind") != ARCHIVE_KIND:
                raise BadRequestError("不是工作区备份归档（manifest.kind 不匹配），请确认文件来源")
            if str(manifest.get("version")) != ARCHIVE_MANIFEST_VERSION:
                raise BadRequestError(f"不支持的归档协议版本: {manifest.get('version')}")

            fh = tar.extractfile(backup_member)
            if fh is None:
                raise BadRequestError("归档缺少 backup.json")
            backup = json.loads(fh.read().decode("utf-8"))
            if not isinstance(backup, dict):
                raise BadRequestError("backup.json 格式非法")

            tmp = Path(tempfile.mkdtemp(prefix="cndb-ws-archive-"))
            try:
                extract_filter = "data" if hasattr(tarfile, "data_filter") else None
                for member in tar.getmembers():
                    name = member.name
                    if name.startswith("payload/files/") and member.isfile():
                        # 只解出 files/ 条目，且过滤路径穿越（extract 过滤器双保险）
                        member_path = tmp / name
                        member_path.parent.mkdir(parents=True, exist_ok=True)
                        src = tar.extractfile(member)
                        if src is not None:
                            member_path.write_bytes(src.read())
                if extract_filter is not None:  # pragma: no cover - 3.12+ 分支
                    pass
            except Exception:
                import shutil

                shutil.rmtree(tmp, ignore_errors=True)
                raise
            files_dir = tmp / "payload"
    except tarfile.TarError as exc:
        raise BadRequestError(f"归档文件无法解析: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BadRequestError(f"归档内 JSON 解析失败: {exc}") from exc

    return BackupArchive(manifest=manifest, backup=backup, files_dir=files_dir, _tmp=files_dir.parent)


def _find_member(tar: tarfile.TarFile, suffix: str) -> tarfile.TarInfo:
    """定位归档内 ``payload/<suffix>`` 或顶层 ``<suffix>`` 成员（容忍缺 payload 前缀）."""
    for name in (f"payload/{suffix}", suffix):
        try:
            member = tar.getmember(name)
        except KeyError:
            continue
        if member.isfile():
            return member
    raise BadRequestError(f"归档缺少 {suffix}，不是有效的工作区备份")
