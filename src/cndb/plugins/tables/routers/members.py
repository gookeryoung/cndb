"""表成员与所有权管理路由."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import AuditLog, DataTable, TableMember
from cndb.plugins.tables.schemas import MemberCreate, MemberOut, MemberUpdate, OwnerTransfer
from cndb.plugins.tables.services.core.access import check_workspace_permission, get_table_or_404
from cndb.plugins.workspaces.models import Role, WorkspaceMember, WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}", tags=["table-members"])


# ── 辅助函数 ─────────────────────────────────────────


def _require_table_admin(
    table: DataTable,
    current_user: User,
    db: Session,
) -> None:
    """校验当前用户是否为表所有者或工作区 ADMIN/OWNER.

    失败时抛 403.
    """
    if table.owner_id is not None and table.owner_id == current_user.id:
        return
    wm = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == table.workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
        .first()
    )
    if wm is None:
        raise HTTPException(status_code=403, detail="非工作区成员，无法操作表成员")
    if wm.role not in (WorkspaceRole.ADMIN, WorkspaceRole.OWNER):
        raise HTTPException(status_code=403, detail="仅表所有者或工作区 ADMIN/OWNER 可执行此操作")


def _assert_workspace_member(workspace_id: int, user_id: int, db: Session) -> None:
    """校验目标用户是否为工作区成员. 失败时抛 400."""
    wm = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        .first()
    )
    if wm is None:
        raise HTTPException(status_code=400, detail="目标用户不是该工作区成员")


_BUILTIN_ROLES = frozenset({"read", "write"})


def _validate_member_role(db: Session, role_code: str) -> None:
    """校验 TableMember.role 是否合法.

    合法值：内置 "read"/"write"，或管理员已定义的 Role.code.
    失败时抛 400.
    """
    if role_code in _BUILTIN_ROLES:
        return
    r = db.query(Role).filter(Role.code == role_code).first()
    if r is None:
        raise HTTPException(status_code=400, detail=f"角色 {role_code!r} 不存在，请联系管理员创建")


def _write_audit(
    db: Session,
    table_id: int,
    action: str,
    actor_id: int,
    detail: dict[str, Any],
) -> None:
    """写一条审计日志."""
    db.add(
        AuditLog(
            table_id=table_id,
            action=action,
            actor_id=actor_id,
            detail=detail,
        )
    )


def _member_out(db: Session, user_id: int, role: str) -> dict[str, Any]:
    """构造 MemberOut 响应 dict."""
    user = db.get(User, user_id)
    return {
        "user_id": user_id,
        "username": user.username if user else "",
        "nickname": user.nickname if user else "",
        "role": role,
    }


# ── 成员列表 ─────────────────────────────────────────


@router.get("/members", response_model=list[MemberOut])
def list_members(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, Any]]:
    """列出表的所有成员（含用户名）."""
    table = get_table_or_404(table_id, workspace_id, db)
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)

    rows = (
        db.query(TableMember, User.username, User.nickname)
        .join(User, User.id == TableMember.user_id)
        .filter(TableMember.table_id == table.id)
        .all()
    )
    result: list[dict[str, Any]] = []
    for tm, username, nickname in rows:
        result.append(
            {
                "user_id": tm.user_id,
                "username": username,
                "nickname": nickname or "",
                "role": tm.role,
            }
        )
    return result


# ── 添加成员 ─────────────────────────────────────────


@router.post("/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(
    workspace_id: int,
    table_id: int,
    payload: MemberCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """为表添加成员."""
    table = get_table_or_404(table_id, workspace_id, db)
    _require_table_admin(table, current_user, db)

    _validate_member_role(db, payload.role)
    _assert_workspace_member(workspace_id, payload.user_id, db)

    if table.owner_id == payload.user_id:
        raise HTTPException(status_code=400, detail="表所有者无需再添加为成员")

    existing = (
        db.query(TableMember).filter(TableMember.table_id == table.id, TableMember.user_id == payload.user_id).first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="该用户已是表成员")

    tm = TableMember(table_id=table.id, user_id=payload.user_id, role=payload.role)
    db.add(tm)
    _write_audit(
        db,
        table.id,
        "add_member",
        current_user.id,
        {"user_id": payload.user_id, "role": payload.role},
    )
    db.commit()
    db.refresh(tm)

    return _member_out(db, tm.user_id, tm.role)


# ── 变更成员角色 ──────────────────────────────────────


@router.patch("/members/{user_id}", response_model=MemberOut)
def update_member(
    workspace_id: int,
    table_id: int,
    user_id: int,
    payload: MemberUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """变更成员角色."""
    table = get_table_or_404(table_id, workspace_id, db)
    _require_table_admin(table, current_user, db)

    _validate_member_role(db, payload.role)

    tm = db.query(TableMember).filter(TableMember.table_id == table.id, TableMember.user_id == user_id).first()
    if tm is None:
        raise HTTPException(status_code=404, detail="该用户不是表成员")

    old_role = tm.role
    tm.role = payload.role
    _write_audit(
        db,
        table.id,
        "update_member",
        current_user.id,
        {"user_id": user_id, "old_role": old_role, "new_role": payload.role},
    )
    db.commit()
    db.refresh(tm)

    return _member_out(db, tm.user_id, tm.role)


# ── 移除成员 ─────────────────────────────────────────


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    workspace_id: int,
    table_id: int,
    user_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """移除表成员."""
    table = get_table_or_404(table_id, workspace_id, db)
    _require_table_admin(table, current_user, db)

    tm = db.query(TableMember).filter(TableMember.table_id == table.id, TableMember.user_id == user_id).first()
    if tm is None:
        raise HTTPException(status_code=404, detail="该用户不是表成员")

    _write_audit(
        db,
        table.id,
        "remove_member",
        current_user.id,
        {"user_id": user_id, "role": tm.role},
    )
    db.delete(tm)
    db.commit()


# ── 转让所有权 ───────────────────────────────────────


@router.post("/owner", response_model=MemberOut)
def transfer_owner(
    workspace_id: int,
    table_id: int,
    payload: OwnerTransfer,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """转让表所有权."""
    table = get_table_or_404(table_id, workspace_id, db)

    # 调用方必须是当前 owner 或工作区 ADMIN/OWNER
    is_owner = table.owner_id is not None and table.owner_id == current_user.id
    ws = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
        .first()
    )
    ws_role = ws.role if ws else None
    if not is_owner and ws_role not in (WorkspaceRole.ADMIN, WorkspaceRole.OWNER):
        raise HTTPException(status_code=403, detail="仅表所有者或工作区 ADMIN/OWNER 可转让所有权")

    # 目标必须是工作区成员
    _assert_workspace_member(workspace_id, payload.user_id, db)

    # 幂等：转让给自己直接返回
    if table.owner_id == payload.user_id:
        return _member_out(db, payload.user_id, "owner")

    old_owner_id = table.owner_id
    table.owner_id = payload.user_id

    # 新 owner 如果同时是表成员，移除其成员记录
    existing_member = (
        db.query(TableMember)
        .filter(
            TableMember.table_id == table.id,
            TableMember.user_id == payload.user_id,
        )
        .first()
    )
    if existing_member is not None:
        db.delete(existing_member)

    _write_audit(
        db,
        table.id,
        "transfer_owner",
        current_user.id,
        {"old_owner_id": old_owner_id, "new_owner_id": payload.user_id},
    )
    db.commit()
    db.refresh(table)

    owner_id = cast(int, table.owner_id)  # 上方已转移所有者，必非空
    return _member_out(db, owner_id, "owner")


__all__ = ["router"]
