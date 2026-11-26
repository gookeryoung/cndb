"""团队路由（ADR 0153 P1）：团队 CRUD + 成员 + 团队内工作区列表.

门控口径：
- 读团队 / 成员 / 工作区列表：团队成员（非成员统一 404，不泄露存在性）；
- 改团队设置 / 策略 / 成员：``team_owner``（成员增删改与转让：owner；成员列表：成员）；
- 删团队：``team_owner``，只解绑工作区（``team_id`` 置空）不删业务数据（D9 / I5）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import PermissionDeniedError
from cndb.core.events import record_event
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import (
    TEAM_POLICY_DEFAULTS,
    TEAM_ROLE_RANK,
    Team,
    TeamMember,
    TeamRole,
    Workspace,
    WorkspaceMember,
)
from cndb.plugins.workspaces.schemas import (
    TeamCreate,
    TeamMemberAddRequest,
    TeamMemberResponse,
    TeamMemberUpdateRequest,
    TeamResponse,
    TeamUpdate,
    TeamWorkspaceItem,
)
from cndb.plugins.workspaces.services.teams import (
    get_team_role,
    normalize_team_policy,
    require_team_member,
    require_team_role,
    unique_team_slug,
)

router = APIRouter(prefix="/teams", tags=["teams"])

_TEAM_ROLE_VALUES: tuple[str, ...] = (TeamRole.OWNER.value, TeamRole.ADMIN.value, TeamRole.MEMBER.value)


def _get_team_or_404(team_id: int, db: Session) -> Team:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    return team


def _invalidate_team_caches(workspace_ids: list[int] | None = None) -> int:
    """失效工作区列表缓存（团队变更会改变 /capabilities 与管理面结果）.

    与 ``routers/workspaces.invalidate_workspace_list_cache`` 同源，此处直接清缓存，
    避免 teams → workspaces 的循环导入。
    """
    from cndb.core.cache import cache_key, list_cache

    cleared = list_cache.clear(cache_key("ws-list"))
    for wid in workspace_ids or []:
        cleared += list_cache.clear(cache_key("workspace-stats", wid))
    return cleared


def _event(
    db: Session,
    action: str,
    *,
    summary: str,
    team: Team,
    user: User,
    target_type: str = "team",
    target_id: int | None = None,
    detail: dict[str, Any] | None = None,
    workspace_id: int | None = None,
) -> None:
    """记录团队级事件（``core_event`` 的 ``team.*``，ADR 0153 P2；尽力而为不阻断业务）."""
    record_event(
        db,
        action,
        summary=summary,
        target_type=target_type,
        target_id=target_id if target_id is not None else team.id,
        workspace_id=workspace_id,
        actor_id=user.id,
        actor_name=user.nickname or user.username,
        detail=detail or {},
        commit=False,
    )


def _team_payload(db: Session, team: Team, user: User) -> dict[str, Any]:
    """组装团队响应载荷（含当前用户角色与统计）."""
    workspace_count = db.query(func.count(Workspace.id)).filter(Workspace.team_id == team.id).scalar() or 0
    member_count = db.query(func.count(TeamMember.id)).filter(TeamMember.team_id == team.id).scalar() or 0
    role = get_team_role(db, team, user)
    return {
        "id": team.id,
        "name": team.name,
        "slug": team.slug,
        "description": team.description,
        "policy": {**TEAM_POLICY_DEFAULTS, **(team.policy or {})},
        "created_by_id": team.created_by_id,
        "created_at": team.created_at,
        "updated_at": team.updated_at,
        "current_user_role": role.value if role else None,
        "workspace_count": int(workspace_count),
        "member_count": int(member_count),
    }


# ── 团队 CRUD ────────────────────────────────────────


@router.get("", response_model=list[TeamResponse])
def list_teams(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[TeamResponse]:
    """列出当前用户所属团队（平铺，无树：C1）."""
    rows = (
        db.query(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .filter(TeamMember.user_id == current_user.id)
        .order_by(Team.id)
        .all()
    )
    return [TeamResponse.model_validate(_team_payload(db, team, current_user)) for team in rows]


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
def create_team(
    payload: TeamCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TeamResponse:
    """创建团队：任意登录用户可建，创建者记为 ``team_owner``."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="团队名称不能为空")
    team = Team(
        name=name,
        slug=(payload.slug or "").strip() or unique_team_slug(db, name),
        description=payload.description or "",
        policy=dict(TEAM_POLICY_DEFAULTS),
        created_by_id=current_user.id,
    )
    if db.query(Team.id).filter(Team.slug == team.slug).first() is not None:
        raise HTTPException(status_code=400, detail="团队标识已被占用")
    db.add(team)
    db.flush()
    db.add(TeamMember(team_id=team.id, user_id=current_user.id, role=TeamRole.OWNER))
    _event(db, "team.create", summary=f"创建团队「{team.name}」", team=team, user=current_user)
    db.commit()
    db.refresh(team)
    _invalidate_team_caches()
    return TeamResponse.model_validate(_team_payload(db, team, current_user))


