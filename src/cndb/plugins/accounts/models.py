"""accounts 插件 ORM 模型：User.

设计来源：cndb Django accounts 模块，改用 SQLAlchemy 2.0 重写。
三员角色参考 GB/T 22239 等级保护：系统管理员 / 安全管理员 / 审计管理员，
以及普通用户 (user) 作为默认角色。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from cndb.models.base import Base, TimestampMixin


class UserRole(StrEnum):
    """用户角色枚举（三员 + 普通用户）.

    - system_admin: 系统管理员 — 负责系统配置、用户管理、工作区创建
    - security_admin: 安全管理员 — 负责权限策略、数据安全、访问控制
    - audit_admin: 审计管理员 — 负责审计日志查看、合规检查
    - user: 普通用户 — 默认角色，日常业务操作
    """

    SYSTEM_ADMIN = "system_admin"
    SECURITY_ADMIN = "security_admin"
    AUDIT_ADMIN = "audit_admin"
    USER = "user"

    @property
    def display_name(self) -> str:
        """角色中文显示名."""
        return {
            UserRole.SYSTEM_ADMIN: "系统管理员",
            UserRole.SECURITY_ADMIN: "安全管理员",
            UserRole.AUDIT_ADMIN: "审计管理员",
            UserRole.USER: "普通用户",
        }[self]


def _default_preferences() -> dict[str, Any]:
    """用户偏好默认值：空的激活视图映射."""
    return {"active_views": {}}


def _default_role() -> str:
    """默认角色为普通用户."""
    return UserRole.USER.value


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
    # 三员角色字段
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=_default_role, index=True)
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=_default_preferences,
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"User(id={self.id}, username={self.username!r}, role={self.role!r})"

    @property
    def role_enum(self) -> UserRole:
        """将 role 字符串转为枚举."""
        try:
            return UserRole(self.role)
        except ValueError:
            return UserRole.USER

    @property
    def is_system_admin(self) -> bool:
        return self.role_enum == UserRole.SYSTEM_ADMIN

    @property
    def is_security_admin(self) -> bool:
        return self.role_enum == UserRole.SECURITY_ADMIN

    @property
    def is_audit_admin(self) -> bool:
        return self.role_enum == UserRole.AUDIT_ADMIN

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


__all__ = ["User", "UserRole"]
