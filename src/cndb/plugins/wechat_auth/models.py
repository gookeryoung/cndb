"""微信账号与 cndb User 的关联模型."""

from __future__ import annotations

from datetime import datetime
from typing import override

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from cndb.models.base import Base


class WechatAccount(Base):
    """绑定 openid ↔ User.id.

    设计决策：
    - openid 唯一，一个微信身份只对应一个 cndb 用户
    - 支持 unionid（若小程序绑定开放平台）用于多端统一身份
    - session_key 持久化用于后续敏感数据解密（手机号等）
    """

    __tablename__ = "wechat_accounts"
    __table_args__ = (Index("ix_wechat_unionid", "unionid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    openid: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    unionid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    session_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # 关联到 accounts_user（级联删除：删用户时清理绑定）
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    nickname: Mapped[str | None] = mapped_column(String(128), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @override
    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"WechatAccount(id={self.id}, openid={self.openid!r}, user_id={self.user_id})"


__all__ = ["WechatAccount"]
