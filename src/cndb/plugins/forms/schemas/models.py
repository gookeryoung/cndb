"""forms 插件 schemas：表单定义 CRUD + 运行器提交."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FormFieldConfig(BaseModel):
    """单字段的表单配置."""

    field_name: str
    editable: bool = True
    visible: bool = True
    required: bool = False


class FormCreate(BaseModel):
    """创建表单定义请求."""

    table_id: int
    name: str = Field(..., max_length=255)
    description: str = ""
    field_config: list[FormFieldConfig] = Field(default_factory=list)
    use_role: str = ""
    edit_role: str = ""
    delete_role: str = ""
    approval_workflow_id: int | None = None


class FormUpdate(BaseModel):
    """更新表单定义请求（全部可选）."""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    field_config: list[FormFieldConfig] | None = None
    use_role: str | None = None
    edit_role: str | None = None
    delete_role: str | None = None
    approval_workflow_id: int | None = None


class FormResponse(BaseModel):
    """表单定义完整响应."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    table_id: int
    name: str
    description: str
    field_config: list[dict[str, Any]]
    layout: dict[str, Any]
    use_role: str
    edit_role: str
    delete_role: str
    order: int
    trashed: bool
    approval_workflow_id: int | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class FormListResponse(BaseModel):
    """表单列表精简响应."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    table_id: int
    name: str
    description: str
    field_config: list[dict[str, Any]]
    use_role: str
    edit_role: str
    delete_role: str


class FormSubmitRequest(BaseModel):
    """表单运行器提交请求：字段名 → 值."""

    values: dict[str, Any]


class FormSubmitResponse(BaseModel):
    """表单运行器提交响应."""

    record_id: int
    message: str = "提交成功"


__all__ = [
    "FormCreate",
    "FormFieldConfig",
    "FormListResponse",
    "FormResponse",
    "FormSubmitRequest",
    "FormSubmitResponse",
    "FormUpdate",
]
