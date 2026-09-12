"""审计日志路由（只读）."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import AuditLog
from cndb.plugins.tables.routers.tables import _check_table_permission, _get_table_or_404
from cndb.plugins.tables.schemas.comments import AuditLogResponse
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(tags=["audit"])


@router.get(
    "/{workspace_id}/tables/{table_id}/audit",
    response_model=list[AuditLogResponse],
)
def list_audit_logs(  # noqa: PLR0913, PLR0917
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    action: str | None = None,
    row_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[AuditLog]:
    """列出表的审计日志，可按 action 或 row_id 过滤."""
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    _get_table_or_404(table_id, workspace_id, db)
    q = db.query(AuditLog).filter(AuditLog.table_id == table_id)
    if action:
        q = q.filter(AuditLog.action == action)
    if row_id is not None:
        q = q.filter(AuditLog.target_id == row_id)
    return q.order_by(AuditLog.id.desc()).limit(limit).all()


__all__ = ["router"]
