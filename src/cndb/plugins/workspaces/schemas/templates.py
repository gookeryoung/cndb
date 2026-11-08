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


class TemplateValidateResponse(BaseModel):
    """无状态规格预检结果（需求 0121）：归一化 spec + 规模，不落库."""

    spec: dict[str, Any]
    counts: dict[str, int] = Field(default_factory=dict)


class TemplateImportPayload(BaseModel):
    """导入文件载荷（需求 0120）: ``.workspace-template.json`` 的完整内容."""

    format: str = "cndb.workspace-template"
    schema_version: int = 1
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    category: str = Field(default="", max_length=64)
    modules: list[str] = DEFAULT_WORKSPACE_MODULES
    spec: dict[str, Any]
    version: int | None = Field(default=None, ge=1)

    @field_validator("modules", mode="before")
    @classmethod
    def _normalize_modules(cls, v: Any) -> list[str]:
        return normalize_modules(v)


class TemplateImportPreviewResponse(BaseModel):
    """导入预览：归一化后的 spec、建议名称与规模统计（不落库）."""

    name: str
    description: str
    category: str
    modules: list[str]
    spec: dict[str, Any]
    counts: dict[str, int] = Field(default_factory=dict)
    source_version: int | None = None
    renamed: bool = False


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
    #: 项目模式下必填（单项目可由前端自动带出）
    project_id: int | None = None


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
    project_id: int | None = None
    project_mode: str = "workspace"


__all__ = [
    "AdvanceStageRequest",
    "ApplyTemplateRequest",
    "ApplyTemplateResponse",
    "LifecycleResponse",
    "TemplateCreate",
    "TemplateImportPayload",
    "TemplateImportPreviewResponse",
    "TemplatePreviewRequest",
    "TemplatePreviewResponse",
    "TemplateResponse",
    "TemplateRevisionResponse",
    "TemplateUpdate",
    "TemplateUpdateResponse",
]


# ── 数据流程（需求 0095）────────────────────────────


class DataFlowField(BaseModel):
    """数据流程表单字段（由模板 spec 归一化后的字段定义）."""

    name: str
    field_type: str
    required: bool = False
    config: dict[str, Any] = Field(default_factory=dict)
    order: int = 0
    hidden: bool = False
    default_value: Any = None


class DataFlowForm(BaseModel):
    """数据流程中的一个表单（映射到工作区数据表）与可配置交互."""

    key: str
    name: str
    description: str = ""
    #: project：按项目行统计；workspace：工作区级共享（不参与项目门禁）
    scope: str = "workspace"
    #: 项目级表单的关联字段名（前端按项目过滤行 / 新建时默认带出）
    project_link_field: str | None = None
    table_id: int | None = None
    table_name: str | None = None
    flow: dict[str, Any]
    fields: list[DataFlowField] = Field(default_factory=list)
    record_count: int = 0
    can_create: bool = False
    can_edit: bool = False
    can_delete: bool = False


class DataFlowStage(BaseModel):
    """数据流程阶段（流程驱动的主要视觉分组）."""

    key: str
    name: str
    description: str = ""
    order: int = 0
    is_current: bool = False
    is_completed: bool = False
    gate_satisfied: bool = False
    forms: list[DataFlowForm] = Field(default_factory=list)


class DataFlowStep(BaseModel):
    """端到端流程的一步：可绑定表单（CRUD）/ 文档规则，或仅为审批 / 确认节点."""

    key: str
    name: str
    description: str = ""
    form: DataFlowForm | None = None
    documents: list[str] = Field(default_factory=list)


class DataFlowFlow(BaseModel):
    """一条端到端业务流程（多流程并列显示）."""

    key: str
    name: str
    description: str = ""
    stage: str | None = None
    stage_name: str | None = None
    steps: list[DataFlowStep] = Field(default_factory=list)
    form_count: int = 0
    step_count: int = 0
    record_count: int = 0


class DataFlowResponse(BaseModel):
    """工作区数据流程：模板 → 流程 / 阶段 → 表单 → 可配置增删查改."""

    template_id: int
    template_name: str
    template_version: int
    current_version: int
    current_stage: str | None = None
    current_stage_index: int = 0
    can_advance: bool = False
    next_stage: dict[str, Any] | None = None
    stages: list[DataFlowStage] = Field(default_factory=list)
    #: 端到端流程（显式配置优先；旧模板由阶段派生，保证前端始终可多流程展示）
    flows: list[DataFlowFlow] = Field(default_factory=list)
    project_id: int | None = None
    project_mode: str = "workspace"


__all__ = [
    "AdvanceStageRequest",
    "ApplyTemplateRequest",
    "ApplyTemplateResponse",
    "DataFlowField",
    "DataFlowFlow",
    "DataFlowForm",
    "DataFlowResponse",
    "DataFlowStage",
    "DataFlowStep",
    "LifecycleResponse",
    "TemplateCreate",
    "TemplateImportPayload",
    "TemplateImportPreviewResponse",
    "TemplatePreviewRequest",
    "TemplatePreviewResponse",
    "TemplateResponse",
    "TemplateRevisionResponse",
    "TemplateUpdate",
    "TemplateUpdateResponse",
]
