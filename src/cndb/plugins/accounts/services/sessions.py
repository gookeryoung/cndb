"""刷新令牌（会话）服务 —— 签发 / 轮换 / 吊销 / 复用检测.

为什么需要它：access token 是**无状态 JWT**，签发后在有效期内无法撤回。引入刷新令牌后：

- access token 可以保持短有效期，会话延续交给刷新令牌；
- 刷新令牌落库（**只存 SHA-256**），因此可以真正"注销"、"全部下线"、"管理员强制下线"；
- **一次性轮换**：每次刷新作废旧令牌并记录 ``replaced_by``；若已被轮换的令牌再次出现，
  视为令牌泄露（攻击者与真实用户同时持有一枚），立即吊销该用户全部会话。

单机 SQLite 即可承担会话表职责，无需 Redis。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.core.errors import UnauthorizedError
from cndb.core.security import create_access_token, create_refresh_token, hash_token
from cndb.plugins.accounts.models import RefreshToken, User


class TokenPairDict(TypedDict):
    """TokenPair 的字典形式（供 Pydantic 响应模型解包，避免 object 类型告警）."""

    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


@dataclass(frozen=True)
class TokenPair:
    """一次登录/刷新返回的令牌对."""

    access_token: str
    refresh_token: str
    expires_in: int

    def as_dict(self) -> TokenPairDict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": "bearer",
            "expires_in": self.expires_in,
        }


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _issue(db: Session, user: User, *, user_agent: str | None = None) -> TokenPair:
    """为用户签发一对新令牌，并落库刷新令牌记录."""
    raw = create_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=_now() + timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS),
            user_agent=(user_agent or None),
        )
    )
    access = create_access_token(
        subject=user.id,
        extra={"username": user.username, "role": user.role},
        token_version=user.token_version,
    )
    return TokenPair(access_token=access, refresh_token=raw, expires_in=settings.JWT_EXPIRE_MINUTES * 60)


def issue_pair(db: Session, user: User, *, user_agent: str | None = None) -> TokenPair:
    """登录成功后签发令牌对（提交事务）."""
    pair = _issue(db, user, user_agent=user_agent)
    db.commit()
    return pair


def _find(db: Session, raw_token: str) -> RefreshToken | None:
    return db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))).scalar_one_or_none()


def revoke_all(db: Session, user_id: int, *, reason: str = "revoked") -> int:
    """吊销某用户全部未吊销刷新令牌，返回受影响行数."""
    result = db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason=reason)
    )
    db.commit()
    # CursorResult.rowcount：SQLAlchemy 2.0 的 execute() 返回类型未声明该属性
    rowcount = getattr(result, "rowcount", 0) or 0
    return int(rowcount)


def revoke_token(db: Session, raw_token: str, *, reason: str = "logout") -> bool:
    """吊销单枚刷新令牌（登出）；不存在或已吊销返回 False."""
    row = _find(db, raw_token)
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = _now()
    row.revoked_reason = reason
    db.commit()
    return True


def rotate(db: Session, raw_token: str, *, user_agent: str | None = None) -> tuple[User, TokenPair]:
    """用刷新令牌换取新的令牌对（一次性轮换）.

    Raises:
        UnauthorizedError: 令牌不存在 / 已过期 / 已吊销；若检测到**已轮换令牌被复用**，
            则先吊销该用户全部会话再抛错。
    """
    row = _find(db, raw_token)
    if row is None:
        raise UnauthorizedError("刷新令牌无效，请重新登录")

    if row.revoked_at is not None:
        if row.replaced_by is not None:
            # 复用检测：已轮换的令牌再次出现 → 视为泄露，吊销该用户全部会话
            revoke_all(db, row.user_id, reason="reuse_detected")
            raise UnauthorizedError("检测到刷新令牌被重复使用，已吊销全部会话，请重新登录")
        raise UnauthorizedError("刷新令牌已失效，请重新登录")

    if row.expires_at <= _now():
        row.revoked_at = _now()
        row.revoked_reason = "expired"
        db.commit()
        raise UnauthorizedError("刷新令牌已过期，请重新登录")

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        revoke_all(db, row.user_id, reason="user_inactive")
        raise UnauthorizedError("账号不可用，请联系管理员")

    new_pair = _issue(db, user, user_agent=user_agent)
    row.revoked_at = _now()
    row.revoked_reason = "rotated"
    row.replaced_by = hash_token(new_pair.refresh_token)
    db.commit()
    return user, new_pair


def list_sessions(db: Session, user_id: int) -> list[RefreshToken]:
    """列出某用户仍有效的会话（未吊销且未过期），新会话在前."""
    now = _now()
    return list(
        db.execute(
            select(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .order_by(RefreshToken.id.desc())
        ).scalars()
    )


def revoke_session(db: Session, user_id: int, session_id: int) -> bool:
    """吊销指定会话（仅限本人），返回是否命中."""
    row = db.get(RefreshToken, session_id)
    if row is None or row.user_id != user_id or row.revoked_at is not None:
        return False
    row.revoked_at = _now()
    row.revoked_reason = "session_revoked"
    db.commit()
    return True


__all__ = [
    "TokenPair",
    "TokenPairDict",
    "issue_pair",
    "list_sessions",
    "revoke_all",
    "revoke_session",
    "revoke_token",
    "rotate",
]
