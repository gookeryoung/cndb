"""工作区模板 / 生命周期 Pydantic schemas（需求 0094）."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cndb.plugins.workspaces.models import DEFAULT_WORKSPACE_MODULES
from cndb.plugins.workspaces.modules import normalize_modules


class TemplateCreate(BaseModel):
    """创建模板：``spec`` 由路由层统一校验与归一化."""

    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    category: str = Field(default="", max_length=64)
    modules: list[str] = DEFAULT_WORKSPACE_MODULES
    spec: dict[str, Any]
    change_summary: str = Field(default="初始版本", max_length=500)

    @field_validator("modules", mode="before")
    @classmethod
    def _normalize_modules(cls, v: Any) -> list[str]:
        return normalize_modules(v)


class TemplateUpdate(BaseModel):
    """更新模板：``spec`` 变化时先算 diff / 影响，必要时要求 ``force``."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    category: str | None = Field(default=None, max_length=64)
    modules: list[str] | None = None
    spec: dict[str, Any] | None = None
    change_summary: str = Field(default="", max_length=500)
    force: bool = False

    @field_validator("modules", mode="before")
    @classmethod
    def _normalize_modules(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        return normalize_modules(v)


class TemplatePreviewRequest(BaseModel):
    """预览请求：传入拟保存的 spec（不落库）."""

    spec: dict[str, Any]


class TemplateRevisionResponse(BaseModel):
    """历史版本快照."""

    model_config = ConfigDict(from_attributes=True)
    version: int
    change_summary: str
    spec: dict[str, Any]
    created_at: datetime


class TemplateResponse(BaseModel):
    """模板列表 / 详情响应."""

    id: int
    name: str
    description: str
    category: str
    modules: list[str]
    spec: dict[str, Any]
    version: int
    is_builtin: bool
    created_by_id: int | None
    updated_at: datetime
    counts: dict[str, int] = Field(default_factory=dict)
    workspace_count: int = 0


class TemplateUpdateResponse(BaseModel):
    """模板更新结果：模板本体 + diff / 影响 / 本次增量同步统计."""

    template: TemplateResponse
    diff: dict[str, Any]
    impact: dict[str, Any]
    requires_force: bool
    applied: bool
    sync: dict[str, int] = Field(default_factory=dict)


class TemplatePreviewResponse(BaseModel):
    """预览结果（diff + 影响），保存前必看."""

    diff: dict[str, Any]
    impact: dict[str, Any]
    requires_force: bool
    spec: dict[str, Any]


class ApplyTemplateRequest(BaseModel):
    """把模板应用到已存在工作区（增量、非破坏）."""

    template_id: int
    force: bool = False


class ApplyTemplateResponse(BaseModel):
    """应用结果：同步计数 + 更新后的模板引用."""

    workspace_id: int
    template_id: int
    template_version: int
    template_stage: str | None
    sync: dict[str, int]


class AdvanceStageRequest(BaseModel):
    """推进生命周期阶段."""

    target_stage: str | None = None
    force: bool = False
    reason: str = Field(default="", max_length=500)


class LifecycleResponse(BaseModel):
    """生命周期状态（逐阶段门禁明细 + 履历）."""

    template_id: int
    template_name: str
    template_version: int
    current_version: int
    current_stage: str | None
    current_stage_index: int
    stage_count: int
    can_advance: bool
    next_stage: dict[str, Any] | None = None
    stages: list[dict[str, Any]] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)
    version_mismatch: bool = False


__all__ = [
    "AdvanceStageRequest",
    "ApplyTemplateRequest",
    "ApplyTemplateResponse",
    "LifecycleResponse",
    "TemplateCreate",
    "TemplatePreviewRequest",
    "TemplatePreviewResponse",
    "TemplateResponse",
    "TemplateRevisionResponse",
    "TemplateUpdate",
    "TemplateUpdateResponse",
]
