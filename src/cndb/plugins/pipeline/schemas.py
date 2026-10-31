"""pipeline 插件请求 / 响应模型（ADR 0076 D2 / D6）."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkflowCreate(BaseModel):
    """新建流水线定义（``name`` 缺省时取 DSL 的 ``name``）."""

    name: str | None = Field(default=None, max_length=120, description="定义名（缺省取 DSL name）")
    content: str = Field(min_length=1, description="YAML DSL 原文")
    enabled: bool = Field(default=True, description="是否启用（关闭后事件 / 定时触发不命中）")


class WorkflowUpdate(BaseModel):
    """更新流水线定义（None = 不改；``content`` 变更时重新编译）."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    content: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None


class RunSummary(BaseModel):
    """列表 / 详情页展示用的最近一次运行摘要."""

    id: int
    status: str
    trigger: str
    stats: dict[str, Any] = Field(default_factory=dict)
    created_at: Any = None


class WorkflowResponse(BaseModel):
    """流水线定义响应（含编译产物与最近一次运行）."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    name: str
    content: str
    compiled: dict[str, Any]
    enabled: bool
    created_by_id: int | None
    created_at: Any
    updated_at: Any
    last_run: RunSummary | None = None


class ValidateRequest(BaseModel):
    """纯编译校验请求（不落库）."""

    content: str = Field(min_length=1)
    name: str | None = Field(default=None, max_length=120)


class ValidateResponse(BaseModel):
    """纯编译校验结果（``ok=false`` 时 ``error`` 为中文错误信息）."""

    ok: bool
    error: str = ""
    name: str = ""
    job_count: int = 0
    step_count: int = 0


class CheckInputResponse(BaseModel):
    """检查动作输入项（目录端点）."""

    name: str
    type: str
    description: str = ""
    required: bool = False
    default: Any = None


class CheckSpecResponse(BaseModel):
    """检查动作目录项（``uses`` 供 DSL 插入辅助）."""

    uses: str
    title: str
    category: str
    severity: str
    target_types: list[str] = Field(default_factory=list)
    inputs: list[CheckInputResponse] = Field(default_factory=list)


class RunResponse(BaseModel):
    """运行详情响应（``stats.jobs`` 为 job / step 结论树）."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    workspace_id: int
    trigger: str
    trigger_payload: dict[str, Any]
    status: str
    stats: dict[str, Any]
    error_message: str
    created_at: Any
    updated_at: Any
    workflow_name: str = ""


class FindingResponse(BaseModel):
    """检查发现物响应."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    check: str
    severity: str
    target_type: str
    target_id: int | None
    locator: dict[str, Any]
    message: str
    detail: dict[str, Any]
    created_at: Any


class FindingListResponse(BaseModel):
    """发现物分页响应."""

    total: int
    items: list[FindingResponse] = Field(default_factory=list)


class RunListResponse(BaseModel):
    """运行历史分页响应."""

    total: int
    items: list[RunResponse] = Field(default_factory=list)
