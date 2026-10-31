"""工作区覆盖恢复（ADR 0075 D3/D4）：清空业务数据 + 按 v9 备份全量重建.

- ``clear_workspace_content``：删除工作区全部业务数据（含动态表 DDL drop、
  版本/草稿/回收站/议题/图表/同步任务/游标/会话/附件归属），**保留**
  ``workspaces_workspace`` 行与 ``workspaces_workspacemember``（成员是部署级资产）；
- ``restore_workspace_from_backup``：clear + 复用 ``_import_backup_into_workspace``
  单一落库入口（I3），并把 workspace meta 按备份还原。
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from cndb.core.errors import ConflictError
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import WorkspaceType, WorkspaceVisibility
from cndb.plugins.workspaces.schemas import WorkspaceImportResponse

logger = logging.getLogger(__name__)

# 覆盖恢复前等待运行中同步任务退出的超时（秒，ADR 0075 边界 1）
SYNC_IDLE_TIMEOUT_SECONDS = 30.0

__all__ = ["clear_workspace_content", "restore_workspace_from_backup", "wait_sync_jobs_idle"]


def wait_sync_jobs_idle(db: Session, workspace_id: int, timeout: float = SYNC_IDLE_TIMEOUT_SECONDS) -> None:
    """等待该工作区运行中的同步任务退出，超时抛 409（不强行打断）."""
    from cndb.plugins.datasource.models import DatasourceSyncJob, DatasourceSyncRun, RunStatus

    deadline = time.monotonic() + timeout
    while True:
        running = (
            db.query(DatasourceSyncRun.id)
            .join(DatasourceSyncJob, DatasourceSyncJob.id == DatasourceSyncRun.job_id)
            .filter(
                DatasourceSyncJob.workspace_id == workspace_id,
                DatasourceSyncRun.status == RunStatus.RUNNING.value,
            )
            .first()
        )
        if running is None:
            return
        if time.monotonic() >= deadline:
            raise ConflictError(
                "该工作区仍有运行中的同步任务，请等待其完成（或手动停止）后再执行覆盖恢复",
                code="restore_sync_running",
            )
        time.sleep(0.5)


def clear_workspace_content(workspace_id: int, db: Session) -> None:
    """清空工作区全部业务数据（保留工作区行与成员关系）.

    DDL drop 前先 commit 释放 SQLite RESERVED 锁（与 backup_io 导入同款先例）。
    """
    from cndb.plugins.datasource.models import (
        DatasourceEntrantCursor,
        DatasourceSession,
        DatasourceSyncJob,
        DatasourceSyncRun,
    )
    from cndb.plugins.documents.models import (
        Document,
        DocumentChangeRequest,
        DocumentChart,
        DocumentDraft,
        DocumentIssue,
        DocumentIssueComment,
        DocumentIssueEvent,
        DocumentPin,
        DocumentShare,
        DocumentTag,
        DocumentVersion,
        Tag,
    )
    from cndb.plugins.files.models import FileOwner
    from cndb.plugins.tables.models import DataField, DataTable, DataView, RowPermission, TableMember, TablePermission

    doc_ids = [row[0] for row in db.query(Document.id).filter(Document.workspace_id == workspace_id).all()]
    dynamic_tables = db.query(DataTable.db_table_name).filter(DataTable.workspace_id == workspace_id).all()

    # 先清 FTS（需要 doc id），再删业务行
    if doc_ids:
        from cndb.plugins.documents.services.search import ensure_fts_schema

        ensure_fts_schema(db)
        placeholders = ",".join(str(int(i)) for i in doc_ids)
        db.execute(text(f"DELETE FROM documents_fts WHERE rowid IN ({placeholders})"))

    # 挂在文档下的表（无 workspace_id 列）：经 document_id 关联；评论/事件经 issue 关联
    if doc_ids:
        for model in (DocumentVersion, DocumentTag, DocumentShare, DocumentDraft, DocumentChangeRequest, DocumentPin):
            db.execute(delete(model).where(model.document_id.in_(doc_ids)))
        issue_ids = db.query(DocumentIssue.id).filter(DocumentIssue.document_id.in_(doc_ids)).all()
        issue_id_list = [row[0] for row in issue_ids]
        if issue_id_list:
            db.execute(delete(DocumentIssueComment).where(DocumentIssueComment.issue_id.in_(issue_id_list)))
            db.execute(delete(DocumentIssueEvent).where(DocumentIssueEvent.issue_id.in_(issue_id_list)))
    for model in (DocumentIssue, DocumentChart, Document, Tag):
        db.execute(delete(model).where(model.workspace_id == workspace_id))

    for model in (DatasourceEntrantCursor, DatasourceSyncRun, DatasourceSyncJob, DatasourceSession):
        _delete_by_workspace_cascade(db, model, workspace_id)

    db.execute(delete(FileOwner).where(FileOwner.workspace_id == workspace_id))

    # 表相关：先删引用行，再 commit，最后 drop 动态物理表 + 删元数据行
    table_ids = [row[0] for row in db.query(DataTable.id).filter(DataTable.workspace_id == workspace_id).all()]
    for model in (RowPermission, TablePermission, TableMember, DataView, DataField):
        if table_ids:
            db.execute(delete(model).where(model.table_id.in_(table_ids)))
    db.commit()

    # DDL drop（物理表已无元数据外键依赖；commit 后连接不持锁）
    bind: Any = db.get_bind()
    for (db_table_name,) in dynamic_tables:
        if db_table_name:
            try:
                with bind.connect() as conn:
                    conn.execute(text(f'DROP TABLE IF EXISTS "{db_table_name}"'))  # nosec B608 - 表名来自受管元数据白名单
                    conn.commit()
            except Exception:  # pragma: no cover - 物理表缺失/被占用时继续清元数据
                logger.warning("动态表 %s drop 失败，跳过", db_table_name, exc_info=True)

    if table_ids:
        db.execute(delete(DataTable).where(DataTable.id.in_(table_ids)))
    db.commit()


def _delete_by_workspace_cascade(db: Session, model: Any, workspace_id: int) -> None:
    """按 workspace_id 删除（模型无 workspace_id 列时经 job/workspaces 关联）."""
    from cndb.plugins.datasource.models import DatasourceSyncJob

    if hasattr(model, "workspace_id"):
        db.execute(delete(model).where(model.workspace_id == workspace_id))
        return
    job_ids = [
        row[0] for row in db.query(DatasourceSyncJob.id).filter(DatasourceSyncJob.workspace_id == workspace_id).all()
    ]
    if job_ids:
        db.execute(delete(model).where(model.job_id.in_(job_ids)))


def restore_workspace_from_backup(
    workspace_id: int,
    backup: dict[str, Any],
    files_dir: Any | None,
    current_user: User,
    db: Session,
) -> WorkspaceImportResponse:
    """覆盖恢复：先清空再按备份全量重建（工作区 id 与成员保留，meta 按备份还原）."""
    from cndb.plugins.workspaces.models import Workspace
    from cndb.plugins.workspaces.services.backup_io import _import_backup_into_workspace

    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise ConflictError("工作区不存在")

    wait_sync_jobs_idle(db, workspace_id)
    clear_workspace_content(workspace_id, db)

    # workspace meta 按备份还原（成员关系不动，D4）
    meta = backup.get("workspace") or {}
    if isinstance(meta, dict) and meta:
        ws.name = meta.get("name") or ws.name
        ws.description = meta.get("description", "") or ""
        ws.tags = meta.get("tags", []) or []
        ws.allow_edit = bool(meta.get("allow_edit", True))
        with contextlib.suppress(ValueError, TypeError):
            ws.visibility = WorkspaceVisibility(meta.get("visibility", ws.visibility.value))
        with contextlib.suppress(ValueError, TypeError):
            ws.workspace_type = WorkspaceType(meta.get("workspace_type", ws.workspace_type.value))
        db.add(ws)
        db.commit()

    result = _import_backup_into_workspace(workspace_id, backup, current_user, db, files_dir=files_dir)
    return result
