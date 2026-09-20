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


class TemplateCreate(BaseModel):
    """创建模板请求."""

    name: str = Field(..., max_length=255)
    description: str = ""
    output_format: str = "docx"
    template_content: str
    table_id: int | None = None
    parameters: list[ParameterDef] = Field(default_factory=list)
    # 持久化的额外引用表 ID 列表（服务端去重保序、剔除主表自身）
    extra_table_ids: list[int] = Field(default_factory=list)


class TemplateUpdate(BaseModel):
    """更新模板请求（全部可选）."""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    output_format: str | None = None
    template_content: str | None = None
    table_id: int | None = None
    parameters: list[ParameterDef] | None = None
    extra_table_ids: list[int] | None = None


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
    extra_table_ids: list[int]
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
    extra_table_ids: list[int]


class RenderRequest(BaseModel):
    """渲染报告请求."""

    table_id: int
    params: dict[str, Any] = Field(default_factory=dict)
    # 可选：主表行过滤（保持给定顺序，忽略不存在的 id；空/缺省=全部行）
    row_ids: list[int] | None = None
    # 可选：额外引用的数据表 ID 列表（显式传值优先，否则回落模板持久化的 extra_table_ids）
    extra_table_ids: list[int] = Field(default_factory=list)


__all__ = [
    "ParameterDef",
    "RenderRequest",
    "TemplateCreate",
    "TemplateListResponse",
    "TemplateResponse",
    "TemplateUpdate",
]
