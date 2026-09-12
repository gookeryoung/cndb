"""accounts 插件 ORM 模型：User.

设计来源：cndb Django accounts 模块，改用 SQLAlchemy 2.0 重写。
"""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

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


__all__ = ["User"]
