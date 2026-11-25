"""团队域服务（ADR 0153 P1）：slug 生成、策略校验与团队门控.

只做「团队自身的」判定；工作区级判定仍在 ``workspaces/permissions.py``：
团队角色只决定管理面，从不派生数据面（D4 / I1）。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from cndb.core.errors import PermissionDeniedError
from cndb.plugins.workspaces.models import (
    POLICY_DEFAULT_ROLE_VALUES,
    TEAM_POLICY_DEFAULTS,
    TEAM_ROLE_RANK,
    Team,
    TeamMember,
    TeamRole,
)
from cndb.plugins.workspaces.modules import normalize_modules

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User

SLUG_MAX_LENGTH = 48
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify_team_name(name: str) -> str:
    """把团队名转成 ASCII slug（中文名等无法转换时回落 ``team``）."""
    base = _SLUG_STRIP.sub("-", name.strip().lower()).strip("-")
    return (base or "team")[:SLUG_MAX_LENGTH]


def unique_team_slug(db: Session, name: str, *, exclude_id: int | None = None) -> str:
    """生成团队内唯一的 slug（冲突时追加 ``-2`` / ``-3`` …）."""
    base = slugify_team_name(name)
    candidate = base
    suffix = 2
    while True:
        stmt = db.query(Team.id).filter(Team.slug == candidate)
        if exclude_id is not None:
            stmt = stmt.filter(Team.id != exclude_id)
        if stmt.first() is None:
            return candidate
        candidate = f"{base}-{suffix}"[:SLUG_MAX_LENGTH]
        suffix += 1


def normalize_team_policy(policy: dict[str, object] | None) -> dict[str, object]:
    """校验并归一团队策略（未知键丢弃，缺键补默认；非法值直接 400）.

    ``default_workspace_role`` 只允许 ``none`` / ``viewer`` / ``editor``；
    ``allowed_modules`` 非空时走 ``normalize_modules``（与工作区模块同一白名单）；
    ``default_storage_quota_bytes`` 必须是非负整数或 None。
    """
    from fastapi import HTTPException, status

    merged: dict[str, object] = {}
    raw = dict(policy or {})

    default_role = raw.get("default_workspace_role", TEAM_POLICY_DEFAULTS["default_workspace_role"])
    if not isinstance(default_role, str) or default_role not in POLICY_DEFAULT_ROLE_VALUES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="团队策略 default_workspace_role 只能是 none / viewer / editor",
        )
    merged["default_workspace_role"] = default_role

    allowed = raw.get("allowed_modules")
    if allowed is not None:
        allowed = normalize_modules(allowed)  # 空集 / 非法模块名 → 422
    merged["allowed_modules"] = allowed

    quota = raw.get("default_storage_quota_bytes")
    if quota is not None and (not isinstance(quota, int) or isinstance(quota, bool) or quota < 0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="团队策略 default_storage_quota_bytes 必须是非负整数",
        )
    merged["default_storage_quota_bytes"] = quota

    invite = raw.get("allow_member_invite", TEAM_POLICY_DEFAULTS["allow_member_invite"])
    if not isinstance(invite, bool):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="团队策略 allow_member_invite 必须是布尔值",
        )
    merged["allow_member_invite"] = invite
    return merged


def team_policy_for(team: Team | None) -> dict[str, object]:
    """团队策略（缺键按默认补齐）；供路由层判断 allowed_modules / 默认配额."""
    from cndb.plugins.workspaces.permissions import team_policy

    return team_policy(team)


def workspace_team_id(db: Session, workspace_id: int) -> int | None:
    """读取工作区所属团队 id（无团队返回 None）."""
    from cndb.plugins.workspaces.models import Workspace

    row = db.query(Workspace.team_id).filter(Workspace.id == workspace_id).first()
    return row[0] if row else None


def in_same_team(db: Session, workspace_id: int, other_workspace_id: int) -> bool:
    """两个工作区是否属于同一团队（任一未挂团队 → False，ADR 0153 D3）."""
    if not workspace_id or not other_workspace_id:
        return False
    team_id = workspace_team_id(db, workspace_id)
    if team_id is None:
        return False
    return workspace_team_id(db, other_workspace_id) == team_id


def get_team_role(db: Session, team: Team, user: User) -> TeamRole | None:
    """读取用户在团队内角色（非成员 None）."""
    member = db.query(TeamMember).filter(TeamMember.team_id == team.id, TeamMember.user_id == user.id).first()
    return member.role if member else None


def require_team_member(db: Session, team: Team, user: User) -> TeamRole:
    """要求团队成员身份；非成员统一 404（不泄露团队存在性，I6 同款口径）."""
    from fastapi import HTTPException

    role = get_team_role(db, team, user)
    if role is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    return role


def require_team_role(db: Session, team: Team, user: User, minimum: TeamRole, *, requirement: str = "") -> TeamRole:
    """要求团队角色达到最低档；不足 403（中文文案与工作区同级口径）."""
    role = require_team_member(db, team, user)
    if TEAM_ROLE_RANK[role] < TEAM_ROLE_RANK[minimum]:
        from cndb.plugins.workspaces.models import TEAM_ROLE_LABELS

        label = TEAM_ROLE_LABELS.get(role.value, role.value)
        detail = f"当前用户在此团队的角色为【{label}】，团队权限不足"
        if requirement:
            detail = f"{detail}（{requirement}）"
        raise PermissionDeniedError(detail)
    return role


def ensure_modules_allowed(policy: dict[str, object], modules: list[str]) -> None:
    """校验新建 / 迁入工作区的模块集合是否被团队策略允许（越界 400）."""
    from fastapi import HTTPException, status

    allowed = policy.get("allowed_modules")
    if not isinstance(allowed, list):
        return
    extra = [m for m in modules if m not in allowed]
    if extra:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"团队策略不允许启用这些模块：{'、'.join(extra)}",
        )


__all__ = [
    "SLUG_MAX_LENGTH",
    "ensure_modules_allowed",
    "get_team_role",
    "in_same_team",
    "normalize_team_policy",
    "require_team_member",
    "require_team_role",
    "slugify_team_name",
    "team_policy_for",
    "unique_team_slug",
    "workspace_team_id",
]
