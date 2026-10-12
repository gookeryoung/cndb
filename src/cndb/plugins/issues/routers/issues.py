"""issues 插件路由：问题清单 API（设计 3.5 节）.

端点：
- POST /{workspace_id}/tables/{table_id}/issues               — 提交问题（所有成员）
- GET  /{workspace_id}/tables/{table_id}/issues               — 列表（status=open/closed/all）
- GET  /{workspace_id}/tables/{table_id}/issues/{issue_id}    — 详情（评论 + 事件流）
- POST /{workspace_id}/tables/{table_id}/issues/{issue_id}/comments — 评论（所有成员）
- POST /{workspace_id}/tables/{table_id}/issues/{issue_id}/close    — 关闭（owner/editor 或创建者）
- POST /{workspace_id}/tables/{table_id}/issues/{issue_id}/reopen   — 重开（owner/editor 或创建者）
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.issues import services
from cndb.plugins.issues.schemas import IssueCommentCreate, IssueCreate
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.core.access import TableAction, get_table_or_404

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/issues", tags=["issues"])


def _table_for_read(
    workspace_id: int,
    table_id: int,
    current_user: User,
    db: Session,
) -> DataTable:
    """取表并校验当前成员可读（所有成员均可访问问题清单）."""
    return get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)


@router.post("", status_code=201)
def create_issue(
    workspace_id: int,
    table_id: int,
    payload: IssueCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """提交问题（所有工作区成员）."""
    table = _table_for_read(workspace_id, table_id, current_user, db)
    issue = services.create_issue(
        db,
        table,
        current_user,
        title=payload.title,
        description=payload.description,
        category=payload.category,
    )
    return services.get_issue_detail(db, issue)


@router.get("")
def list_issues(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    status: str = Query(default="open", pattern="^(open|closed|all)$"),
) -> dict[str, Any]:
    """问题列表，默认展示 open（GitHub 式两栏过滤）."""
    table = _table_for_read(workspace_id, table_id, current_user, db)
    items = services.list_issues(db, table.id, status=status)
    return {"items": items, "total": len(items)}


@router.get("/{issue_id}")
def get_issue(
    workspace_id: int,
    table_id: int,
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """问题详情（本体 + 评论 + 事件流）."""
    table = _table_for_read(workspace_id, table_id, current_user, db)
    issue = services.get_issue_or_404(db, table, issue_id)
    return services.get_issue_detail(db, issue)


@router.post("/{issue_id}/comments", status_code=201)
def add_comment(
    workspace_id: int,
    table_id: int,
    issue_id: int,
    payload: IssueCommentCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """添加评论（所有成员）."""
    table = _table_for_read(workspace_id, table_id, current_user, db)
    issue = services.get_issue_or_404(db, table, issue_id)
    return services.add_comment(db, issue, current_user, payload.content)


def _transition(
    workspace_id: int,
    table_id: int,
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    *,
    action: str,
):
    """关闭/重开公共流程：权限校验（owner/editor 或创建者）+ 状态流转."""
    table = _table_for_read(workspace_id, table_id, current_user, db)
    issue = services.get_issue_or_404(db, table, issue_id)
    role = services.require_issue_actor_role(db, table, current_user)
    if not services.can_manage_issue(issue, current_user, role):
        raise HTTPException(status_code=403, detail="仅 owner/editor 或创建者可操作")
    if action == "close":
        return services.get_issue_detail(db, services.close_issue(db, issue, current_user))
    return services.get_issue_detail(db, services.reopen_issue(db, issue, current_user))


@router.post("/{issue_id}/close")
def close_issue(
    workspace_id: int,
    table_id: int,
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """关闭问题."""
    return _transition(workspace_id, table_id, issue_id, current_user, db, action="close")


@router.post("/{issue_id}/reopen")
def reopen_issue(
    workspace_id: int,
    table_id: int,
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """重开问题."""
    return _transition(workspace_id, table_id, issue_id, current_user, db, action="reopen")


__all__ = ["router"]
