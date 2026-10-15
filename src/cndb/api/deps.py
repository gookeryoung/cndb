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
from cndb.core.observability import get_request_id as current_request_id
from cndb.core.observability import set_actor_ids
from cndb.core.security import decode_access_token

logger = logging.getLogger(__name__)


def get_request_id(x_request_id: str | None = Header(default=None)) -> str:
    """请求关联 id：优先观测中间件生成/透传的值，其次请求头，最后自行生成.

    与访问日志、慢 SQL 日志使用同一个值，便于按 id 串联一次请求的全部痕迹；
    在请求上下文之外（如后台任务直接调用）保留「无值则生成 UUID hex」的既有契约。
    """
    from_middleware = current_request_id()
    return from_middleware or x_request_id or uuid.uuid4().hex


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
    user: User | None = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if user is None:
        return None
    # 令牌代次校验：改密 / 管理员强制下线后 token_version +1，既有 access token 立即失效
    if int(payload.get("tv", 0) or 0) != int(getattr(user, "token_version", 0) or 0):
        logger.info("令牌代次已失效（user_id=%s），要求重新登录", user_id)
        return None
    return user


def _unauthorized(detail: str = "未认证或登录已过期") -> HTTPException:
    """统一的 401（带 WWW-Authenticate），供未认证 / 令牌非法等路径复用."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> object | None:
    """JWT 认证：解析 Bearer 令牌并加载用户.

    LOCAL_MODE=True（单机模式）时完全忽略 Authorization 头（包括同机
    持有的旧 token），所有请求统一归属内置本地用户——这是单机定位的
    明确语义，非缺陷。

    返回 / 抛出：
        - LOCAL_MODE：返回内置本地用户（忽略 Authorization 头）；
        - AUTH_ENABLED=True：认证成功返回 User；**未带认证头 / 头格式非法 / 令牌为空 /
          令牌无效或过期一律抛 401**（此前前三种情况返回 None，端点解引用会变成 500）；
        - AUTH_ENABLED=False：返回 None（该模式下不做认证，需要用户的端点应自行决定语义，
          或改用 get_optional_user 显式接收匿名）。

    注意：需要"登录更好、匿名也行"的路由应使用 :func:`get_optional_user`，它会吞掉 401 返回 None。
    """

    if settings.LOCAL_MODE:
        # 单机模式：免登录，直接映射内置本地用户
        local_user = _get_local_user(db)
        set_actor_ids(
            request.state,
            user_id=getattr(local_user, "id", None),
            username=getattr(local_user, "username", None),
        )
        return local_user

    if not settings.AUTH_ENABLED:
        return None

    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth_header:
        raise _unauthorized("缺少认证信息，请先登录")

    # 格式: "Bearer <token>"
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise _unauthorized("认证头格式非法，应为 Bearer <token>")

    token = parts[1].strip()
    if not token:
        raise _unauthorized("令牌为空，请重新登录")

    user: User | None = _authenticate_jwt(token, db)

    if user is None:
        raise _unauthorized("无效或过期的令牌")
    set_actor_ids(
        request.state,
        user_id=getattr(user, "id", None),
        username=getattr(user, "username", None),
    )
    return user


def get_optional_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> object | None:
    """可选认证：有令牌则解析，无令牌或无效也不报错（返回 None）.

    适用于公开共享视图等"登录更好、匿名也行"的场景.
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
