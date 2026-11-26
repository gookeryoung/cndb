"""团队数据授权路由（ADR 0154 B′ / P3.1）.

源工作区所有者把「某团队 = viewer」授出去：

- 只产 `data_role=viewer`，**不产管理面**，也不改行级 / 字段规则（D11 / H57）；
- 到期惰性失效（无需清扫），也可随时撤销；
- 与团队角色互相独立：团队角色不放行数据（H49），放行数据的是本授权行。
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.events import record_event
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import (
    LINK_DEFAULT_TTL_DAYS,
    LINK_MAX_TTL_DAYS,
    Team,
    WorkspaceTeamAccess,
)
from cndb.plugins.workspaces.permissions import WorkspaceCapability, require_capability
from cndb.plugins.workspaces.routers.deps import _get_workspace_or_404
from cndb.plugins.workspaces.schemas import TeamAccessCreate, TeamAccessResponse
from cndb.plugins.workspaces.services.links import grant_team_access, team_access_payload

router = APIRouter(prefix="/workspaces", tags=["workspace-team-access"])


def _invalidate(workspace_id: int) -> None:
    from cndb.core.cache import cache_key, list_cache, search_cache

    list_cache.clear(cache_key("ws-list"))
    list_cache.clear(cache_key("workspace-stats", workspace_id))
    search_cache.clear(cache_key("global-search"))
    search_cache.clear(cache_key("team-search"))


def _require_owner(db: Session, workspace_id: int, user: User, requirement: str):
    ws = _get_workspace_or_404(workspace_id, db)
    require_capability(WorkspaceCapability.MANAGE_ACCESS, db, ws, user, requirement=requirement)
    return ws


@router.get("/{workspace_id}/team-access", response_model=list[TeamAccessResponse])
def list_team_access(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[TeamAccessResponse]:
    """列出本工作区的团队数据授权（仅所有者，属于管理面信息）."""
    _require_owner(db, workspace_id, current_user, "仅所有者可查看团队授权")
    rows = (
        db.query(WorkspaceTeamAccess)
        .filter(WorkspaceTeamAccess.workspace_id == workspace_id)
        .order_by(WorkspaceTeamAccess.id)
        .all()
    )
    return [TeamAccessResponse.model_validate(team_access_payload(db, row)) for row in rows]


@router.post(
    "/{workspace_id}/team-access",
    response_model=TeamAccessResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_team_access(
    workspace_id: int,
    payload: TeamAccessCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TeamAccessResponse:
    """授「团队 = 只读 / 可编辑」（仅所有者；同团队重复授权覆盖有效期与角色，不新增行）."""
    ws = _require_owner(db, workspace_id, current_user, "仅所有者可授团队授权")
    team = db.get(Team, payload.team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    if ws.team_id is not None and ws.team_id == team.id:
        raise HTTPException(status_code=400, detail="不能把工作区授给它自己所属的团队（成员本就可见）")

    ttl_days = payload.ttl_days or LINK_DEFAULT_TTL_DAYS
    if not 1 <= ttl_days <= LINK_MAX_TTL_DAYS:
        raise HTTPException(status_code=400, detail=f"有效期需在 1–{LINK_MAX_TTL_DAYS} 天之间")

    role_label = "编辑" if payload.role == "editor" else "只读"
    row = grant_team_access(
        db,
        workspace_id=ws.id,
        team_id=team.id,
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=ttl_days),
        granted_by_id=current_user.id,
        note=payload.note or "",
        role=payload.role,
    )
    db.flush()
    record_event(
        db,
        "workspace.team_access_grant",
        summary=f"授权团队「{team.name}」{role_label}访问工作区「{ws.name}」（{ttl_days} 天）",
        target_type="workspace",
        target_id=ws.id,
        workspace_id=ws.id,
        actor_id=current_user.id,
        actor_name=current_user.nickname or current_user.username,
        detail={"team_id": team.id, "ttl_days": ttl_days, "role": payload.role},
        commit=False,
    )
    db.commit()
    db.refresh(row)
    _invalidate(ws.id)
    return TeamAccessResponse.model_validate(team_access_payload(db, row))


@router.delete("/{workspace_id}/team-access/{access_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team_access(
    workspace_id: int,
    access_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """撤销团队授权（仅所有者）."""
    ws = _require_owner(db, workspace_id, current_user, "仅所有者可撤销团队授权")
    row = db.get(WorkspaceTeamAccess, access_id)
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(status_code=404, detail="授权不存在")
    team = db.get(Team, row.team_id)
    role_label = "编辑" if row.role == "editor" else "只读"
    record_event(
        db,
        "workspace.team_access_revoke",
        summary=f"撤销团队「{team.name if team else row.team_id}」对工作区「{ws.name}」的{role_label}授权",
        target_type="workspace",
        target_id=ws.id,
        workspace_id=ws.id,
        actor_id=current_user.id,
        actor_name=current_user.nickname or current_user.username,
        detail={"team_id": row.team_id},
        commit=False,
    )
    db.delete(row)
    db.commit()
    _invalidate(ws.id)


__all__: list[str] = ["router"]
