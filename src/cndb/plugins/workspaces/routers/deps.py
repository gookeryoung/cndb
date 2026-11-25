"""workspaces 路由共用依赖：解析工作区并校验成员 / 能力位身份.

ADR 0153 P0：所有工作区级门控统一走 ``permissions.resolve_capabilities``，
本模块只保留「HTTP 语义」的薄封装（成员缺失 404、能力不足 403）。
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from cndb.core.errors import PermissionDeniedError
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Team, Workspace
from cndb.plugins.workspaces.permissions import (
    Capabilities,
    WorkspaceCapability,
    require_capability,
    resolve_capabilities,
)


def _require_team_for_workspace(
    db: Session,
    team_id: int | None,
    user: User,
    *,
    requirement: str = "",
) -> Team | None:
    """要求调用者是目标团队成员（工作区挂载团队时使用）；非成员 403，团队不存在 404."""
    if team_id is None:
        return None
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    from cndb.plugins.workspaces.services.teams import get_team_role

    if get_team_role(db, team, user) is None:
        detail = "你不是该团队成员，无权把工作区挂到该团队"
        if requirement:
            detail = f"{detail}（{requirement}）"
        raise PermissionDeniedError(detail)
    return team


def _get_workspace_or_404(workspace_id: int, db: Session) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")  # pragma: no cover - 由 _get_workspace_or_404 前置
    return ws


def _require_member(workspace: Workspace, user: User, db: Session) -> Capabilities:
    """要求工作区成员身份；非成员统一 404（不泄露工作区存在性，ADR 0153 I6）."""
    caps = resolve_capabilities(user, workspace, db)
    if not caps.allows(WorkspaceCapability.READ):
        raise HTTPException(status_code=404, detail="工作区不存在")
    return caps


def _require_owner(
    workspace: Workspace,
    user: User,
    db: Session,
    *,
    requirement: str = "仅所有者可执行此操作",
) -> Capabilities:
    """要求管理面能力位（P0 等价「工作区所有者」）；失败走 ADR 0047 文案."""
    return require_capability(
        WorkspaceCapability.EDIT_SETTINGS,
        db,
        workspace,
        user,
        requirement=requirement,
    )


def _require_workspace_owner(
    workspace: Workspace,
    user: User,
    db: Session,
    *,
    requirement: str = "仅所有者可执行此操作",
) -> Capabilities:
    """要求工作区所有者本人（团队管理员不可代替）：删除 / 覆盖恢复属不可逆操作（ADR 0153 D9）."""
    return require_capability(
        WorkspaceCapability.DELETE_WORKSPACE,
        db,
        workspace,
        user,
        requirement=requirement,
    )


__all__ = [
    "_get_workspace_or_404",
    "_require_member",
    "_require_owner",
    "_require_team_for_workspace",
    "_require_workspace_owner",
]
