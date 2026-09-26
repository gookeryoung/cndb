"""reports 插件 Pydantic schemas（业务实现模块）."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ParameterDef(BaseModel):
    """模板参数定义."""

    name: str
    type: str = "string"  # string / number / date / boolean
    default: Any = None
    required: bool = False
    label: str = ""
    # 可选值列表（如 ["在职", "离职", "全部"]）：非空时前端渲染下拉菜单，渲染时校验取值
    options: list[str] = Field(default_factory=list)


class TemplateCreate(BaseModel):
    """创建模板请求."""

    name: str = Field(..., max_length=255)
    description: str = ""
    output_format: str = "docx"
    template_content: str
    table_id: int | None = None
    parameters: list[ParameterDef] = Field(default_factory=list)
    # 额外引用表（可跨工作区，渲染时注入 records_by_table）
    extra_table_ids: list[int] = Field(default_factory=list)
    # 主题风格（business/minimal/modern/engineering/academic）
    theme: str = "minimal"


class TemplateUpdate(BaseModel):
    """更新模板请求（全部可选）."""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    output_format: str | None = None
    template_content: str | None = None
    table_id: int | None = None
    parameters: list[ParameterDef] | None = None
    extra_table_ids: list[int] | None = None
    theme: str | None = None


class TemplateResponse(BaseModel):
    """模板响应."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    table_id: int | None = None
    name: str
    description: str
    output_format: str
    template_content: str
    parameters: list[dict[str, Any]]
    extra_table_ids: list[int] = Field(default_factory=list)
    theme: str = "minimal"
    created_at: dt.datetime
    updated_at: dt.datetime


class TemplateListResponse(BaseModel):
    """模板列表响应（精简）."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    table_id: int | None = None
    name: str
    description: str
    output_format: str
    parameters: list[dict[str, Any]]
    extra_table_ids: list[int] = Field(default_factory=list)
    theme: str = "minimal"


class RenderRequest(BaseModel):
    """渲染报告请求."""

    table_id: int
    params: dict[str, Any] = Field(default_factory=dict)
    # 可选：过滤行（空=全部）
    row_ids: list[int] | None = None
    # 可选：临时追加的额外引用表 ID 列表，渲染时与模板持久化的 extra_table_ids 合并去重后注入 records_by_table
    extra_table_ids: list[int] = Field(default_factory=list)


__all__ = [
    "ParameterDef",
    "RenderRequest",
    "TemplateCreate",
    "TemplateListResponse",
    "TemplateResponse",
    "TemplateUpdate",
]
