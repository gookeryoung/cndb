"""issues 插件服务层：问题清单业务逻辑.

权限模型（设计 3.5 节）：
- 所有工作区成员可提交问题、评论、查看列表/详情；
- 关闭/重开：owner/editor，或创建者本人关闭自己的问题。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.issues.models import (
    ISSUE_ACTION_CLOSED,
    ISSUE_ACTION_CREATED,
    ISSUE_ACTION_REOPENED,
    ISSUE_CATEGORIES,
    ISSUE_STATUS_CLOSED,
    ISSUE_STATUS_OPEN,
    Issue,
    IssueComment,
    IssueEvent,
)
from cndb.plugins.tables.models import DataTable
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role


def create_issue(
    db: Session,
    table: DataTable,
    user: User,
    *,
    title: str,
    description: str = "",
    category: str = "other",
) -> Issue:
    """创建问题并写入 created 状态事件.

    Raises:
        HTTPException(400): category 非法.
    """
    if category not in ISSUE_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"非法的问题类别: {category}")
    issue = Issue(
        workspace_id=table.workspace_id,
        table_id=table.id,
        title=title,
        description=description,
        category=category,
        status=ISSUE_STATUS_OPEN,
        created_by_id=user.id,
    )
    db.add(issue)
    db.flush()
    db.add(
        IssueEvent(
            issue_id=issue.id,
            action=ISSUE_ACTION_CREATED,
            actor_id=user.id,
            created_at=dt.datetime.now(dt.UTC),
        )
    )
    db.commit()
    db.refresh(issue)
    return issue


def list_issues(
    db: Session,
    table_id: int,
    *,
    status: str = "open",
) -> list[dict[str, Any]]:
    """问题列表（status=open/closed/all），按创建时间倒序，附 comment_count."""
    q = db.query(Issue).filter(Issue.table_id == table_id)
    if status == ISSUE_STATUS_OPEN:
        q = q.filter(Issue.status == ISSUE_STATUS_OPEN)
    elif status == ISSUE_STATUS_CLOSED:
        q = q.filter(Issue.status == ISSUE_STATUS_CLOSED)
    issues = q.order_by(Issue.id.desc()).all()

    counts: dict[int, int] = {}
    if issues:
        from sqlalchemy import func

        rows = (
            db.query(IssueComment.issue_id, func.count(IssueComment.id))
            .filter(IssueComment.issue_id.in_([i.id for i in issues]))
            .group_by(IssueComment.issue_id)
            .all()
        )
        counts = {int(issue_id): int(n) for issue_id, n in rows}
    return [_serialize_issue(i, comment_count=counts.get(i.id, 0)) for i in issues]


def get_issue_or_404(db: Session, table: DataTable, issue_id: int) -> Issue:
    """按 id 取问题并校验归属（表与工作区不匹配一律 404）."""
    issue = db.get(Issue, issue_id)
    if issue is None or issue.table_id != table.id or issue.workspace_id != table.workspace_id:
        raise HTTPException(status_code=404, detail="问题不存在")
    return issue


def get_issue_detail(db: Session, issue: Issue) -> dict[str, Any]:
    """问题详情：本体 + 评论 + 事件流."""
    comments = db.query(IssueComment).filter(IssueComment.issue_id == issue.id).order_by(IssueComment.id.asc()).all()
    events = db.query(IssueEvent).filter(IssueEvent.issue_id == issue.id).order_by(IssueEvent.id.asc()).all()
    data = _serialize_issue(issue, comment_count=len(comments))
    data["comments"] = [
        {
            "id": c.id,
            "content": c.content,
            "created_by_id": c.created_by_id,
            "created_at": _iso(c.created_at),
        }
        for c in comments
    ]
    data["events"] = [
        {
            "id": e.id,
            "action": e.action,
            "actor_id": e.actor_id,
            "created_at": _iso(e.created_at),
        }
        for e in events
    ]
    return data


def add_comment(db: Session, issue: Issue, user: User, content: str) -> dict[str, Any]:
    """添加评论."""
    comment = IssueComment(issue_id=issue.id, content=content, created_by_id=user.id)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return {
        "id": comment.id,
        "content": comment.content,
        "created_by_id": comment.created_by_id,
        "created_at": _iso(comment.created_at),
    }


def can_manage_issue(issue: Issue, user: User, role: WorkspaceRole | None) -> bool:
    """关闭/重开权限：owner/editor，或创建者本人."""
    if role in (WorkspaceRole.OWNER, WorkspaceRole.EDITOR):
        return True
    return issue.created_by_id is not None and issue.created_by_id == user.id


def close_issue(db: Session, issue: Issue, user: User) -> Issue:
    """关闭问题（已关闭时 409），写 closed 事件."""
    if issue.status == ISSUE_STATUS_CLOSED:
        raise HTTPException(status_code=409, detail="问题已处于关闭状态")
    issue.status = ISSUE_STATUS_CLOSED
    db.add(
        IssueEvent(
            issue_id=issue.id,
            action=ISSUE_ACTION_CLOSED,
            actor_id=user.id,
            created_at=dt.datetime.now(dt.UTC),
        )
    )
    db.commit()
    db.refresh(issue)
    return issue


def reopen_issue(db: Session, issue: Issue, user: User) -> Issue:
    """重开问题（已打开时 409），写 reopened 事件."""
    if issue.status == ISSUE_STATUS_OPEN:
        raise HTTPException(status_code=409, detail="问题已处于打开状态")
    issue.status = ISSUE_STATUS_OPEN
    db.add(
        IssueEvent(
            issue_id=issue.id,
            action=ISSUE_ACTION_REOPENED,
            actor_id=user.id,
            created_at=dt.datetime.now(dt.UTC),
        )
    )
    db.commit()
    db.refresh(issue)
    return issue


def require_issue_actor_role(db: Session, table: DataTable, user: User) -> WorkspaceRole | None:
    """取当前用户在表所属工作区的角色（供路由层权限判定）."""
    ws = db.get(Workspace, table.workspace_id)
    if ws is None:  # pragma: no cover - 表必然挂在有效工作区下
        return None
    return get_member_role(user, ws, db)


def _serialize_issue(issue: Issue, *, comment_count: int) -> dict[str, Any]:
    """问题序列化（列表/详情共用字段）."""
    return {
        "id": issue.id,
        "workspace_id": issue.workspace_id,
        "table_id": issue.table_id,
        "title": issue.title,
        "description": issue.description,
        "category": issue.category,
        "status": issue.status,
        "created_by_id": issue.created_by_id,
        "comment_count": comment_count,
        "created_at": _iso(issue.created_at),
        "updated_at": _iso(issue.updated_at),
    }


def _iso(value: Any) -> str | None:
    """datetime 统一转 ISO 字符串."""
    return value.isoformat() if value is not None else None


__all__ = [
    "add_comment",
    "can_manage_issue",
    "close_issue",
    "create_issue",
    "get_issue_detail",
    "get_issue_or_404",
    "list_issues",
    "reopen_issue",
    "require_issue_actor_role",
]
