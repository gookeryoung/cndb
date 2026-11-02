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


class ResumeRequest(BaseModel):
    """复核续跑：可带关键词 / 检索式（调整），也可全空（不调）。"""

    keywords: list[str] | None = Field(default=None, max_length=20, description="调整后的扩展词；空表示不改")
    query: str | None = Field(default=None, max_length=500, description="直接指定下一轮检索式；空表示用轮次记录")


class RuleValidateRequest(BaseModel):
    """规则片段校验（前端表单实时校验复用）。"""

    scope: dict[str, Any] = Field(default_factory=dict)
    filter_rule: dict[str, Any] = Field(default_factory=dict)
    targets: list[dict[str, Any]] = Field(default_factory=list)
    iteration: dict[str, Any] = Field(default_factory=dict)


class RuleValidateResponse(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)


# ── P3：渠道目录 / 规则草案 / 失败诊断 ────────────────


class ChannelOption(BaseModel):
    """渠道目录里的一条可选渠道."""

    value: str = Field(..., description="写进 scope.channels 的值（job:<id> 或 rss: / arxiv: 等简写）")
    label: str
    kind: str = Field(..., description="job / preset / provider")
    provider: str = ""
    requires_key: bool = False
    hint: str = ""


class ProviderOption(BaseModel):
    """已注册 provider 的元信息（前端按 params_schema 渲染内联声明表单）."""

    name: str
    label: str
    params_schema: dict[str, Any] = Field(default_factory=dict)
    supports_paging: bool = False


class ChannelCatalogResponse(BaseModel):
    """渠道目录：jobs（可引用）+ 简写 + provider + 语义辅助开关说明."""

    channels: list[ChannelOption] = Field(default_factory=list)
    providers: list[ProviderOption] = Field(default_factory=list)
    llm_actions: list[str] = Field(default_factory=list)


class RuleDraftRequest(BaseModel):
    """自然语言需求 → 规则草案（A 动作，只回草案不落策略）。"""

    description: str = Field(..., min_length=2, max_length=4000)
    table_id: int | None = Field(default=None, description="提示用：优先落这张表")
    parent_id: int | None = Field(default=None, description="提示用：优先落这个文档文件夹")


class RuleDraftResponse(BaseModel):
    """草案 + 模型元信息；``degraded`` 非空表示模型未参与（前端提示手填）."""

    draft: dict[str, Any]
    model: str = ""
    run_id: int | None = None
    degraded: str = ""
    error: str = ""


class DiagnoseResponse(BaseModel):
    """失败诊断（E 动作，只读）."""

    text: str
    model: str = ""
    run_id: int | None = None
    degraded: str = ""
