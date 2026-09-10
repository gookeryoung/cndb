"""accounts 插件 ORM 模型：User + ApiToken.

设计来源：cndb Django accounts/tokens 模块，改用 SQLAlchemy 2.0 重写。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cndb.models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    """平台用户，对齐 cndb AbstractUser 的核心字段."""

    __tablename__ = "accounts_user"
    __table_args__ = {"extend_existing": True}

    username: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=True)
    nickname: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 关系：ApiToken
    api_tokens: Mapped[list[ApiToken]] = relationship(back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"User(id={self.id}, username={self.username!r})"

    def set_password(self, plain: str) -> None:
        """对明文密码 bcrypt 哈希并写入 hashed_password.

        Args:
            plain: 用户原始密码
        """
        from cndb.core.security import hash_password

        self.hashed_password = hash_password(plain)

    def check_password(self, plain: str) -> bool:
        """校验明文密码是否匹配当前哈希.

        Args:
            plain: 用户输入的明文密码
        """
        from cndb.core.security import verify_password

        return verify_password(plain, self.hashed_password)


def generate_api_token() -> str:
    """生成随机令牌明文：cndb_ 前缀 + 40 位十六进制随机串."""
    return f"cndb_{secrets.token_hex(20)}"


def hash_api_token(token: str) -> str:
    """返回令牌的 SHA-256 十六进制摘要（落库形式）."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ApiToken(TimestampMixin, Base):
    """API 访问令牌：明文仅签发时返回一次，库中只存 SHA-256 摘要."""

    __tablename__ = "accounts_apitoken"
    __table_args__ = {"extend_existing": True}

    user_id: Mapped[int] = mapped_column(ForeignKey("accounts_user.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    prefix: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)

    user: Mapped[User] = relationship(back_populates="api_tokens")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"ApiToken(id={self.id}, prefix={self.prefix!r}, name={self.name!r})"

    @classmethod
    def issue(cls, db: Session, user: User, name: str) -> tuple[ApiToken, str]:
        """签发新令牌：返回 (令牌对象, 明文)，明文仅此一次可见.

        Args:
            db: 数据库会话
            user: 令牌归属的用户
            name: 令牌名称（便于用户识别）

        Returns:
            (ApiToken 对象, 令牌明文)
        """
        token = generate_api_token()
        obj = cls(
            user_id=user.id,
            name=name,
            prefix=token[:12],
            digest=hash_api_token(token),
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj, token


# datetime 类型引用（供 type annotation 使用）
from sqlalchemy.orm import Session  # noqa: E402

__all__ = ["ApiToken", "User", "generate_api_token", "hash_api_token"]
