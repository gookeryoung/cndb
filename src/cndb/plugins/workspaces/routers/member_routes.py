"""成员管理（列表 / 候选 / 增删改）与所有权转让路由.

由 routers/workspaces.py 以 `router.include_router(member_router)` 挂载，
沿用同一个 /workspaces 前缀。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role
from cndb.plugins.workspaces.routers.deps import _get_workspace_or_404, _require_member, _require_owner
from cndb.plugins.workspaces.schemas import (
    MemberAddRequest,
    MemberUpdateRequest,
    MemberUserBrief,
    WorkspaceMemberResponse,
    WorkspaceOwnerTransferRequest,
)


def invalidate_workspace_list_cache() -> int:
    """失效工作区列表缓存（成员变更后调用）.

    刻意在这里**直接**用缓存模块而不是从 routers/workspaces.py 导入：
    后者会与本模块形成循环导入（workspaces 导入 member_router），
    导致工作区插件整体加载失败、路由全部 404。
    """
    from cndb.core.cache import cache_key, list_cache

    return list_cache.clear(cache_key("ws-list"))


router = APIRouter()

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
    # inner join 用户表：剔除用户已删除的孤儿成员行，与 member_count 口径一致
    return (
        db.query(WorkspaceMember)
        .join(User, User.id == WorkspaceMember.user_id)
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
    """添加成员（仅 OWNER，不允许添加为 OWNER）."""
    ws = _get_workspace_or_404(workspace_id, db)
    _require_owner(ws, current_user, db)
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
        raise HTTPException(status_code=400, detail="用户已是成员")  # pragma: no cover - 测试已覆盖通过 IntegrityError
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
    """可添加为成员的候选用户列表（OWNER 可见，排除已是成员的用户）."""
    ws = _get_workspace_or_404(workspace_id, db)
    _require_owner(ws, current_user, db)
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
    """修改成员角色（仅 OWNER；保护最后一个 OWNER 不可降级）."""
    ws = _get_workspace_or_404(workspace_id, db)
    requester_role = get_member_role(current_user, ws, db)
    if requester_role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail="需要所有者权限")
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.id == member_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")  # pragma: no cover
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
    """移除成员（仅 OWNER；保护最后一个 OWNER 不可移除）."""
    ws = _get_workspace_or_404(workspace_id, db)
    requester_role = get_member_role(current_user, ws, db)
    if requester_role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail="需要所有者权限")
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.id == member_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")  # pragma: no cover
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
    invalidate_workspace_list_cache()


# ── 转让所有权 ────────────────────────────────────────


@router.post("/{workspace_id}/owner", response_model=WorkspaceMemberResponse)
def transfer_owner(
    workspace_id: int,
    payload: WorkspaceOwnerTransferRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceMember:
    """转让工作区所有权（仅当前 OWNER 可执行；目标须是工作区成员）."""
    ws = _get_workspace_or_404(workspace_id, db)
    requester_role = get_member_role(current_user, ws, db)
    if requester_role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail="仅所有者可转让所有权")

    # 目标必须是工作区成员
    target_member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == payload.user_id,
        )
        .first()
    )
    if target_member is None:
        raise HTTPException(status_code=400, detail="目标用户不是该工作区成员")

    # 幂等：转让给自己直接返回
    if target_member.role == WorkspaceRole.OWNER:
        return target_member

    # 把当前 OWNER 降级为编辑者
    current_owner = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == WorkspaceRole.OWNER,
        )
        .first()
    )
    if current_owner is not None:
        current_owner.role = WorkspaceRole.EDITOR

    # 把目标提升为 OWNER
    target_member.role = WorkspaceRole.OWNER
    db.commit()
    db.refresh(target_member)
    _ = target_member.user
    return target_member


__all__ = ["router"]