@router.get("/{team_id}", response_model=TeamResponse)
def get_team(
    team_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TeamResponse:
    """团队详情（团队成员可读）."""
    team = _get_team_or_404(team_id, db)
    require_team_member(db, team, current_user)
    return TeamResponse.model_validate(_team_payload(db, team, current_user))


@router.patch("/{team_id}", response_model=TeamResponse)
def update_team(
    team_id: int,
    payload: TeamUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TeamResponse:
    """更新团队名称 / 描述 / 策略（仅 ``team_owner``）."""
    team = _get_team_or_404(team_id, db)
    require_team_role(db, team, current_user, TeamRole.OWNER, requirement="仅团队所有者可修改团队设置")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="团队名称不能为空")
        team.name = name
    if payload.description is not None:
        team.description = payload.description
    if payload.policy is not None:
        team.policy = normalize_team_policy(payload.policy.model_dump())
    _event(db, "team.update", summary=f"更新团队「{team.name}」设置", team=team, user=current_user)
    db.commit()
    db.refresh(team)
    _invalidate_team_caches()
    return TeamResponse.model_validate(_team_payload(db, team, current_user))


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(
    team_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除团队（仅 ``team_owner``）：工作区 ``team_id`` 置空并降级为独立工作区（I5）."""
    team = _get_team_or_404(team_id, db)
    require_team_role(db, team, current_user, TeamRole.OWNER, requirement="仅团队所有者可删除团队")
    workspace_ids = [row[0] for row in db.query(Workspace.id).filter(Workspace.team_id == team.id).all()]
    db.query(Workspace).filter(Workspace.team_id == team.id).update(
        {Workspace.team_id: None}, synchronize_session=False
    )
    _event(
        db,
        "team.delete",
        summary=f"删除团队「{team.name}」，{len(workspace_ids)} 个工作区转为独立工作区",
        team=team,
        user=current_user,
        detail={"workspace_ids": workspace_ids},
    )
    db.delete(team)
    db.commit()
    _invalidate_team_caches(workspace_ids)


# ── 团队成员 ─────────────────────────────────────────


@router.get("/{team_id}/members", response_model=list[TeamMemberResponse])
def list_team_members(
    team_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[TeamMemberResponse]:
    """团队成员列表（团队成员可读）."""
    team = _get_team_or_404(team_id, db)
    require_team_member(db, team, current_user)
    rows = (
        db.query(TeamMember)
        .join(User, User.id == TeamMember.user_id)
        .options(selectinload(TeamMember.user))
        .filter(TeamMember.team_id == team.id)
        .order_by(TeamMember.id)
        .all()
    )
    return [TeamMemberResponse.model_validate(row) for row in rows]


@router.post("/{team_id}/members", response_model=TeamMemberResponse, status_code=status.HTTP_201_CREATED)
def add_team_member(
    team_id: int,
    payload: TeamMemberAddRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TeamMemberResponse:
    """添加团队成员（``team_owner`` / ``team_admin``；不得直接添加为 owner）."""
    team = _get_team_or_404(team_id, db)
    require_team_role(db, team, current_user, TeamRole.ADMIN, requirement="仅团队所有者或管理员可添加成员")
    if payload.role not in _TEAM_ROLE_VALUES or payload.role == TeamRole.OWNER.value:
        raise HTTPException(status_code=400, detail="团队成员角色只能是 admin / member")
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if db.query(TeamMember).filter(TeamMember.team_id == team.id, TeamMember.user_id == user.id).first() is not None:
        raise HTTPException(status_code=400, detail="该用户已是团队成员")
    member = TeamMember(team_id=team.id, user_id=user.id, role=TeamRole(payload.role))
    db.add(member)
    _event(
        db,
        "team.member_add",
        summary=f"向团队「{team.name}」添加成员 {user.username}",
        team=team,
        user=current_user,
        target_type="user",
        target_id=user.id,
        detail={"role": payload.role},
    )
    db.commit()
    db.refresh(member)
    _ = member.user
    _invalidate_team_caches()
    return TeamMemberResponse.model_validate(member)


@router.patch("/{team_id}/members/{member_id}", response_model=TeamMemberResponse)
def update_team_member(
    team_id: int,
    member_id: int,
    payload: TeamMemberUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TeamMemberResponse:
    """修改团队成员角色（仅 ``team_owner``；保护最后一个 ``team_owner``；不得操作更高角色）."""
    team = _get_team_or_404(team_id, db)
    actor_role = require_team_role(db, team, current_user, TeamRole.OWNER, requirement="仅团队所有者可修改成员角色")
    if payload.role not in _TEAM_ROLE_VALUES:
        raise HTTPException(status_code=400, detail="团队成员角色只能是 owner / admin / member")
    member = db.query(TeamMember).filter(TeamMember.id == member_id, TeamMember.team_id == team.id).first()
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")
    # ADR 0161 D5：不得操作角色高于自己的成员（下级不改上级）
    if TEAM_ROLE_RANK[member.role] > TEAM_ROLE_RANK[actor_role]:
        raise PermissionDeniedError("不能修改角色高于自己的成员")
    new_role = TeamRole(payload.role)
    if member.role is TeamRole.OWNER and new_role is not TeamRole.OWNER:
        owner_count = (
            db.query(func.count(TeamMember.id))
            .filter(TeamMember.team_id == team.id, TeamMember.role == TeamRole.OWNER)
            .scalar()
            or 0
        )
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="团队至少保留一名所有者")
    previous = member.role.value
    member.role = new_role
    _event(
        db,
        "team.member_role",
        summary=f"团队「{team.name}」成员 {member.user_id} 角色 {previous} → {new_role.value}",
        team=team,
        user=current_user,
        target_type="user",
        target_id=member.user_id,
        detail={"before": previous, "after": new_role.value},
    )
    db.commit()
    db.refresh(member)
    _ = member.user
    _invalidate_team_caches()
    return TeamMemberResponse.model_validate(member)


@router.delete("/{team_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_team_member(
    team_id: int,
    member_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """移除团队成员（``team_owner`` / ``team_admin``；保护最后一个 ``team_owner``）.

    移除团队身份**不影响**其工作区成员身份（两套授权彼此独立，D4）。
    """
    team = _get_team_or_404(team_id, db)
    actor_role = require_team_role(db, team, current_user, TeamRole.ADMIN, requirement="仅团队所有者或管理员可移除成员")
    member = db.query(TeamMember).filter(TeamMember.id == member_id, TeamMember.team_id == team.id).first()
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")
    # ADR 0161 D5：不得移除角色高于自己的成员（团队管理员不可移除 team_owner）
    if TEAM_ROLE_RANK[member.role] > TEAM_ROLE_RANK[actor_role]:
        raise PermissionDeniedError("不能移除角色高于自己的成员")
    if member.role is TeamRole.OWNER:
        owner_count = (
            db.query(func.count(TeamMember.id))
            .filter(TeamMember.team_id == team.id, TeamMember.role == TeamRole.OWNER)
            .scalar()
            or 0
        )
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="团队至少保留一名所有者")
    _event(
        db,
        "team.member_remove",
        summary=f"从团队「{team.name}」移除成员 {member.user_id}",
        team=team,
        user=current_user,
        target_type="user",
        target_id=member.user_id,
    )
    db.delete(member)
    db.commit()
    _invalidate_team_caches()


# ── 团队内工作区（平铺列表，无树） ───────────────────


@router.get("/{team_id}/workspaces", response_model=list[TeamWorkspaceItem])
def list_team_workspaces(
    team_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[TeamWorkspaceItem]:
    """团队内工作区平铺列表（团队成员可读；C1：不做树形层级）."""
    team = _get_team_or_404(team_id, db)
    require_team_member(db, team, current_user)
    rows = db.query(Workspace).filter(Workspace.team_id == team.id).order_by(Workspace.id).all()
    counts: dict[int, int] = {
        int(row[0]): int(row[1])
        for row in (
            db.query(WorkspaceMember.workspace_id, func.count(WorkspaceMember.id))
            .filter(WorkspaceMember.workspace_id.in_([ws.id for ws in rows] or [0]))
            .group_by(WorkspaceMember.workspace_id)
            .all()
        )
    }
    member_workspace_ids = {
        int(row[0])
        for row in db.query(WorkspaceMember.workspace_id)
        .filter(
            WorkspaceMember.workspace_id.in_([ws.id for ws in rows] or [0]),
            WorkspaceMember.user_id == current_user.id,
        )
        .all()
    }
    return [
        TeamWorkspaceItem.model_validate(
            {
                "id": ws.id,
                "name": ws.name,
                "description": ws.description,
                "visibility": ws.visibility,
                "modules": ws.modules,
                "member_count": int(counts.get(ws.id, 0)),
                "is_member": ws.id in member_workspace_ids,
                "updated_at": ws.updated_at,
            }
        )
        for ws in rows
    ]


@router.get("/{team_id}/search")
def search_team(
    team_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: str = Query(min_length=1, max_length=200, description="关键词"),
    limit: int = Query(default=10, ge=1, le=30, description="各组命中上限"),
) -> dict[str, Any]:
    """团队内跨工作区检索（ADR 0153 P2）：只扫该团队下用户**可读**的工作区.

    团队管理员默认无数据面（H49），因此不会出现在结果里。
    """
    from cndb.plugins.workspaces.services.search import search_team_workspaces

    team = _get_team_or_404(team_id, db)
    require_team_member(db, team, current_user)
    keyword = q.strip()
    if not keyword:
        return {"query": "", "documents": [], "tables": [], "rows": []}
    return search_team_workspaces(db, current_user, team.id, keyword, limit=limit)


__all__ = ["router"]
