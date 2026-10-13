"""change_requests 插件路由：修改申请 API（设计 3.4 节）.

端点：
- POST /{workspace_id}/tables/{table_id}/change-requests                  — 创建申请（所有成员）
- GET  /{workspace_id}/tables/{table_id}/change-requests                  — 列表（scope=open/all/mine/merged）
- GET  /{workspace_id}/tables/{table_id}/change-requests/{request_id}     — 详情（items diff + 动作流水）
- POST /{workspace_id}/tables/{table_id}/change-requests/{request_id}/merge      — 逐项决策合并（owner/editor）
- POST /{workspace_id}/tables/{table_id}/change-requests/{request_id}/close      — 关闭（owner/editor 或提交人）
- POST /{workspace_id}/tables/{table_id}/change-requests/{request_id}/reopen    — 重开（owner/editor）
- POST /{workspace_id}/tables/{table_id}/change-requests/{request_id}/update-base — 刷新基准（仅提交人）
- POST /{workspace_id}/tables/{table_id}/change-requests/{request_id}/comments   — 评论（所有成员）
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.change_requests import services
from cndb.plugins.change_requests.schemas import (
    ChangeCommentCreate,
    ChangeRequestCreate,
    MergePayload,
)
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.core.access import TableAction, get_table_or_404
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/change-requests", tags=["change_requests"])


def _table_for_read(
    workspace_id: int,
    table_id: int,
    current_user: User,
    db: Session,
) -> DataTable:
    """取表并校验当前成员可读（所有成员均可查看/发起申请）."""
    return get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)


@router.post("", status_code=201)
def create_request(
    workspace_id: int,
    table_id: int,
    payload: ChangeRequestCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """创建修改申请（支持多 item；base_values 由服务端快照）."""
    table = _table_for_read(workspace_id, table_id, current_user, db)
    cr = services.create_request(
        db,
        table,
        current_user,
        title=payload.title,
        description=payload.description,
        items=[item.model_dump() for item in payload.items],
    )
    return services.get_request_detail(db, cr, table)


@router.get("")
def list_requests(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    scope: str = Query(default="open", pattern="^(open|all|mine|merged)$"),
) -> dict[str, Any]:
    """申请列表，附 conflicts_count 与当前用户写模式 write_mode（direct/change_request/denied）."""
    table = _table_for_read(workspace_id, table_id, current_user, db)
    items = services.list_requests(db, table.id, scope=scope, user=current_user)
    return {
        "items": items,
        "total": len(items),
        "write_mode": services.resolve_write_mode(db, table, current_user),
    }


@router.get("/{request_id}")
def get_request(
    workspace_id: int,
    table_id: int,
    request_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """申请详情（items 字段级 diff + 动作流水）."""
    table = _table_for_read(workspace_id, table_id, current_user, db)
    cr = services.get_request_or_404(db, table, request_id)
    return services.get_request_detail(db, cr, table)


@router.post("/{request_id}/merge")
def merge_request(
    workspace_id: int,
    table_id: int,
    request_id: int,
    payload: MergePayload,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """逐项决策合并（仅 owner/editor），落库后申请置 merged."""
    table = _table_for_read(workspace_id, table_id, current_user, db)
    cr = services.get_request_or_404(db, table, request_id)
    decisions = {d.item_id: d.action for d in payload.items}
    return services.merge_request(db, cr, table, current_user, decisions, payload.comment)


def _transition(
    db: Session,
    table: DataTable,
    request_id: int,
    current_user: User,
    *,
    action: str,
) -> dict[str, Any]:
    """close/reopen/update-base 公共流程."""
    cr = services.get_request_or_404(db, table, request_id)
    if action == "close":
        role = services.require_reviewer_role(db, table, current_user)
        cr = services.close_request(db, cr, current_user, role)
    elif action == "reopen":
        role = services.require_reviewer_role(db, table, current_user)
        if role not in (WorkspaceRole.OWNER, WorkspaceRole.EDITOR):
            raise HTTPException(status_code=403, detail="仅 owner/editor 可重开")
        cr = services.reopen_request(db, cr, current_user)
    else:  # update-base
        cr = services.update_base(db, cr, table, current_user)
    # 返回完整详情（含 items/actions），与详情页缓存契约一致（缺 items 会致前端渲染崩溃）
    return services.get_request_detail(db, cr, table)


@router.post("/{request_id}/close")
def close_request(
    workspace_id: int,
    table_id: int,
    request_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """关闭申请（owner/editor 或提交人本人）."""
    table = _table_for_read(workspace_id, table_id, current_user, db)
    return _transition(db, table, request_id, current_user, action="close")


@router.post("/{request_id}/reopen")
def reopen_request(
    workspace_id: int,
    table_id: int,
    request_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """重开申请（仅 owner/editor）."""
    table = _table_for_read(workspace_id, table_id, current_user, db)
    return _transition(db, table, request_id, current_user, action="reopen")


@router.post("/{request_id}/update-base")
def update_base(
    workspace_id: int,
    table_id: int,
    request_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """刷新基准（仅提交人，stale 复位）."""
    table = _table_for_read(workspace_id, table_id, current_user, db)
    return _transition(db, table, request_id, current_user, action="update-base")


@router.post("/{request_id}/comments", status_code=201)
def add_comment(
    workspace_id: int,
    table_id: int,
    request_id: int,
    payload: ChangeCommentCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """添加评论（所有成员，写动作流水）."""
    table = _table_for_read(workspace_id, table_id, current_user, db)
    cr = services.get_request_or_404(db, table, request_id)
    return services.add_comment(db, cr, current_user, payload.content)


__all__ = ["router"]
