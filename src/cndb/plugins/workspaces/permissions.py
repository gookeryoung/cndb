"""工作区角色判定辅助函数（非 FastAPI 权限类，便于单元测试直接调用）."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from cndb.plugins.workspaces.models import ROLE_RANK, Workspace, WorkspaceMember, WorkspaceRole

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User


def get_member_role(user: User | None, workspace: Workspace, db: Session) -> WorkspaceRole | None:
    """返回用户在工作区的角色枚举，非成员返回 None."""
    if user is None:
        return None
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user.id)
        .first()
    )
    return member.role if member else None


def has_role(user: User | None, workspace: Workspace, minimum: WorkspaceRole, db: Session) -> bool:
    """判断用户角色是否达到最低要求."""
    role = get_member_role(user, workspace, db)
    if role is None:
        return False
    return ROLE_RANK[role] >= ROLE_RANK[minimum]


__all__ = ["get_member_role", "has_role"]
