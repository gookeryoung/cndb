"""FastAPI 依赖注入工具函数.

集中放置 Depends() 可调用对象，避免散落在各路由文件.

认证方式：JWT（Authorization: Bearer <jwt>），由前端登录流程签发.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User

from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.core.security import decode_access_token

logger = logging.getLogger(__name__)


def get_request_id(x_request_id: str | None = Header(default=None)) -> str:
    """生成或透传请求 ID（链路追踪用）.

    若上游调用方已传入 X-Request-Id，则直接透传；否则生成一个新的 UUID.
    下游服务可通过依赖注入在任意位置拿到同一个 request_id.
    """
    if x_request_id:
        return x_request_id
    return uuid.uuid4().hex


# ── 认证依赖 ──────────────────────────────────────────

# 单机模式内置本地用户名（get-or-create 幂等键）
_LOCAL_USERNAME = "local"


def _get_local_user(db: Session) -> User:
    """返回单机模式内置本地用户（惰性 get-or-create，幂等）.

    用户不存在时创建：is_superuser=True 保证单机用户拥有全部能力；
    hashed_password 取随机不可知值（local 模式下 login 入口已 403，
    密码永不参与校验）。并发首建（多 worker 同时首次访问）撞 username
    unique 约束时回退重查，必命中先建方的用户行。

    Args:
        db: 数据库会话

    Returns:
        username='local' 的内置用户行
    """
    from cndb.plugins.accounts.models import User

    user = db.query(User).filter(User.username == _LOCAL_USERNAME).first()
    if user is not None:
        return user

    user = User(
        username=_LOCAL_USERNAME,
        nickname="本地用户",
        is_superuser=True,
    )
    user.hashed_password = secrets.token_urlsafe(32)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # 并发首建竞态：另一方已提交同名用户，回退重查
        db.rollback()
        user = db.query(User).filter(User.username == _LOCAL_USERNAME).first()
        if user is None:
            raise
        return user
    logger.info("单机模式首次访问，已创建内置本地用户: id=%s", user.id)
    return user


def _authenticate_jwt(token: str, db: Session) -> User | None:
    """尝试用 JWT 解析令牌并加载用户."""
    from cndb.plugins.accounts.models import User

    try:
        payload = decode_access_token(token)
    except Exception:
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        user_id = int(sub)
    except (ValueError, TypeError):
        # 防御：sub 不是合法整数（如格式错误或签名已知的伪造令牌）时返回 None，
        # 避免 ValueError 穿透到 FastAPI 变成 500
        logger.warning("JWT sub claim 不是合法整数: %r", sub)
        return None
    return db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> object | None:
    """JWT 认证：解析 Bearer 令牌并加载用户.

    LOCAL_MODE=True（单机模式）时完全忽略 Authorization 头（包括同机
    持有的旧 token），所有请求统一归属内置本地用户——这是单机定位的
    明确语义，非缺陷。

    返回：
        单机模式返回内置本地用户；否则认证成功返回 User 对象，
        AUTH_ENABLED=False 或无认证头时返回 None；
        AUTH_ENABLED=True 但认证失败时抛 401.
    """

    if settings.LOCAL_MODE:
        # 单机模式：免登录，直接映射内置本地用户
        return _get_local_user(db)

    if not settings.AUTH_ENABLED:
        return None

    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth_header:
        return None

    # 格式: "Bearer <token>"
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    token = parts[1].strip()
    if not token:
        return None

    user: User | None = _authenticate_jwt(token, db)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_optional_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> object | None:
    """可选认证：有令牌则解析，无令牌或无效也不报错（返回 None）.

    适用于公开表单/共享视图等"登录更好、匿名也行"的场景.
    """
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None


__all__ = [
    "get_current_user",
    "get_optional_user",
    "get_request_id",
]
