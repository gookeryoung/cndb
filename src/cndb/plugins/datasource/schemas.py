"""datasource API 数据结构（Pydantic v2）."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field


class ProviderInfo(BaseModel):
    """可用数据源适配器（前端据此渲染动态表单）."""

    name: str
    label: str
    params_schema: dict[str, Any] = Field(default_factory=dict)
    default_cursor: str = "date"
    supports_paging: bool = False


class ProviderListResponse(BaseModel):
    providers: list[ProviderInfo]


class SyncJobCreate(BaseModel):
    """新建同步任务.

    ``request_spec`` / ``cursor`` / ``schedule`` 的结构见 ADR 0006；
    服务端在创建时逐项校验（URL 模板、游标策略、调度表达式），不合法直接 400。
    """

    name: str = Field(..., min_length=1, max_length=128)
    provider: str = Field(default="http_json")
    table_id: int | None = Field(default=None, description="目标表；留空表示暂不落表")
    request_spec: dict[str, Any] = Field(..., description="请求模板与分页 / 时间窗口声明")
    parser: str = Field(default="json")
    entrant_param: str | None = Field(default=None, description="标的占位符名，如 city / symbol")
    entrant_keys: list[str] = Field(default_factory=list)
    match_keys: list[str] = Field(default_factory=list, description="幂等键（目标字段名）")
    field_mapping: dict[str, Any] = Field(default_factory=dict)
    cursor: dict[str, Any] = Field(default_factory=dict)
    schedule: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    session_id: int | None = Field(default=None, description="凭证会话（请求头 + 密钥）")
    rate_limit_ms: int = Field(default=0, ge=0, le=60_000, description="同一任务内相邻请求最小间隔（毫秒）")
    run_immediately: bool = Field(default=False, description="创建后立刻跑一次（同步执行）")


class SyncJobUpdate(BaseModel):
    """局部更新：未提供的字段保持不变."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    provider: str | None = None
    table_id: int | None = None
    request_spec: dict[str, Any] | None = None
    parser: str | None = None
    entrant_param: str | None = None
    entrant_keys: list[str] | None = None
    match_keys: list[str] | None = None
    field_mapping: dict[str, Any] | None = None
    cursor: dict[str, Any] | None = None
    schedule: dict[str, Any] | None = None
    enabled: bool | None = None
    session_id: int | None = None
    rate_limit_ms: int | None = Field(default=None, ge=0, le=60_000)


