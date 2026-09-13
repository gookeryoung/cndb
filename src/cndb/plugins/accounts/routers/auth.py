"""认证路由：注册 / 登录 / 当前用户 / 用户管理.

三员权限设计：
- 公开注册 /auth/register: 仅允许注册 user (普通用户) 角色
- 管理员创建 /auth/admin-register: 仅超级管理员可调用，可指定任意角色
- 列出用户 /auth/users: 仅超级管理员可调用
- 更新角色 /auth/users/{id}/role: 仅超级管理员可调用
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.security import create_access_token
from cndb.plugins.accounts.models import User, UserRole
from cndb.plugins.accounts.schemas.auth import (
    PUBLIC_REGISTERABLE_ROLES,
    AdminRegisterRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _validate_role(role: str) -> UserRole:
    """校验 role 值是否合法，返回 UserRole 枚举."""
    try:
        return UserRole(role)
    except ValueError as exc:
        valid = ", ".join(r.value for r in UserRole)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的角色 '{role}'，可选值: {valid}",
        ) from exc


def _ensure_unique(db: Session, username: str, email: str | None) -> None:
    """检查用户名/邮箱去重，冲突则 raise 400."""
    if db.query(User).filter(User.username == username).first() is not None:
        raise HTTPException(status_code=400, detail="用户名已被使用")
    if email and db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=400, detail="邮箱已被使用")


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> User:
    """公开注册新用户.

    安全约束：公开注册仅允许注册 user (普通用户) 角色。如 payload.role
    指定了三员角色，则自动降级为 user 并在响应体中体现。

    Args:
        payload: 注册请求体（用户名/邮箱/昵称/密码/角色）
        db: 数据库会话

    Returns:
        创建后的 User 对象
    """
    _ensure_unique(db, payload.username, payload.email)

    # 公开注册只能选 user 角色
    if payload.role not in PUBLIC_REGISTERABLE_ROLES:
        # 降级处理：不要让用户知道可以越权，静默降级
        role_value = UserRole.USER.value
    else:
        role_value = payload.role

    _validate_role(role_value)

    user = User(
        username=payload.username,
        email=payload.email,
        nickname=payload.nickname,
        role=role_value,
    )
    user.set_password(payload.password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/admin-register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="管理员创建用户",
)
def admin_register(
    payload: AdminRegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """由超级管理员创建用户，可指定任意角色（含三员）.

    Args:
        payload: 管理员创建请求体（role 必填）
        db: 数据库会话
        current_user: 当前登录用户，必须是超级管理员

    Returns:
        创建后的 User 对象
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅超级管理员可创建用户",
        )

    _ensure_unique(db, payload.username, payload.email)
    validated = _validate_role(payload.role)

    user = User(
        username=payload.username,
        email=payload.email,
        nickname=payload.nickname,
        role=validated.value,
    )
    # 指定角色对应的语义化 nickname（如果没填）
    if not user.nickname:
        user.nickname = validated.display_name
    user.set_password(payload.password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """用户登录，返回 JWT.

    支持用户名或邮箱作为登录标识.

    Args:
        payload: 登录请求体
        db: 数据库会话

    Returns:
        JWT 令牌响应
    """
    user = db.query(User).filter((User.username == payload.login) | (User.email == payload.login)).first()
    if user is None or not user.is_active or not user.check_password(payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名/邮箱或密码错误",
        )
    access_token = create_access_token(subject=user.id, extra={"username": user.username})
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> User:
    """返回当前登录用户信息."""
    if current_user is None:
        raise HTTPException(status_code=401, detail="未认证")
    return current_user


@router.get("/users", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    role_filter: str | None = Query(default=None, description="按角色筛选"),
) -> list[User]:
    """列出所有用户（仅超级管理员）.

    Args:
        db: 数据库会话
        current_user: 必须是超级管理员
        role_filter: 可选角色筛选

    Returns:
        用户列表
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅超级管理员可查看用户列表",
        )
    q = db.query(User)
    if role_filter is not None:
        _validate_role(role_filter)
        q = q.filter(User.role == role_filter)
    return q.order_by(User.id).all()


@router.patch("/users/{user_id}/role", response_model=UserResponse)
def update_user_role(
    user_id: int,
    new_role: str = Query(..., description="新角色: system_admin / security_admin / audit_admin / user"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """更新指定用户的角色（仅超级管理员）.

    Args:
        user_id: 目标用户 ID
        new_role: 新角色字符串
        db: 数据库会话
        current_user: 必须是超级管理员

    Returns:
        更新后的 User 对象
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅超级管理员可修改用户角色",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    validated = _validate_role(new_role)
    user.role = validated.value
    db.commit()
    db.refresh(user)
    return user
