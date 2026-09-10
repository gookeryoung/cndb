"""认证路由：注册 / 登录 / 当前用户."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.security import create_access_token
from cndb.plugins.accounts.models import User
from cndb.plugins.accounts.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> User:
    """注册新用户.

    Args:
        payload: 注册请求体（用户名/邮箱/昵称/密码）
        db: 数据库会话

    Returns:
        创建后的 User 对象
    """
    # 用户名去重
    if db.query(User).filter(User.username == payload.username).first() is not None:
        raise HTTPException(status_code=400, detail="用户名已被使用")
    # 邮箱去重
    if payload.email and db.query(User).filter(User.email == payload.email).first() is not None:
        raise HTTPException(status_code=400, detail="邮箱已被使用")
    user = User(
        username=payload.username,
        email=payload.email,
        nickname=payload.nickname,
    )
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
