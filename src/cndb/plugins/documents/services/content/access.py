"""文档访问门控：取文档（含已删除 / 任意状态）/ 取工作区 / 角色校验."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.core.errors import NotFoundError
from cndb.plugins.documents.models import Document
from cndb.plugins.workspaces.models import WorkspaceRole
from cndb.plugins.workspaces.permissions import raise_permission_denied, workspace_data_role

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User


def get_document_or_404(db: Session, workspace_id: int, doc_id: int) -> Document:
    """取工作区下未删除文档，不存在抛 NotFoundError."""
    doc = db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.workspace_id == workspace_id,
            Document.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if doc is None:
        raise NotFoundError("文档不存在")
    return doc


def get_deleted_document_or_404(db: Session, workspace_id: int, doc_id: int) -> Document:
    """取工作区下**已删除**文档（回收站操作专用），不存在抛 NotFoundError."""
    doc = db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.workspace_id == workspace_id,
            Document.is_deleted == True,  # noqa: E712
        )
    ).scalar_one_or_none()
    if doc is None:
        raise NotFoundError("回收站中不存在该文档")
    return doc


def get_document_any_state_or_404(db: Session, workspace_id: int, doc_id: int) -> Document:
    """取工作区下文档（不过滤删除态），不存在抛 NotFoundError.

    供"先判断删除态再决定语义"的流程使用（如彻底删除对未删除文档返回 409）。
    """
    doc = db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.workspace_id == workspace_id,
        )
    ).scalar_one_or_none()
    if doc is None:
        raise NotFoundError("文档不存在")
    return doc


def require_editor(db: Session, workspace_id: int, user: User) -> WorkspaceRole:
    """校验用户是工作区 editor/owner（viewer 或非成员拒绝写操作）."""
    ws = _get_workspace(db, workspace_id)
    role = workspace_data_role(user, ws, db)
    if role is None or role == WorkspaceRole.VIEWER:
        # ADR 0047：403 文案带角色与拥有者指引（唯一出口）
        raise_permission_denied(db, ws, user, requirement="仅编辑者及以上角色可执行此操作")
    return role


def _get_workspace(db: Session, workspace_id: int):
    from cndb.plugins.workspaces.models import Workspace

    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("工作区不存在")
    return ws
