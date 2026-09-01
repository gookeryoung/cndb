"""工作区成员角色判定与 DRF 权限类."""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from rest_framework import permissions
from rest_framework.request import Request

from cndb.workspaces.models import Workspace, WorkspaceMember

# 角色等级：数值越大权限越高
ROLE_RANK: dict[str, int] = {
    WorkspaceMember.Role.OWNER: 4,
    WorkspaceMember.Role.ADMIN: 3,
    WorkspaceMember.Role.EDITOR: 2,
    WorkspaceMember.Role.COMMENTER: 1,
    WorkspaceMember.Role.VIEWER: 0,
}


def get_member_role(user: AbstractBaseUser | None, workspace: Workspace) -> str | None:
    """返回用户在工作区的角色，非成员返回 None。"""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    member = workspace.members.filter(user=user).only("role").first()
    return member.role if member else None


def has_role(user: AbstractBaseUser | None, workspace: Workspace, minimum: str) -> bool:
    """判断用户角色是否达到最低要求。"""
    role = get_member_role(user, workspace)
    if role is None:
        return False
    return ROLE_RANK[role] >= ROLE_RANK[minimum]


class IsWorkspaceMember(permissions.BasePermission):
    """对象级权限：仅工作区成员可访问，变更要求 ADMIN 及以上。"""

    def has_object_permission(self, request: Request, _view: object, obj: object) -> bool:
        """读取对所有成员开放，写操作要求 ADMIN 及以上角色."""
        if not isinstance(obj, Workspace):
            return False
        if request.method in permissions.SAFE_METHODS:
            return get_member_role(request.user, obj) is not None
        return has_role(request.user, obj, WorkspaceMember.Role.ADMIN)
