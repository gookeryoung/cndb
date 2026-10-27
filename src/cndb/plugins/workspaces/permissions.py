"""工作区角色判定辅助函数（非 FastAPI 权限类，便于单元测试直接调用）."""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

from sqlalchemy.orm import Session

from cndb.core.errors import PermissionDeniedError
from cndb.plugins.workspaces.models import (
    ROLE_RANK,
    WORKSPACE_ROLE_LABELS,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User


def get_member_role(user: User | None, workspace: Workspace, db: Session) -> WorkspaceRole | None:
    """返回用户在工作区的角色枚举，非成员返回 None."""
    if user is None:  # pragma: no cover - Depends 保证 user 非 None
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
    if role is None:  # pragma: no cover - 由 get_member_role 内部处理
        return False
    return ROLE_RANK[role] >= ROLE_RANK[minimum]


def get_workspace_owner_display_name(db: Session, workspace: Workspace) -> str | None:
    """返回工作区拥有者的展示名（nickname 回退 username），无 owner 成员返回 None."""
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.role == WorkspaceRole.OWNER)
        .first()
    )
    if member is None or member.user is None:  # pragma: no cover - user 为关系必载
        return None
    return member.user.nickname or member.user.username


def permission_denied_detail(
    db: Session,
    workspace: Workspace,
    user: User,
    *,
    scope: str = "",
    requirement: str = "",
) -> str:
    """构造 403 权限不足的中文文案（ADR 0047 唯一出口）.

    Args:
        db: 数据库会话。
        workspace: 目标工作区。
        user: 当前用户。
        scope: 被拒层级描述（如 ``"表级"`` / ``"视图级"``；空串表示不带层级）。
        requirement: 额外要求描述（如 ``"仅 owner/editor 可合并修改申请"``）。
    """
    role = get_member_role(user, workspace, db)
    scope_part = f"{scope}权限不足" if scope else "权限不足"
    owner_name = get_workspace_owner_display_name(db, workspace)
    if owner_name:
        contact = (
            f"；如需加入，请联系工作区拥有者【{owner_name}】"
            if role is None
            else (f"；如需提升权限，请联系工作区拥有者【{owner_name}】")
        )
    else:
        contact = ""
    if role is None:
        detail = f"你不是该工作区成员，{scope_part}{contact}"
    else:
        label = WORKSPACE_ROLE_LABELS.get(role.value, role.value)
        detail = f"当前用户在此工作区的角色为【{label}】，{scope_part}{contact}"
    if requirement:
        detail = f"{detail}（{requirement}）"
    return detail


def raise_permission_denied(
    db: Session,
    workspace: Workspace,
    user: User,
    *,
    scope: str = "",
    requirement: str = "",
    code: str | None = None,
) -> NoReturn:
    """按 ADR 0047 模板构造文案并抛出 ``PermissionDeniedError``（HTTP 403）."""
    raise PermissionDeniedError(
        permission_denied_detail(db, workspace, user, scope=scope, requirement=requirement),
        code=code,
    )


__all__ = [
    "get_member_role",
    "get_workspace_owner_display_name",
    "has_role",
    "permission_denied_detail",
    "raise_permission_denied",
]
