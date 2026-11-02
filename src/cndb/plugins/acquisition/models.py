"""acquisition 插件 ORM 模型：采集策略 / 运行 / 轮次 / 条目台账（ADR 0085 P0）.

四张表（见 ADR 0085 §1）：

- ``acquisition_strategy``  策略定义：四段规则 JSON（scope / filter_rule / targets / iteration）
  + 调度 + 租约；**不复制** datasource job 的请求与凭证；
- ``acquisition_run``       一次运行：状态 / 规则快照 / 计数 / 预算消耗 / 失败明细；
- ``acquisition_round``     轮次明细（对齐 endo ``iteration_history``，可查询）；
- ``acquisition_item``      条目台账：来源追溯 + 跨运行去重键 + 落点绑定。

半结构化配置一律 JSON 列，与 ``datasource_sync_job`` 的口径一致：
规则新增维度不改表。
"""

from __future__ import annotations

import datetime as dt
import enum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cndb.models.base import Base, TimestampMixin


class RunStatus(enum.StrEnum):
    """一次运行的状态（``partial`` = 部分渠道 / 落点失败或预算触顶）."""

    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunTrigger(enum.StrEnum):
    """触发来源."""

    MANUAL = "manual"
    SCHEDULER = "scheduler"
    CLI = "cli"


class ReviewState(enum.StrEnum):
    """扩展词复核状态（D5 / D14）：auto = 纯确定性，llm = 模型判断后自动续跑，manual = 停等用户."""

    AUTO = "auto"
    LLM = "llm"
    PENDING = "pending"
    CONFIRMED = "confirmed"


#: 扩展词来源（轮次留痕用）
KEYWORD_SOURCE_TF = "tf"
KEYWORD_SOURCE_LLM = "llm"
KEYWORD_SOURCE_USER = "user"
KEYWORD_SOURCES = (KEYWORD_SOURCE_TF, KEYWORD_SOURCE_LLM, KEYWORD_SOURCE_USER)


class AcquisitionStrategy(TimestampMixin, Base):
    """采集策略：一条用户规则 + 调度 + 预算（ADR 0085 §1）."""

    __tablename__ = "acquisition_strategy"
    __table_args__ = (
        Index("ix_acquisition_strategy_ws_enabled", "workspace_id", "enabled"),
        {"extend_existing": True},
    )

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    # 采集范围与来源：{"channels":[...], "query":..., "time_window":{...}, "max_results_per_channel":n}
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # 筛选规则：三段式 + 布尔式（rules/filter.py 的 FilterRule）
    filter_rule: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # 落点：{"kind":"table","table_id":1,"match_keys":[...],"field_mapping":{...}}
    targets: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    # 迭代：轮次 / 扩展 / 停止 / 预算
    iteration: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # 语义辅助开关：{"enabled":true,"actions":[...]}
    llm: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # 调度：{"mode":"manual|daily|interval|cron", ...}
    schedule: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # 规则版本：实质变更 +1；运行快照带此值
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    # 执行租约（与 datasource_sync_job 同语义，ADR 0006 I4）
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class AcquisitionRun(TimestampMixin, Base):
    """一次策略运行（成功 / 部分成功 / 失败 / 复核暂停都落一行）."""

    __tablename__ = "acquisition_run"
    __table_args__ = (
        Index("ix_acquisition_run_strategy_started", "strategy_id", "started_at"),
        {"extend_existing": True},
    )

    strategy_id: Mapped[int] = mapped_column(
        ForeignKey("acquisition_strategy.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default=RunTrigger.MANUAL.value)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=RunStatus.RUNNING.value, index=True)
    # 运行时规则快照（含 rule_version），保证「哪版规则产生了哪批数据」可追溯
    rule_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    round_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_message: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    docs_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    docs_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    docs_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # {"requests":n,"rows":n,"llm_calls":n,"llm_tokens":n}
    budget_used: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # {"channels":{...},"channel_errors":[...],"llm_degraded":[...],"budget_exhausted":bool}
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AcquisitionRound(TimestampMixin, Base):
    """轮次明细：检索式 / 渠道统计 / 新增量 / 扩展词 / 停止原因."""

    __tablename__ = "acquisition_round"
    __table_args__ = (
        UniqueConstraint("run_id", "round_no", name="uq_acquisition_round_run_no"),
        {"extend_existing": True},
    )

    run_id: Mapped[int] = mapped_column(
        ForeignKey("acquisition_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    query: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    channels: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    # {"total_collected","after_dedup","after_filter","by_channel":{},"channel_errors":[]}
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    new_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accumulated_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # [{"term","count","df","weight","source","reason?","dropped?","rename_to?"}]
    top_keywords: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    next_query: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    gap: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    review_state: Mapped[str] = mapped_column(String(16), nullable=False, default=ReviewState.AUTO.value)
    # empty_round / min_new / budget / max_rounds / None
    stop_reason: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AcquisitionItem(TimestampMixin, Base):
    """条目台账：来源追溯 + 跨运行去重 + 落点绑定（ADR 0085 I9）."""

    __tablename__ = "acquisition_item"
    __table_args__ = (
        UniqueConstraint("strategy_id", "dedupe_key", name="uq_acquisition_item_strategy_key"),
        Index("ix_acquisition_item_run", "run_id"),
        {"extend_existing": True},
    )

    strategy_id: Mapped[int] = mapped_column(
        ForeignKey("acquisition_strategy.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[int | None] = mapped_column(ForeignKey("acquisition_run.id", ondelete="SET NULL"), nullable=True)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    channel: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # doi: / url: / sha1: / title: 前缀 + 归一值
    dedupe_key: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    published_at: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    match_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # table / document
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    # 表落点记 table_id；文档落点记 document_id
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 内容指纹：文档落点判断「是否需要新版本」
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")


__all__ = [
    "KEYWORD_SOURCES",
    "KEYWORD_SOURCE_LLM",
    "KEYWORD_SOURCE_TF",
    "KEYWORD_SOURCE_USER",
    "AcquisitionItem",
    "AcquisitionRound",
    "AcquisitionRun",
    "AcquisitionStrategy",
    "ReviewState",
    "RunStatus",
    "RunTrigger",
]
