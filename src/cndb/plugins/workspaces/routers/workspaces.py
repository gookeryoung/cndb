"""workspaces 插件路由：CRUD + 成员管理 + pin + candidates."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role, has_role
from cndb.plugins.workspaces.schemas import (
    MemberAddRequest,
    MemberUpdateRequest,
    MemberUserBrief,
    PinRequest,
    PinToggleResponse,
    WorkspaceCreate,
    WorkspaceMemberResponse,
    WorkspaceResponse,
    WorkspaceUpdate,
    WorkspaceWithPinnedResponse,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# ── 公共依赖：解析工作区并校验成员身份 ─────────────────


def _get_workspace_or_404(workspace_id: int, db: Session) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return ws


def _require_member(workspace: Workspace, user: User, db: Session) -> None:
    if get_member_role(user, workspace, db) is None:
        raise HTTPException(status_code=404, detail="工作区不存在")


def _require_admin(workspace: Workspace, user: User, db: Session) -> None:
    if not has_role(user, workspace, WorkspaceRole.ADMIN, db):
        raise HTTPException(status_code=403, detail="需要管理员权限")


# ── 工作区 CRUD ──────────────────────────────────────


@router.get("", response_model=list[WorkspaceWithPinnedResponse])
def list_workspaces(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkspaceWithPinnedResponse]:
    """列出当前用户所属的工作区，钉住的置顶."""
    from sqlalchemy import case, select

    stmt = (
        select(
            Workspace,
            case(
                (WorkspaceMember.pinned.is_(True), True),
                else_=False,
            ).label("pinned"),
        )
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == current_user.id)
        .order_by(case((WorkspaceMember.pinned.is_(True), 0), else_=1), Workspace.id)
    )
    rows = db.execute(stmt).all()
    result: list[WorkspaceWithPinnedResponse] = []
    for ws, pinned in rows:
        d = {c.name: getattr(ws, c.name) for c in ws.__table__.columns}
        d["pinned"] = bool(pinned)
        result.append(WorkspaceWithPinnedResponse.model_validate(d))
    return result


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Workspace:
    """创建工作区并把创建者登记为 OWNER."""
    ws = Workspace(name=payload.name, description=payload.description, created_by_id=current_user.id)
    db.add(ws)
    db.flush()  # 拿到 ws.id
    member = WorkspaceMember(workspace_id=ws.id, user_id=current_user.id, role=WorkspaceRole.OWNER)
    db.add(member)
    db.commit()
    db.refresh(ws)
    return ws


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Workspace:
    """获取单个工作区（需是成员）."""
    ws = _get_workspace_or_404(workspace_id, db)
    _require_member(ws, current_user, db)
    return ws


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Workspace:
    """更新工作区（需 ADMIN+ 角色）."""
    ws = _get_workspace_or_404(workspace_id, db)
    _require_admin(ws, current_user, db)
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(ws, key, value)
    db.commit()
    db.refresh(ws)
    return ws


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除工作区（仅 OWNER 可执行）."""
    ws = _get_workspace_or_404(workspace_id, db)
    role = get_member_role(current_user, ws, db)
    if role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail="仅所有者可删除工作区")
    db.delete(ws)
    db.commit()


# ── 成员管理 ──────────────────────────────────────────


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
def list_members(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkspaceMember]:
    """列出当前工作区全部成员（需是成员）."""
    ws = _get_workspace_or_404(workspace_id, db)
    _require_member(ws, current_user, db)
    return (
        db.query(WorkspaceMember)
        .options(selectinload(WorkspaceMember.user))
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .all()
    )


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    workspace_id: int,
    payload: MemberAddRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceMember:
    """添加成员（需 ADMIN+，不允许添加为 OWNER）."""
    ws = _get_workspace_or_404(workspace_id, db)
    _require_admin(ws, current_user, db)
    if payload.role == WorkspaceRole.OWNER:
        raise HTTPException(status_code=400, detail="不能直接添加所有者")
    user = db.query(User).filter(User.username == payload.username, User.is_active.is_(True)).first()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    existing = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user.id)
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=400, detail="用户已是成员")
    member = WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role=payload.role)
    db.add(member)
    db.commit()
    db.refresh(member)
    # 预加载 user 关系供 response 序列化
    _ = member.user
    return member


@router.get("/{workspace_id}/members/candidates")
def list_member_candidates(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    search: str = Query("", description="按用户名/昵称模糊过滤"),
) -> dict[str, list[MemberUserBrief]]:
    """可添加为成员的候选用户列表（ADMIN+ 可见，排除已是成员的用户）."""
    ws = _get_workspace_or_404(workspace_id, db)
    _require_admin(ws, current_user, db)
    member_ids = [
        mid for (mid,) in db.query(WorkspaceMember.user_id).filter(WorkspaceMember.workspace_id == workspace_id).all()
    ]
    query = db.query(User).filter(User.is_active.is_(True), User.id.notin_(member_ids))
    if search.strip():
        keyword = f"%{search.strip()}%"
        query = query.filter((User.username.ilike(keyword)) | (User.nickname.ilike(keyword)))
    users = query.order_by(User.username).all()
    return {"results": [MemberUserBrief.model_validate(u) for u in users]}


@router.patch("/{workspace_id}/members/{member_id}", response_model=WorkspaceMemberResponse)
def update_member_role(
    workspace_id: int,
    member_id: int,
    payload: MemberUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceMember:
    """修改成员角色（需 ADMIN+；保护最后一个 OWNER 不可降级；OWNER 操作 OWNER 需 OWNER 自己）."""
    ws = _get_workspace_or_404(workspace_id, db)
    requester_role = get_member_role(current_user, ws, db)
    if requester_role not in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.id == member_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")
    if member.role == WorkspaceRole.OWNER and requester_role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail="仅所有者可操作所有者")
    # 保护：最后一个 OWNER 不可降级
    if member.role == WorkspaceRole.OWNER and payload.role != WorkspaceRole.OWNER:
        owner_count = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == WorkspaceRole.OWNER,
            )
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="工作区至少保留一名所有者")
    member.role = payload.role
    db.commit()
    db.refresh(member)
    _ = member.user
    return member


@router.delete("/{workspace_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    workspace_id: int,
    member_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """移除成员（需 ADMIN+；保护最后一个 OWNER 不可移除）."""
    ws = _get_workspace_or_404(workspace_id, db)
    requester_role = get_member_role(current_user, ws, db)
    if requester_role not in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.id == member_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")
    if member.role == WorkspaceRole.OWNER and requester_role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail="仅所有者可操作所有者")
    if member.role == WorkspaceRole.OWNER:
        owner_count = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == WorkspaceRole.OWNER,
            )
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="工作区至少保留一名所有者")
    db.delete(member)
    db.commit()


# ── pin 切换 ──────────────────────────────────────────


@router.post("/pin", response_model=PinToggleResponse)
def toggle_pin(
    payload: PinRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PinToggleResponse:
    """切换当前用户对工作区的钉住状态."""
    ws = _get_workspace_or_404(payload.workspace_id, db)
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == current_user.id)
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    member.pinned = not member.pinned
    db.commit()
    db.refresh(member)
    return PinToggleResponse(pinned=member.pinned)


__all__ = ["router"]
