"""审计日志路由（只读）."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import AuditLog
from cndb.plugins.tables.schemas.comments import AuditLogResponse
from cndb.plugins.tables.services.core.access import (
    TableAction,
    check_workspace_permission,
    get_hidden_field_names,
    get_table_or_404,
)
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(tags=["audit"])


@router.get(
    "/{workspace_id}/tables/{table_id}/audit",
    response_model=list[AuditLogResponse],
)
def list_audit_logs(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    action: str | None = None,
    row_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """列出表的审计日志，可按 action 或 row_id 过滤.

    审计日志的 ``detail`` 保存了行数据的快照，因此**可见性口径必须与记录读取一致**：
    - 需要对该表有 READ 权限（受限表对普通编辑器不可读，其审计同样不可读）；
    - 按 ``row_filters`` 裁剪到调用者可见的行（target_id 为空的结构类日志保留）；
    - 按调用者角色剔除 ``hidden_fields`` 中的字段。
    """
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    table = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    q = db.query(AuditLog).filter(AuditLog.table_id == table_id)
    if action:
        q = q.filter(AuditLog.action == action)
    if row_id is not None:
        q = q.filter(AuditLog.target_id == row_id)

    # 行级过滤：只返回调用者可见行上的审计条目（无 target_id 的结构类日志不受影响）
    from sqlalchemy import MetaData, Table, or_, select

    sa_table = Table(table.db_table_name, MetaData(), autoload_with=db.bind)
    row_scope = _row_scope_condition(db, table, sa_table)
    if row_scope is not None:
        visible_row_ids = select(sa_table.c.id).where(row_scope)
        q = q.filter(or_(AuditLog.target_id.is_(None), AuditLog.target_id.in_(visible_row_ids)))

    entries = q.order_by(AuditLog.id.desc()).limit(limit).all()

    # 字段级隐藏：审计 detail 里同样不能出现调用者看不到的字段。
    # 注意必须构造**响应副本**而不是改写 ORM 对象 —— 直接改 entry.detail 会把这个
    # 会话里的对象标脏，共享会话（如测试/长事务）下会被 flush 回库，等于真的删了数据。
    hidden = get_hidden_field_names(db, table, current_user) or set()
    result: list[dict[str, Any]] = []
    for entry in entries:
        detail = dict(entry.detail or {})
        for name in hidden:
            detail.pop(name, None)
        result.append(
            {
                "id": entry.id,
                "table_id": entry.table_id,
                "action": entry.action,
                "actor_id": entry.actor_id,
                "target_id": entry.target_id,
                "detail": detail,
                "created_at": entry.created_at,
            }
        )
    return result


def _row_scope_condition(db: Session, table: Any, sa_table: Any) -> Any | None:
    """编译表的行级过滤条件（无配置返回 None），与记录读取接口同一套逻辑."""
    from cndb.plugins.tables.services.core.access import get_row_scope, row_filter_conjunction
    from cndb.plugins.tables.services.core.query import compile_filters

    scope = get_row_scope(db, table)
    if not scope:
        return None
    return compile_filters(table, sa_table, scope, row_filter_conjunction(db, table))


__all__ = ["router"]
