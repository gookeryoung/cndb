"""文档问题清单服务：创建 / 列表 / 详情 / 评论 / 关闭 / 重开.

权限模型与数据表问题清单一致：所有工作区成员可提交问题与评论、查看列表/详情；
关闭/重开由 owner/editor 或创建者本人操作。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import (
    DI_ACTION_CLOSED,
    DI_ACTION_CREATED,
    DI_ACTION_REOPENED,
    Document,
    DocumentIssue,
    DocumentIssueComment,
    DocumentIssueEvent,
)
from cndb.plugins.documents.services import visibility
from cndb.plugins.issues.models import ISSUE_CATEGORIES, ISSUE_STATUS_CLOSED, ISSUE_STATUS_OPEN
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role

STATUS_FILTERS = ("open", "closed", "all")


def _visible_document_or_404(db: Session, workspace_id: int, document_id: int, user: User) -> Document:
    """取文档并校验可见性（草稿/未发布版对非创建者与所有者不可见）."""
    from cndb.plugins.documents.services import visibility

    return visibility.get_visible_document_or_404(db, workspace_id, document_id, user)


def require_member(db: Session, workspace_id: int, user: User) -> WorkspaceRole:
    """校验用户是工作区成员（问题清单的读与提交均只要求成员身份）."""
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("工作区不存在")
    role = get_member_role(user, ws, db)
    if role is None:
        raise PermissionDeniedError("非工作区成员")
    return role


def create_issue(
    db: Session,
    workspace_id: int,
    document_id: int,
    user: User,
    *,
    title: str,
    description: str = "",
    category: str = "other",
) -> DocumentIssue:
    """在文档下创建问题并写入 created 状态事件.

    Raises:
        BadRequestError: 类别非法。
        NotFoundError: 文档不存在或已删除。
    """
    require_member(db, workspace_id, user)
    if category not in ISSUE_CATEGORIES:
        raise BadRequestError(f"非法的问题类别: {category}")
    # 可见性：不能在看不见的文档（他人草稿/未发布版）上提交问题
    doc = _visible_document_or_404(db, workspace_id, document_id, user)

    issue = DocumentIssue(
        workspace_id=workspace_id,
        document_id=doc.id,
        title=title,
        description=description,
        category=category,
        status=ISSUE_STATUS_OPEN,
        created_by_id=user.id,
    )
    db.add(issue)
    db.flush()
    db.add(
        DocumentIssueEvent(
            issue_id=issue.id,
            action=DI_ACTION_CREATED,
            actor_id=user.id,
            created_at=dt.datetime.now(dt.UTC),
        )
    )
    db.commit()
    db.refresh(issue)
    return issue


def list_issues(
    db: Session,
    workspace_id: int,
    user: User,
    *,
    document_id: int | None = None,
    status: str = "open",
) -> list[dict[str, Any]]:
    """问题列表（status=open/closed/all），按 id 倒序，附评论数与文档标题."""
    require_member(db, workspace_id, user)
    if status not in STATUS_FILTERS:
        raise BadRequestError(f"不支持的问题状态: {status}，可选 {'/'.join(STATUS_FILTERS)}")

    stmt = select(DocumentIssue).where(DocumentIssue.workspace_id == workspace_id)
    if document_id is not None:
        # 指定文档时先校验该文档可见（否则等于变相探测他人草稿）
        _visible_document_or_404(db, workspace_id, document_id, user)
        stmt = stmt.where(DocumentIssue.document_id == document_id)
    if status in (ISSUE_STATUS_OPEN, ISSUE_STATUS_CLOSED):
        stmt = stmt.where(DocumentIssue.status == status)
    # 可见性：只返回"文档对当前用户可见"的问题
    stmt = stmt.where(
        DocumentIssue.document_id.in_(
            select(Document.id).where(
                Document.workspace_id == workspace_id,
                Document.is_deleted == False,  # noqa: E712
                visibility.visible_condition(db, workspace_id, user),
            )
        )
    )
    issues = list(db.scalars(stmt.order_by(DocumentIssue.id.desc())).all())

    counts: dict[int, int] = {}
    titles: dict[int, str] = {}
    if issues:
        issue_ids = [i.id for i in issues]
        doc_ids = {i.document_id for i in issues}
        rows = (
            db.query(DocumentIssueComment.issue_id, func.count(DocumentIssueComment.id))
            .filter(DocumentIssueComment.issue_id.in_(issue_ids))
            .group_by(DocumentIssueComment.issue_id)
            .all()
        )
        counts = {int(issue_id): int(n) for issue_id, n in rows}
        titles: dict[int, str] = {}
        for doc_id, doc_title in db.query(Document.id, Document.title).filter(Document.id.in_(doc_ids)).all():
            titles[int(doc_id)] = str(doc_title)
    return [
        serialize_issue(i, comment_count=counts.get(i.id, 0), document_title=titles.get(i.document_id)) for i in issues
    ]


def get_issue_or_404(db: Session, workspace_id: int, issue_id: int, user: User | None = None) -> DocumentIssue:
    """按 id 取问题并校验工作区归属与文档可见性（不匹配一律 404）.

    ``user`` 非空时同时校验问题所属文档对该用户可见，避免通过问题详情
    探测/读取他人草稿上的讨论。
    """
    issue = db.get(DocumentIssue, issue_id)
    if issue is None or issue.workspace_id != workspace_id:
        raise NotFoundError("问题不存在")
    if user is not None:
        _visible_document_or_404(db, workspace_id, issue.document_id, user)
    return issue


def get_issue_detail(db: Session, issue: DocumentIssue) -> dict[str, Any]:
    """问题详情：本体 + 评论 + 事件流."""
    comments = (
        db.query(DocumentIssueComment)
        .filter(DocumentIssueComment.issue_id == issue.id)
        .order_by(DocumentIssueComment.id.asc())
        .all()
    )
    events = (
        db.query(DocumentIssueEvent)
        .filter(DocumentIssueEvent.issue_id == issue.id)
        .order_by(DocumentIssueEvent.id.asc())
        .all()
    )
    doc = db.get(Document, issue.document_id)
    data = serialize_issue(issue, comment_count=len(comments), document_title=doc.title if doc else None)
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
        {"id": e.id, "action": e.action, "actor_id": e.actor_id, "created_at": _iso(e.created_at)} for e in events
    ]
    return data


def add_comment(db: Session, issue: DocumentIssue, user: User, content: str) -> dict[str, Any]:
    """添加评论."""
    comment = DocumentIssueComment(issue_id=issue.id, content=content, created_by_id=user.id)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return {
        "id": comment.id,
        "content": comment.content,
        "created_by_id": comment.created_by_id,
        "created_at": _iso(comment.created_at),
    }


def can_manage_issue(issue: DocumentIssue, user: User, role: WorkspaceRole | None) -> bool:
    """关闭/重开权限：owner/editor，或创建者本人."""
    if role in (WorkspaceRole.OWNER, WorkspaceRole.EDITOR):
        return True
    return issue.created_by_id is not None and issue.created_by_id == user.id


def close_issue(db: Session, issue: DocumentIssue, user: User) -> DocumentIssue:
    """关闭问题（已关闭时 409），写 closed 事件."""
    if issue.status == ISSUE_STATUS_CLOSED:
        raise ConflictError("问题已处于关闭状态")
    issue.status = ISSUE_STATUS_CLOSED
    db.add(
        DocumentIssueEvent(
            issue_id=issue.id,
            action=DI_ACTION_CLOSED,
            actor_id=user.id,
            created_at=dt.datetime.now(dt.UTC),
        )
    )
    db.commit()
    db.refresh(issue)
    return issue


def reopen_issue(db: Session, issue: DocumentIssue, user: User) -> DocumentIssue:
    """重开问题（已打开时 409），写 reopened 事件."""
    if issue.status == ISSUE_STATUS_OPEN:
        raise ConflictError("问题已处于打开状态")
    issue.status = ISSUE_STATUS_OPEN
    db.add(
        DocumentIssueEvent(
            issue_id=issue.id,
            action=DI_ACTION_REOPENED,
            actor_id=user.id,
            created_at=dt.datetime.now(dt.UTC),
        )
    )
    db.commit()
    db.refresh(issue)
    return issue


def serialize_issue(
    issue: DocumentIssue,
    *,
    comment_count: int,
    document_title: str | None = None,
) -> dict[str, Any]:
    """问题序列化（列表/详情共用字段）."""
    return {
        "id": issue.id,
        "workspace_id": issue.workspace_id,
        "document_id": issue.document_id,
        "document_title": document_title,
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
    "STATUS_FILTERS",
    "add_comment",
    "can_manage_issue",
    "close_issue",
    "create_issue",
    "get_issue_detail",
    "get_issue_or_404",
    "list_issues",
    "reopen_issue",
    "require_member",
    "serialize_issue",
]
