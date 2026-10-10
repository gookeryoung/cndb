"""用户管理路由：编辑 / 批量操作 / 启禁用 / 操作日志查询.

权限设计（对齐 .trae/designs/user-management-upgrade.md）：
- 用户列表 / 编辑 / 批量操作：仅超级管理员
- 操作日志查询：超级管理员或审计管理员（audit_admin 只读）
- 旧端点 /auth/users、/auth/users/{id}/role 已迁移至本路由组并删除
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.accounts.schemas.users import (
    BatchUserActionRequest,
    BatchUserActionResponse,
    UserAdminResponse,
    UserAdminUpdateRequest,
    UserAuditLogPage,
    UserAuditLogResponse,
    UserListPage,
)
from cndb.plugins.accounts.services.users import (
    UserAdminError,
    batch_user_action,
    get_user_or_none,
    query_audit_logs,
    update_user,
)

router = APIRouter(prefix="/users", tags=["users"])


def _require_superuser(current_user: User | None = Depends(get_current_user)) -> User:
    """写操作门控：仅超级管理员.

    Raises:
        HTTPException: 403 权限不足（含未认证 fallback，避免 None 解引用 500）
    """
    if current_user is None or not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅超级管理员可执行用户管理操作")
    return current_user


def _require_audit_reader(current_user: User | None = Depends(get_current_user)) -> User:
    """日志读取门控：超级管理员或审计管理员.

    Raises:
        HTTPException: 403 权限不足
    """
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅超级管理员或审计管理员可查看操作日志")
    if not (current_user.is_superuser or current_user.is_audit_admin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅超级管理员或审计管理员可查看操作日志")
    return current_user


def _map_user_admin_error(exc: UserAdminError) -> HTTPException:
    """业务校验异常统一映射为 400 + 中文明细."""
    return HTTPException(status_code=400, detail=str(exc))


@router.get("", response_model=UserListPage, summary="用户分页列表")
def list_users(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(_require_superuser)],
    keyword: str | None = Query(default=None, max_length=150, description="用户名/邮箱/昵称模糊搜索"),
    role: str | None = Query(default=None, description="按角色筛选"),
    is_active: bool | None = Query(default=None, description="按启用状态筛选"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
) -> UserListPage:
    """分页查询用户列表，支持关键词/角色/状态筛选（仅超级管理员）.

    Args:
        db: 数据库会话
        _current_user: 超级管理员
        keyword: 模糊匹配用户名/邮箱/昵称
        role: 角色筛选
        is_active: 启用状态筛选
        page: 页码
        page_size: 每页条数

    Returns:
        用户分页
    """
    from cndb.plugins.accounts.models import UserRole

    if role is not None and role not in {r.value for r in UserRole}:
        valid = ", ".join(r.value for r in UserRole)
        raise HTTPException(status_code=400, detail=f"无效的角色 '{role}'，可选值: {valid}")

    q = db.query(User)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((User.username.ilike(like)) | (User.email.ilike(like)) | (User.nickname.ilike(like)))
    if role is not None:
        q = q.filter(User.role == role)
    if is_active is not None:
        q = q.filter(User.is_active.is_(is_active))

    total = q.count()
    items = q.order_by(User.id).offset((page - 1) * page_size).limit(page_size).all()
    return UserListPage(total=total, items=[UserAdminResponse.model_validate(u) for u in items])


@router.patch("/{user_id}", response_model=UserAdminResponse, summary="编辑用户")
def edit_user(
    user_id: int,
    payload: UserAdminUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(_require_superuser)],
) -> UserAdminResponse:
    """编辑指定用户（用户名/邮箱/电话/昵称/角色/状态），变更写入操作日志.

    防护：不能修改自己的角色/状态；不能禁用最后一个可用超管。

    Args:
        user_id: 目标用户 ID
        payload: 编辑请求体（仅提交字段生效）
        db: 数据库会话
        current_user: 超级管理员

    Returns:
        更新后的用户
    """
    target = get_user_or_none(db, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        user = update_user(db, actor=current_user, target=target, data=payload)
    except UserAdminError as exc:
        raise _map_user_admin_error(exc) from exc
    return UserAdminResponse.model_validate(user)


@router.post("/batch", response_model=BatchUserActionResponse, summary="批量操作")
def batch_action(
    payload: BatchUserActionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(_require_superuser)],
) -> BatchUserActionResponse:
    """批量启用/禁用/设置角色，返回逐项结果.

    Args:
        payload: 批量操作请求体
        db: 数据库会话
        current_user: 超级管理员

    Returns:
        逐项结果汇总
    """
    try:
        return batch_user_action(db, actor=current_user, payload=payload)
    except UserAdminError as exc:
        raise _map_user_admin_error(exc) from exc


@router.get("/audit-logs", response_model=UserAuditLogPage, summary="操作日志查询")
def list_audit_logs(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(_require_audit_reader)],
    action: str | None = Query(default=None, description="按动作筛选"),
    actor_id: int | None = Query(default=None, description="按操作人筛选"),
    target_user_id: int | None = Query(default=None, description="按被操作用户筛选"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
) -> UserAuditLogPage:
    """分页查询用户管理操作日志（时间倒序，超级管理员/审计管理员）.

    Args:
        db: 数据库会话
        _current_user: 超级管理员或审计管理员
        action: 动作筛选
        actor_id: 操作人筛选
        target_user_id: 被操作用户筛选
        page: 页码
        page_size: 每页条数

    Returns:
        日志分页
    """
    logs, total = query_audit_logs(
        db, page=page, page_size=page_size, action=action, actor_id=actor_id, target_user_id=target_user_id
    )
    return UserAuditLogPage(total=total, items=[UserAuditLogResponse.model_validate(item) for item in logs])


@router.get("/{user_id}/audit-logs", response_model=UserAuditLogPage, summary="单用户操作日志")
def list_user_audit_logs(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(_require_audit_reader)],
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
) -> UserAuditLogPage:
    """查询指定用户的操作日志（时间倒序，超级管理员/审计管理员）.

    Args:
        user_id: 目标用户 ID
        db: 数据库会话
        _current_user: 超级管理员或审计管理员
        page: 页码
        page_size: 每页条数

    Returns:
        日志分页
    """
    if get_user_or_none(db, user_id) is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    logs, total = query_audit_logs(db, page=page, page_size=page_size, target_user_id=user_id)
    return UserAuditLogPage(total=total, items=[UserAuditLogResponse.model_validate(item) for item in logs])
