"""workspaces 插件路由：CRUD + 成员管理 + pin + candidates."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import (
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceType,
    WorkspaceVisibility,
)
from cndb.plugins.workspaces.permissions import get_member_role, has_role
from cndb.plugins.workspaces.routers.deps import _get_workspace_or_404, _require_member, _require_owner
from cndb.plugins.workspaces.routers.member_routes import router as member_router
from cndb.plugins.workspaces.schemas import (
    PinRequest,
    PinToggleResponse,
    WorkspaceCreate,
    WorkspaceCreateFromBackup,
    WorkspaceCreateFromBackupResponse,
    WorkspaceDetailResponse,
    WorkspaceImportRequest,
    WorkspaceImportResponse,
    WorkspaceResponse,
    WorkspaceUpdate,
    WorkspaceWithPinnedResponse,
)
from cndb.plugins.workspaces.services.backup_io import (
    _coerce_row_value_types,
    _import_backup_into_workspace,
)

# 工作区列表缓存（进程内，短 TTL；写路径主动失效）
WORKSPACE_LIST_TTL_SECONDS = 10.0


def _list_cache() -> Any:
    from cndb.core.cache import list_cache

    return list_cache


def invalidate_workspace_list_cache() -> int:
    """失效所有用户的工作区列表缓存（成员/工作区变更后调用）."""
    from cndb.core.cache import cache_key, list_cache

    return list_cache.clear(cache_key("ws-list"))


router = APIRouter(prefix="/workspaces", tags=["workspaces"])
# 成员管理 / 所有权转让拆到 routers/member_routes.py（同一前缀下挂载）
router.include_router(member_router)

# ── 工作区 CRUD ──────────────────────────────────────


@router.get("", response_model=list[WorkspaceWithPinnedResponse])
def list_workspaces(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkspaceWithPinnedResponse]:
    """列出当前用户所属的工作区，钉住的置顶，附带 table_count / member_count.

    进程内短 TTL 缓存（10s，按用户隔离）：该接口每次都要做 3 次聚合统计，
    是首页最热的读路径；写路径（新建/改名/成员变更）会主动失效，
    短 TTL 只是兜底 —— 单机部署下进程内缓存无需 Redis 即可生效。
    """
    from cndb.core.cache import cache_key

    cache = _list_cache()
    ck = cache_key("ws-list", current_user.id, id(db.bind))
    cached = cache.get(ck)
    if cached is not None:
        return cached
    data = _list_workspaces_uncached(db, current_user)
    cache.set(ck, data, WORKSPACE_LIST_TTL_SECONDS)
    return data


def _list_workspaces_uncached(
    db: Session,
    current_user: User,
) -> list[WorkspaceWithPinnedResponse]:
    from sqlalchemy import case, func, select

    from cndb.plugins.tables.models import DataTable

    stmt = (
        select(Workspace, WorkspaceMember)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == current_user.id)
        .order_by(case((WorkspaceMember.pinned.is_(True), 0), else_=1), Workspace.id)
    )
    rows = db.execute(stmt).all()

    # 批量收集 workspace_id 用于统计
    ws_ids = [ws.id for ws, _ in rows]
    # 表数统计（排除软删）
    table_counts: dict[int, int] = {
        row[0]: row[1]
        for row in (
            db.query(DataTable.workspace_id, func.count(DataTable.id))
            .filter(DataTable.workspace_id.in_(ws_ids), DataTable.trashed_at.is_(None))
            .group_by(DataTable.workspace_id)
            .all()
        )
    }
    # 成员数统计（inner join 用户表：历史脏数据中用户已删除的孤儿成员行不计入，
    # 保证计数与成员列表一致）
    member_counts: dict[int, int] = {
        row[0]: row[1]
        for row in (
            db.query(WorkspaceMember.workspace_id, func.count(WorkspaceMember.id))
            .join(User, User.id == WorkspaceMember.user_id)
            .filter(WorkspaceMember.workspace_id.in_(ws_ids))
            .group_by(WorkspaceMember.workspace_id)
            .all()
        )
    }
    result: list[WorkspaceWithPinnedResponse] = []
    for ws, member in rows:
        d = {c.name: getattr(ws, c.name) for c in ws.__table__.columns}
        d["pinned"] = bool(member.pinned)
        # 统计字段塞进 response 扩展（WorkspaceWithPinnedResponse 继承自 WorkspaceResponse，
        # 前端列表类型声明时用 Workspace & { table_count, member_count } 接收）
        d["table_count"] = table_counts.get(ws.id, 0)
        d["member_count"] = member_counts.get(ws.id, 0)
        d["current_user_role"] = member.role.value if member.role else None
        result.append(WorkspaceWithPinnedResponse.model_validate(d))
    return result


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Workspace:
    """创建工作区并把创建者登记为 OWNER."""
    ws = Workspace(
        name=payload.name,
        description=payload.description,
        visibility=payload.visibility,
        tags=payload.tags,
        allow_edit=payload.allow_edit,
        workspace_type=payload.workspace_type,
        created_by_id=current_user.id,
    )
    db.add(ws)
    db.flush()  # 拿到 ws.id
    member = WorkspaceMember(workspace_id=ws.id, user_id=current_user.id, role=WorkspaceRole.OWNER)
    db.add(member)
    db.commit()
    invalidate_workspace_list_cache()
    db.refresh(ws)
    return ws


@router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
def get_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceDetailResponse:
    """获取工作区详情（需是成员），附带拥有者信息和统计."""
    from contextlib import suppress

    from sqlalchemy import MetaData, func, select

    from cndb.plugins.tables.models import DataTable, DataView
    from cndb.plugins.workspaces.services.storage_snapshot import snapshot_used_bytes

    ws = _get_workspace_or_404(workspace_id, db)
    _require_member(ws, current_user, db)

    # 统计
    table_count = (
        db.query(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed_at.is_(None),
        )
        .count()
    )
    member_count = (
        db.query(WorkspaceMember)
        .join(User, User.id == WorkspaceMember.user_id)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
        )
        .count()
    )
    view_count = (
        db.query(DataView)
        .join(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed_at.is_(None),
        )
        .count()
    )
    # 总行数：遍历每个 DataTable 的物理表执行 COUNT
    total_rows = 0
    tables = (
        db.query(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed_at.is_(None),
        )
        .all()
    )
    metadata = MetaData()
    for tbl in tables:
        with suppress(Exception):
            sa_table = __import__("sqlalchemy").Table(tbl.db_table_name, metadata, autoload_with=db.bind)
            cnt = db.execute(select(func.count(sa_table.c.id))).scalar() or 0
            total_rows += int(cnt)

    # 拥有者信息
    owner_member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == WorkspaceRole.OWNER,
        )
        .first()
    )
    owner_info: dict[str, Any] | None = None
    if owner_member and owner_member.user:
        owner_info = {
            "id": owner_member.user.id,
            "username": owner_member.user.username,
            "nickname": owner_member.user.nickname,
        }

    current_role = get_member_role(current_user, ws, db)
    d = {c.name: getattr(ws, c.name) for c in ws.__table__.columns}
    d.update(
        {
            "owner": owner_info,
            "table_count": table_count,
            "member_count": member_count,
            "view_count": view_count,
            "total_rows": total_rows,
            # 读用量快照（ADR 0024），缺失时懒计算一次并落库
            "storage_bytes": snapshot_used_bytes(db, workspace_id, lazy=True) or 0,
            "current_user_role": current_role.value if current_role else None,
        }
    )
    return WorkspaceDetailResponse.model_validate(d)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Workspace:
    """更新工作区（仅 OWNER）."""
    ws = _get_workspace_or_404(workspace_id, db)
    _require_owner(ws, current_user, db)
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(ws, key, value)
    db.commit()
    invalidate_workspace_list_cache()
    db.refresh(ws)
    return ws


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除工作区（仅 OWNER 可执行）."""
    ws = _get_workspace_or_404(workspace_id, db)
    role = get_member_role(current_user, ws, db)
    if role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail="仅所有者可删除工作区")
    db.delete(ws)
    db.commit()
    invalidate_workspace_list_cache()


