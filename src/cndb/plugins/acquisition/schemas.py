"""acquisition API 数据结构（Pydantic v2，ADR 0085 §7）."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field


class StrategyCreate(BaseModel):
    """新建采集策略：四段规则 + 调度。"""

    name: str = Field(..., min_length=1, max_length=128)
    scope: dict[str, Any] = Field(..., description="渠道 / 检索式 / 时间窗 / 每渠道上限")
    filter_rule: dict[str, Any] = Field(default_factory=dict, description="三段式筛选 + 布尔式")
    targets: list[dict[str, Any]] = Field(..., description="落点数组（本期仅 table）")
    iteration: dict[str, Any] = Field(default_factory=dict, description="轮次 / 扩展 / 停止 / 预算")
    llm: dict[str, Any] = Field(default_factory=dict, description="语义辅助开关与动作白名单")
    schedule: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False


class StrategyUpdate(BaseModel):
    """局部更新：未提供的字段保持不变；实质变更 → ``rule_version`` +1。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    scope: dict[str, Any] | None = None
    filter_rule: dict[str, Any] | None = None
    targets: list[dict[str, Any]] | None = None
    iteration: dict[str, Any] | None = None
    llm: dict[str, Any] | None = None
    schedule: dict[str, Any] | None = None
    enabled: bool | None = None


class StrategyOut(BaseModel):
    id: int
    workspace_id: int
    name: str
    enabled: bool
    scope: dict[str, Any]
    filter_rule: dict[str, Any]
    targets: list[dict[str, Any]]
    iteration: dict[str, Any]
    llm: dict[str, Any]
    schedule: dict[str, Any]
    rule_version: int
    last_run_at: dt.datetime | None = None
    last_status: str = ""
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class StrategyListResponse(BaseModel):
    total: int
    strategies: list[StrategyOut]


class RoundOut(BaseModel):
    id: int
    run_id: int
    round_no: int
    query: str
    channels: list[Any]
    stats: dict[str, Any]
    new_items: int
    accumulated_items: int
    top_keywords: list[Any]
    next_query: str
    gap: dict[str, Any]
    review_state: str
    stop_reason: str
    status: str
    error_message: str
    duration_ms: int


class RunOut(BaseModel):
    id: int
    strategy_id: int
    trigger: str
    status: str
    round_count: int
    progress: int
    progress_message: str
    fetched: int
    inserted: int
    updated: int
    skipped: int
    docs_created: int
    docs_updated: int
    docs_skipped: int
    budget_used: dict[str, Any]
    error_message: str
    detail: dict[str, Any]
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    duration_ms: int


class RunListResponse(BaseModel):
    total: int
    runs: list[RunOut]


class RunDetailResponse(BaseModel):
    run: RunOut
    rounds: list[RoundOut]


class PreviewRequest(BaseModel):
    """预览：可覆盖检索式（保存前试算），不落库。"""

    query: str | None = Field(default=None, max_length=500)


class PreviewSample(BaseModel):
    title: str = ""
    url: str = ""
    published_at: str = ""
    match_score: int = 0


class PreviewResponse(BaseModel):
    status: str
    collected: int
    after_dedup: int
    after_filter: int
    by_channel: dict[str, int] = Field(default_factory=dict)
    samples: list[PreviewSample] = Field(default_factory=list)
    channel_errors: list[dict[str, str]] = Field(default_factory=list)


class RuleValidateRequest(BaseModel):
    """规则片段校验（前端表单实时校验复用）。"""

    scope: dict[str, Any] = Field(default_factory=dict)
    filter_rule: dict[str, Any] = Field(default_factory=dict)
    targets: list[dict[str, Any]] = Field(default_factory=list)
    iteration: dict[str, Any] = Field(default_factory=dict)


class RuleValidateResponse(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
