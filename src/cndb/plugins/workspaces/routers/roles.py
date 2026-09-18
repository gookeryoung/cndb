"""数据角色（Role）管理路由 —— 仅管理员维护.

职责：
- 管理员（system_admin）创建 / 查看 / 更新 / 删除全局数据角色
- 表拥有者从现有角色中选择分配给其表的成员（分配逻辑走 members.py，不在此处）
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User, UserRole
from cndb.plugins.workspaces.models import ACTION_KEYS, Role
from cndb.plugins.workspaces.schemas import RoleCreate, RoleResponse, RoleUpdate

router = APIRouter(prefix="/roles", tags=["roles"])


# ── 权限检查 ──────────────────────────────────────────


def _require_system_admin(current_user: User) -> None:
    """校验当前用户是否为 system_admin.

    失败时抛 403.
    """
    if current_user.role != UserRole.SYSTEM_ADMIN.value:
        raise HTTPException(status_code=403, detail="仅系统管理员可维护角色")


# ── 辅助：校验 code 合法性 ────────────────────────────


def _validate_code(code: str) -> None:
    """校验角色 code 是否仅含小写字母、数字、下划线，长度 1-64."""
    import re

    if not code:
        raise HTTPException(status_code=400, detail="code 不能为空")
    if len(code) > 64:
        raise HTTPException(status_code=400, detail="code 长度不能超过 64")
    if not re.fullmatch(r"[a-z0-9_]+", code):
        raise HTTPException(status_code=400, detail="code 仅允许小写字母、数字、下划线")


def _validate_permissions(permissions: dict[str, bool] | None) -> None:
    """校验 permissions dict 仅包含合法 action_key."""
    if not permissions:
        return
    unknown = [k for k in permissions if k not in ACTION_KEYS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知权限项: {unknown}")
    non_bool = [k for k, v in permissions.items() if not isinstance(v, bool)]
    if non_bool:
        raise HTTPException(status_code=400, detail=f"权限值必须为 bool: {non_bool}")


# ── 内置角色种子 ──────────────────────────────────────


def seed_builtin_roles(db: Session) -> None:
    """在数据库中写入内置角色（幂等，启动或测试 fixture 可反复调用）."""
    from cndb.plugins.workspaces.models import BUILTIN_ROLE_CODES

    builtin_defs: dict[str, tuple[str, dict[str, bool]]] = {
        "read": (
            "只读",
            {"READ": True, "EDIT_RECORDS": False, "EDIT_VIEWS": False, "EDIT_SCHEMA": False},
        ),
        "write": (
            "可编辑",
            {"READ": True, "EDIT_RECORDS": True, "EDIT_VIEWS": True, "EDIT_SCHEMA": False},
        ),
        "admin": (
            "表管理员",
            {"READ": True, "EDIT_RECORDS": True, "EDIT_VIEWS": True, "EDIT_SCHEMA": True},
        ),
    }
    for code in BUILTIN_ROLE_CODES:
        existing = db.query(Role).filter(Role.code == code).first()
        if existing is not None:
            # 补齐缺失的权限 key（升级场景）
            existing.ensure_permissions()
            continue
        name, perms = builtin_defs.get(code, (code, {}))
        r = Role(code=code, name=name, permissions=perms, is_builtin=True)
        r.ensure_permissions()
        db.add(r)
    db.flush()


# ── 列表 ──────────────────────────────────────────────


@router.get("", response_model=list[RoleResponse])
def list_roles(
    _current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_builtin: bool = Query(True, description="是否包含内置角色"),
) -> list[Role]:
    """列出所有数据角色（所有已登录成员均可查看）."""
    seed_builtin_roles(db)
    query = db.query(Role)
    if not include_builtin:
        query = query.filter(Role.is_builtin.is_(False))
    return query.order_by(Role.is_builtin.desc(), Role.id.asc()).all()


# ── 创建 ──────────────────────────────────────────────


@router.post("", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: RoleCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Role:
    """创建自定义角色 —— 仅 system_admin."""
    _require_system_admin(current_user)
    seed_builtin_roles(db)
    _validate_code(payload.code)
    _validate_permissions(payload.permissions)

    existing = db.query(Role).filter(Role.code == payload.code).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"角色 code {payload.code!r} 已存在")

    role = Role(
        code=payload.code,
        name=payload.name.strip(),
        description=payload.description,
        permissions=payload.permissions or {},
        is_builtin=False,
    )
    role.ensure_permissions()
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


# ── 详情 ──────────────────────────────────────────────


@router.get("/{role_id}", response_model=RoleResponse)
def get_role(
    role_id: int,
    _current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Role:
    """获取角色详情."""
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    return role


# ── 更新 ──────────────────────────────────────────────


@router.patch("/{role_id}", response_model=RoleResponse)
def update_role(
    role_id: int,
    payload: RoleUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Role:
    """更新角色 —— 仅 system_admin.

    内置角色可修改 name/description/permissions，但 code/is_builtin 不可改.
    """
    _require_system_admin(current_user)
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")

    update_data = payload.model_dump(exclude_unset=True)
    _validate_permissions(update_data.get("permissions"))
    if "name" in update_data:
        role.name = (update_data["name"] or "").strip()
    if "description" in update_data:
        role.description = update_data["description"] or ""
    if "permissions" in update_data:
        role.permissions = update_data["permissions"] or {}
        role.ensure_permissions()

    db.commit()
    db.refresh(role)
    return role


# ── 删除 ──────────────────────────────────────────────


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除角色 —— 仅 system_admin.

    内置角色不可删；正在被 TableMember 引用的角色不可删.
    """
    _require_system_admin(current_user)
    from cndb.plugins.tables.models import TableMember

    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    if role.is_builtin:
        raise HTTPException(status_code=400, detail="内置角色不可删除")

    in_use = db.query(TableMember).filter(TableMember.role == role.code).count()
    if in_use > 0:
        raise HTTPException(status_code=400, detail=f"角色正在被 {in_use} 个表成员引用，无法删除")

    db.delete(role)
    db.commit()


__all__ = ["router", "seed_builtin_roles"]