# ── pin 切换 ──────────────────────────────────────────


@router.post("/pin", response_model=PinToggleResponse)
def toggle_pin(
    payload: PinRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PinToggleResponse:
    """切换当前用户对工作区的钉住状态."""
    ws = _get_workspace_or_404(payload.workspace_id, db)
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == current_user.id)
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="工作区不存在")  # pragma: no cover - 由 _get_workspace_or_404 前置
    member.pinned = not member.pinned
    db.commit()
    invalidate_workspace_list_cache()
    db.refresh(member)
    return PinToggleResponse(pinned=member.pinned)


def _row_scope_where(db: Any, tbl: Any, sa_table: Any, user: Any = None) -> Any | None:
    """编译该表的**读范围**条件（无配置或调用者豁免时返回 None）.

    ADR 0004：导出取数复用 ``row_access.row_read_scope_where``（默认档 ∪ 命中的行级规则），
    与记录读取 / 审计同一入口，导出不得越过读范围。
    """
    from cndb.plugins.tables.services.core.row_access import row_read_scope_where

    return row_read_scope_where(db, tbl, sa_table, user)


@router.get("/{workspace_id}/export")
def export_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """导出整个工作区为 JSON：工作区元信息 + 所有表结构 + 数据行 + 视图配置 + 表权限 + 文档（含标签）."""
    import datetime as dt

    from sqlalchemy import MetaData, select

    from cndb.plugins.documents.models import Document, DocumentTag, Tag
    from cndb.plugins.documents.services.content import latest_version, load_content
    from cndb.plugins.tables.models import DataField, DataTable, DataView, RowPermission, TablePermission

    ws = _get_workspace_or_404(workspace_id, db)
    # 全量导出是备份/恢复的一侧，与 import_workspace 对称要求 EDITOR+：
    # 此前仅校验成员身份，任何 viewer 都能把所有表（含受限表）连数据行一起导出。
    if not has_role(current_user, ws, WorkspaceRole.EDITOR, db):
        raise HTTPException(status_code=403, detail="需要编辑者及以上权限才能导出工作区")

    # 工作区元信息
    workspace_meta = {
        "name": ws.name,
        "description": ws.description,
        "visibility": ws.visibility.value,
        "tags": ws.tags,
        "allow_edit": ws.allow_edit,
        "workspace_type": ws.workspace_type.value,
    }

    # 导出所有表（含字段、数据、视图）
    tables_data: list[dict[str, Any]] = []
    tables = (
        db.query(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed_at.is_(None),
        )
        .all()
    )

    # 表级可见性：只导出当前用户**能读**的表（read_role 高于自身角色的表不得导出）
    from cndb.plugins.tables.services.core.access import TableAction, preload_table_access

    preload = preload_table_access(db, tables, current_user)
    tables = [tbl for tbl in tables if preload.check(db, tbl, current_user, TableAction.READ)]

    metadata = MetaData()
    # v4：每表的 行 id → 行索引 映射与字段 id，供关联数据跨表重映射
    row_index_maps: dict[int, dict[int, int]] = {}
    for tbl in tables:
        # 字段定义（含字段 id：导入端据此重映射 link/lookup config 内的跨表引用）
        fields = (
            db.query(DataField)
            .filter(
                DataField.table_id == tbl.id,
                DataField.trashed.is_(False),
            )
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

        # 数据行：行键用业务字段名（字段物理列名跨库恢复时会重新随机生成，
        # 直接导出物理列名会导致导入端键匹配不上、数据行全部丢失）；
        # 按 id 排序保证导出顺序稳定（导入端按导出顺序重建行并映射关联）
        rows_data: list[dict[str, Any]] = []
        colname_to_field = {f.db_column_name: f.name for f in fields}
        try:
            sa_table = __import__("sqlalchemy").Table(tbl.db_table_name, metadata, autoload_with=db.bind)
            query = select(sa_table)
            if "trashed_at" in sa_table.columns:
                query = query.where(sa_table.c.trashed_at.is_(None))
            # 行级权限（TablePermission.row_filters）：导出与读取接口保持一致口径
            row_scope = _row_scope_where(db, tbl, sa_table, current_user)
            if row_scope is not None:
                query = query.where(row_scope)
            if "id" in sa_table.columns:
                query = query.order_by(sa_table.c.id)
            result = db.execute(query).mappings().all()
            rows_data = [{colname_to_field[k]: v for k, v in dict(r).items() if k in colname_to_field} for r in result]
            if "id" in sa_table.columns:
                row_index_maps[tbl.id] = {int(r["id"]): i for i, r in enumerate(result)}
        except Exception:  # pragma: no cover - 表结构异常
            logging.getLogger(__name__).debug("导出读取表数据失败，跳过", exc_info=True)

        # 视图配置
        views = db.query(DataView).filter(DataView.table_id == tbl.id).all()
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
                # ADR 0003：可见性档位与命名空间（新增键，旧版备份无此键时按旧语义还原）
                "owner_id": v.owner_id,
                "visibility": v.visibility,
                "scope_key": v.scope_key,
            }
            for v in views
        ]

        # 表级权限配置（备份/恢复配置的一侧）：随表导出，导入端按新表 id 还原
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

        # 行级权限规则（tables_rowpermission，ADR 0004 §7-9）：随表导出，
        # 导入端按新表 id 还原；旧版备份（无该键）缺失时按「无规则」还原
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
            }
        )

    # v4：link 字段关联行导出（行以导出顺序的索引定位，跨表重映射在导入端完成）。
    # 放在主循环后：target 表的行索引映射可能此时尚未构建。
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
                continue  # pragma: no cover - 关联表异常时跳过该字段
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

    # 文档备份：工作区级标签 + 文档树（文件夹层级 + 最新正文，不含历史版本）。
    # 软删除（回收站）中的文档不导出；外存/压缩的内联内容统一解出为明文正文，
    # 导入端按分级存储策略重新落盘。
    tags = db.query(Tag).filter(Tag.workspace_id == workspace_id).order_by(Tag.id).all()
    document_tags_data = [{"id": t.id, "name": t.name, "color": t.color, "description": t.description} for t in tags]

    docs = (
        db.query(Document)
        .filter(Document.workspace_id == workspace_id, Document.is_deleted.is_(False))
        .order_by(Document.id)
        .all()
    )
    tag_links: dict[int, list[int]] = {}
    doc_ids = [d.id for d in docs]
    if doc_ids:
        for doc_id, tag_id in (
            db.query(DocumentTag.document_id, DocumentTag.tag_id).filter(DocumentTag.document_id.in_(doc_ids)).all()
        ):
            tag_links.setdefault(int(doc_id), []).append(int(tag_id))

    documents_data: list[dict[str, Any]] = []
    for d in docs:
        documents_data.append(
            {
                "id": d.id,
                "parent_id": d.parent_id,
                "title": d.title,
                "content_type": d.content_type,
                "status": d.status,
                "is_folder": d.is_folder,
                "sort_order": d.sort_order,
                "content": "" if d.is_folder else load_content(latest_version(db, d.id), d),
                "tag_ids": tag_links.get(d.id, []),
            }
        )

    # v5：外部数据同步任务（ADR 0006）。跨工作区 table_id 不可移植，
    # 导出用「目标表名」引用，导入端按同名表映射；找不到同名表则任务不绑定表。
    # v7（ADR 0019）：大模型连接已改为**个人配置**，属于用户私有数据，不随工作区备份导出。
    from cndb.plugins.datasource.models import DatasourceSession, DatasourceSyncJob

    table_name_by_id = {tbl.id: tbl.name for tbl in tables}
    session_name_by_id = {
        row[0]: row[1]
        for row in db.query(DatasourceSession.id, DatasourceSession.name)
        .filter(DatasourceSession.workspace_id == workspace_id)
        .all()
    }
    sync_jobs = (
        db.query(DatasourceSyncJob)
        .filter(DatasourceSyncJob.workspace_id == workspace_id)
        .order_by(DatasourceSyncJob.id)
        .all()
    )
    sync_jobs_data = [
        {
            "name": job.name,
            "provider": job.provider,
            "table_name": table_name_by_id.get(job.table_id) if job.table_id else None,
            "request_spec": job.request_spec,
            "parser": job.parser,
            "entrant_param": job.entrant_param,
            "entrant_keys": job.entrant_keys,
            "match_keys": job.match_keys,
            "field_mapping": job.field_mapping,
            "cursor": job.cursor,
            "schedule": job.schedule,
            "enabled": job.enabled,
            # 会话只记名称：密钥不随备份导出（导入端按同名绑定，缺失则解绑）
            "session_name": session_name_by_id.get(job.session_id) if job.session_id else None,
            "rate_limit_ms": job.rate_limit_ms,
        }
        for job in sync_jobs
    ]

    return {
        "version": "7",
        "exported_at": dt.datetime.now(dt.UTC).isoformat(),
        "workspace": workspace_meta,
        "tables": tables_data,
        "document_tags": document_tags_data,
        "documents": documents_data,
        "sync_jobs": sync_jobs_data,
    }