class SyncJobOut(BaseModel):
    id: int
    workspace_id: int
    name: str
    provider: str
    table_id: int | None
    request_spec: dict[str, Any]
    parser: str
    entrant_param: str | None
    entrant_keys: list[str]
    match_keys: list[str]
    field_mapping: dict[str, Any]
    cursor: dict[str, Any]
    schedule: dict[str, Any]
    enabled: bool
    last_run_at: dt.datetime | None
    last_status: str
    session_id: int | None = None
    rate_limit_ms: int = 0
    created_at: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def from_model(cls, job: Any) -> SyncJobOut:
        return cls(
            id=job.id,
            workspace_id=job.workspace_id,
            name=job.name,
            provider=job.provider,
            table_id=job.table_id,
            request_spec=job.request_spec or {},
            parser=job.parser,
            entrant_param=job.entrant_param,
            entrant_keys=job.entrant_keys or [],
            match_keys=job.match_keys or [],
            field_mapping=job.field_mapping or {},
            cursor=job.cursor or {},
            schedule=job.schedule or {},
            enabled=job.enabled,
            last_run_at=job.last_run_at,
            last_status=job.last_status,
            session_id=job.session_id,
            rate_limit_ms=int(job.rate_limit_ms or 0),
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class SyncJobListResponse(BaseModel):
    total: int
    jobs: list[SyncJobOut]


class SyncRunOut(BaseModel):
    id: int
    job_id: int
    status: str
    trigger: str
    started_at: dt.datetime
    finished_at: dt.datetime | None
    duration_ms: int
    cursor_from: str
    cursor_to: str
    fetched: int
    inserted: int
    updated: int
    skipped: int
    error_message: str
    detail: dict[str, Any]

    @classmethod
    def from_model(cls, run: Any) -> SyncRunOut:
        return cls(
            id=run.id,
            job_id=run.job_id,
            status=run.status,
            trigger=run.trigger,
            started_at=run.started_at,
            finished_at=run.finished_at,
            duration_ms=run.duration_ms,
            cursor_from=run.cursor_from,
            cursor_to=run.cursor_to,
            fetched=run.fetched,
            inserted=run.inserted,
            updated=run.updated,
            skipped=run.skipped,
            error_message=run.error_message,
            detail=run.detail or {},
        )


class SyncRunListResponse(BaseModel):
    total: int
    runs: list[SyncRunOut]


class RunResponse(BaseModel):
    """手动运行结果：run 明细 + 最新 job 状态."""

    job: SyncJobOut
    run: SyncRunOut


class SessionCreate(BaseModel):
    """新建凭证会话：请求头 + 密钥（密钥只写不回显）."""

    name: str = Field(..., min_length=1, max_length=128)
    headers: dict[str, str] = Field(default_factory=dict, description="非敏感请求头")
    secrets: dict[str, str] = Field(default_factory=dict, description="密钥字典，运行期作为模板变量注入")


class SessionUpdate(BaseModel):
    """局部更新；``secrets`` 一旦提供即整体替换."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    headers: dict[str, str] | None = None
    secrets: dict[str, str] | None = None


class SessionOut(BaseModel):
    """会话详情：**不返回密钥值**，只给键名（前端做「已配置」标记）."""

    id: int
    workspace_id: int
    name: str
    headers: dict[str, str]
    secret_keys: list[str] = Field(default_factory=list)
    created_at: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def from_model(cls, session: Any) -> SessionOut:
        return cls(
            id=session.id,
            workspace_id=session.workspace_id,
            name=session.name,
            headers=dict(session.headers or {}),
            secret_keys=sorted((session.secrets or {}).keys()),
            created_at=session.created_at,
            updated_at=session.updated_at,
        )


class SessionListResponse(BaseModel):
    total: int
    sessions: list[SessionOut]


class DomainTemplate(BaseModel):
    """领域模板包：按 provider 预置的一套分析配置（公式 / 图表 / 汇总）."""

    id: str
    provider: str
    name: str
    description: str
    reason: str = ""
    formulas: list[dict[str, Any]] = Field(default_factory=list)
    chart: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None


class DomainTemplateListResponse(BaseModel):
    templates: list[DomainTemplate]


class PreviewRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=500, description="返回行数上限")


class PreviewResponse(BaseModel):
    status: str
    total: int
    columns: list[str] = Field(default_factory=list)
    plans: int = 0
    succeeded: int = 0
    cursor_from: str = ""
    cursor_to: str = ""
    rows: list[dict[str, Any]] = Field(default_factory=list)
    failures: list[dict[str, Any]] = Field(default_factory=list)
    normalize_failures: list[dict[str, Any]] = Field(default_factory=list)
    # 预览时自动识别的幂等键（ADR 0019）；空列表表示未识别出唯一键
    suggested_match_keys: list[str] = Field(default_factory=list)


__all__ = [
    "DomainTemplate",
    "DomainTemplateListResponse",
    "PreviewRequest",
    "PreviewResponse",
    "ProviderInfo",
    "ProviderListResponse",
    "RunResponse",
    "SessionCreate",
    "SessionListResponse",
    "SessionOut",
    "SessionUpdate",
    "SyncJobCreate",
    "SyncJobListResponse",
    "SyncJobOut",
    "SyncJobUpdate",
    "SyncRunListResponse",
    "SyncRunOut",
]
