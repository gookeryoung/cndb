"""FastAPI 依赖注入工具函数.

集中放置 Depends() 可调用对象，避免散落在各路由文件.

认证双轨：
- JWT：Authorization: Bearer <jwt>，前端登录后使用
- ApiToken：Authorization: Bearer cndb_<sha256hex>，外部脚本使用
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException, Request, status
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
    return db.query(User).filter(User.id == int(sub), User.is_active.is_(True)).first()


def _authenticate_api_token(token: str, db: Session) -> User | None:
    """尝试用 ApiToken 摘要匹配令牌并加载用户，同时更新 last_used_at."""
    import datetime as dt
    import hashlib

    from cndb.plugins.accounts.models import ApiToken, User

    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    at = db.query(ApiToken).filter(ApiToken.digest == digest).first()
    if at is None:
        return None
    at.last_used_at = dt.datetime.now(dt.UTC)
    db.commit()
    return db.query(User).filter(User.id == at.user_id, User.is_active.is_(True)).first()


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> object | None:
    """双轨认证：先尝试 JWT，再尝试 ApiToken.

    返回：
        认证成功返回 User 对象；AUTH_ENABLED=False 或无认证头时返回 None；
        AUTH_ENABLED=True 但认证失败时抛 401.
    """

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

    # 先尝试 ApiToken（cndb_ 前缀），再尝试 JWT
    user: User | None = None
    if token.startswith("cndb_"):
        user = _authenticate_api_token(token, db)
    if user is None:
        user = _authenticate_jwt(token, db)

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