@router.post("/import", response_model=WorkspaceCreateFromBackupResponse, status_code=status.HTTP_201_CREATED)
def create_workspace_from_backup(
    payload: WorkspaceCreateFromBackup,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceCreateFromBackupResponse:
    """从备份 JSON 创建全新工作区：先创建工作区（owner 为当前用户），再把备份中的表结构、数据和视图导入."""
    data = payload.json_data
    if not isinstance(data, dict) or "tables" not in data:
        raise HTTPException(status_code=400, detail="无效的备份文件格式")

    # 从备份里读取 workspace meta 作为创建工作区的默认值
    ws_meta = data.get("workspace") or {}
    backup_name = payload.name or (ws_meta.get("name") or "").strip() or "未命名工作区"

    try:
        visibility_str = ws_meta.get("visibility", "member")
        visibility = WorkspaceVisibility(visibility_str)
    except (ValueError, TypeError):
        visibility = WorkspaceVisibility.MEMBER

    try:
        workspace_type = WorkspaceType(ws_meta.get("workspace_type", WorkspaceType.DATA_DOC.value))
    except (ValueError, TypeError):
        workspace_type = WorkspaceType.DATA_DOC

    ws = Workspace(
        name=backup_name,
        description=ws_meta.get("description", "") or "",
        visibility=visibility,
        tags=ws_meta.get("tags", []) or [],
        allow_edit=bool(ws_meta.get("allow_edit", True)),
        workspace_type=workspace_type,
        created_by_id=current_user.id,
    )
    db.add(ws)
    db.flush()  # 拿到 ws.id

    member = WorkspaceMember(workspace_id=ws.id, user_id=current_user.id, role=WorkspaceRole.OWNER)
    db.add(member)
    db.commit()
    db.refresh(ws)

    # 导入备份中的表/数据/视图
    try:
        import_result = _import_backup_into_workspace(ws.id, data, current_user, db)
    except HTTPException:
        # 导入失败：清理刚创建的工作区，避免脏数据残留
        db.delete(ws)
        db.commit()
        raise

    return WorkspaceCreateFromBackupResponse(
        workspace=ws,
        imported_tables=import_result.imported_tables,
        imported_rows=import_result.imported_rows,
        imported_views=import_result.imported_views,
        imported_documents=import_result.imported_documents,
        imported_sync_jobs=import_result.imported_sync_jobs,
        errors=import_result.errors,
    )


@router.post("/{workspace_id}/import", response_model=WorkspaceImportResponse)
def import_workspace(
    workspace_id: int,
    payload: WorkspaceImportRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceImportResponse:
    """从 JSON 数据导入表结构、视图和数据行到指定工作区（EDITOR+）."""
    ws = _get_workspace_or_404(workspace_id, db)
    if not has_role(current_user, ws, WorkspaceRole.EDITOR, db):
        raise HTTPException(status_code=403, detail="需要编辑者权限")
    data = payload.json_data
    if not isinstance(data, dict) or "tables" not in data:
        raise HTTPException(status_code=400, detail="无效的导入数据格式")

    return _import_backup_into_workspace(workspace_id, data, current_user, db)


__all__ = ["_coerce_row_value_types", "router"]
