"""documents 插件路由：文档问题清单 API.

端点（挂 ``/{workspace_id}/document-issues``，独立于 documents 路径）：

- GET    ""                         列表（成员；可按 document_id / status 过滤）
- POST   ""                         提交问题（成员）
- GET    /{issue_id}                详情（本体 + 评论 + 状态事件）
- POST   /{issue_id}/comments       评论（成员）
- POST   /{issue_id}/close          关闭（owner/editor 或创建者）
- POST   /{issue_id}/reopen         重开（owner/editor 或创建者）

与数据表问题清单同构，仅载体由 table_id 换成 document_id。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import PermissionDeniedError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents import services
from cndb.plugins.documents.schemas import DocumentIssueCommentCreate, DocumentIssueCreate

router = APIRouter(prefix="/{workspace_id}/document-issues", tags=["documents"])


@router.get("")
def list_issues(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    document_id: Annotated[int | None, Query(description="仅列出该文档的问题")] = None,
    status: Annotated[str, Query(description="open / closed / all")] = "open",
) -> dict[str, Any]:
    """问题列表（默认待处理）."""
    items = services.issues.list_issues(db, workspace_id, current_user, document_id=document_id, status=status)
    return {"items": items, "total": len(items)}


@router.post("", status_code=201)
def create_issue(
    workspace_id: int,
    payload: DocumentIssueCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """提交问题（所有工作区成员）."""
    issue = services.issues.create_issue(
        db,
        workspace_id,
        payload.document_id,
        current_user,
        title=payload.title,
        description=payload.description,
        category=payload.category,
    )
    return services.issues.get_issue_detail(db, issue)


@router.get("/{issue_id}")
def get_issue(
    workspace_id: int,
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """问题详情（含评论与状态事件）."""
    services.issues.require_member(db, workspace_id, current_user)
    issue = services.issues.get_issue_or_404(db, workspace_id, issue_id, current_user)
    return services.issues.get_issue_detail(db, issue)


@router.post("/{issue_id}/comments", status_code=201)
def add_comment(
    workspace_id: int,
    issue_id: int,
    payload: DocumentIssueCommentCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """添加评论."""
    services.issues.require_member(db, workspace_id, current_user)
    issue = services.issues.get_issue_or_404(db, workspace_id, issue_id, current_user)
    return services.issues.add_comment(db, issue, current_user, payload.content)


def _transition(workspace_id: int, issue_id: int, current_user: User, db: Session, *, action: str) -> dict[str, Any]:
    """关闭/重开公共流程：权限校验（owner/editor 或创建者）+ 状态流转."""
    role = services.issues.require_member(db, workspace_id, current_user)
    issue = services.issues.get_issue_or_404(db, workspace_id, issue_id, current_user)
    if not services.issues.can_manage_issue(issue, current_user, role):
        raise PermissionDeniedError("仅 owner/editor 或创建者可操作")
    if action == "close":
        return services.issues.get_issue_detail(db, services.issues.close_issue(db, issue, current_user))
    return services.issues.get_issue_detail(db, services.issues.reopen_issue(db, issue, current_user))


@router.post("/{issue_id}/close")
def close_issue(
    workspace_id: int,
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """关闭问题."""
    return _transition(workspace_id, issue_id, current_user, db, action="close")


@router.post("/{issue_id}/reopen")
def reopen_issue(
    workspace_id: int,
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """重开问题."""
    return _transition(workspace_id, issue_id, current_user, db, action="reopen")


__all__ = ["router"]
