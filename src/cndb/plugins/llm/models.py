"""llm 插件 ORM 模型（ADR 0020 P0）.

两张表：

- ``llm_user_config``  个人大模型连接（自 ``datasource_user_llm_config`` 搬迁）：
  地址 / 模型 / 加密 API Key / 系统提示词覆盖，每人一条；
- ``llm_run``          调用留痕：每次模型调用的元数据（动作 / 模型 / token / 耗时 / 状态），
  **不存提示词与输出全文**；不属于工作区数据，不进备份。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cndb.models.base import Base, TimestampMixin


class LlmUserConfig(TimestampMixin, Base):
    """个人「大模型连接」：配一次即可被该用户的所有 AI 能力复用（ADR 0019 / ADR 0020）.

    - ``user_id``：唯一，一个用户至多一条连接；随用户级联删除；
    - ``base_url``：OpenAI 兼容服务地址（默认 ``https://api.deepseek.com``）；
    - ``model``：模型名（默认 ``deepseek-chat``）；
    - ``api_key``：**Fernet 密文**，读接口只回 ``has_api_key``，不随备份导出；
    - ``system_prompt``：可选覆盖系统提示词，空串表示使用内置默认值。
    """

    __tablename__ = "llm_user_config"
    __table_args__ = {"extend_existing": True}

    user_id: Mapped[int] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    # 密文（core.crypto.encrypt_secret）；空串表示未配置
    api_key: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")


class LlmRun(TimestampMixin, Base):
    """一次模型调用的留痕（成功 / 失败都落一行）.

    刻意**不存**提示词与输出全文：``detail`` 只放定位信息（目标类型 / id、输入输出字符数、
    重试次数、request_id），``error`` 截断且不含提示词 —— 工作区内容不因 AI 调用二次落库。
    """

    __tablename__ = "llm_run"
    __table_args__ = (
        Index("ix_llm_run_created_at", "created_at"),
        Index("ix_llm_run_user_created", "user_id", "created_at"),
        {"extend_existing": True},
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 平台级动作可为空（无工作区语义）
    workspace_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success", index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 失败摘要（≤500 字，不含提示词 / 输出全文）
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


__all__ = ["LlmRun", "LlmUserConfig"]
