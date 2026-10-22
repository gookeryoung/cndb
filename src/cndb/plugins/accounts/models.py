"""accounts 插件 ORM 模型：User.

设计来源：cndb Django accounts 模块，改用 SQLAlchemy 2.0 重写。
三员角色参考 GB/T 22239 等级保护：系统管理员 / 安全管理员 / 审计管理员，
以及普通用户 (user) 作为默认角色。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
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
    """用户偏好默认值：激活视图映射 + 主页自定义顺序与收藏视图（ADR 0021）."""
    return {
        "active_views": {},
        "workspace_order": [],
        "favorite_views": [],
    }


def _default_role() -> str:
    """默认角色为普通用户."""
    return UserRole.USER.value


class User(TimestampMixin, Base):
    """平台用户，对齐 cndb AbstractUser 的核心字段."""

    __tablename__ = "accounts_user"
    __table_args__ = {"extend_existing": True}

    username: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    nickname: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 令牌代次：改密 / 管理员强制下线时 +1，使已签发的 access token 立即失效
    # （JWT 本身无状态，靠 tv claim 与当前值比对实现吊销）
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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


class RefreshToken(TimestampMixin, Base):
    """刷新令牌（会话）记录 —— 服务端可吊销.

    设计要点：
    - **只存哈希**：库中保存 token 的 SHA-256，泄库不等于可直接使用；
    - **一次性轮换**：每次 /refresh 作废旧 token 并写入 ``replaced_by``，形成链；
      若已被轮换的 token 再次被使用，视为泄露 → 吊销该用户全部会话（见 sessions 服务）；
    - 撤销 ``revoked_at`` 非空即失效；``expires_at`` 到期同样失效；
    - 单机 SQLite 下即可承担会话表职责，无需 Redis。
    """

    __tablename__ = "accounts_refreshtoken"
    __table_args__ = {"extend_existing": True}

    user_id: Mapped[int] = mapped_column(ForeignKey("accounts_user.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 被哪一枚新令牌取代（轮换链）；null 表示尚未轮换
    replaced_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"RefreshToken(id={self.id}, user_id={self.user_id}, revoked={self.revoked_at is not None})"


class UserAuditLog(TimestampMixin, Base):
    """用户管理操作日志（平台级审计，与 tables_auditlog 平行）.

    记录管理员对用户的编辑/角色变更/启禁用/批量操作，detail 保存
    before/after 快照与批量摘要；日志只增不改不删（不提供写删 API）。
    """

    __tablename__ = "accounts_userauditlog"
    __table_args__ = {"extend_existing": True}

    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"UserAuditLog(id={self.id}, action={self.action!r}, actor_id={self.actor_id}, target={self.target_user_id})"


__all__ = ["User", "UserAuditLog", "UserRole"]
