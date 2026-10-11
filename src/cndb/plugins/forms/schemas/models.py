"""forms 插件 Pydantic v2 schemas."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cndb.plugins.workspaces.models import WorkspaceRole

# 表单权限阈值合法取值：空串（未配置）或工作区角色名
_ROLE_VALUES = {r.value for r in WorkspaceRole}


def _validate_role_threshold(v: str) -> str:
    """校验阈值列：空串 = 未配置回退表级；非空必须是合法工作区角色名."""
    if v and v not in _ROLE_VALUES:
        raise ValueError(f"角色阈值非法: {v}，合法值 {_ROLE_VALUES} 或空串")
    return v


class FormFieldConfig(BaseModel):
    """表单内单个字段的展示与编辑配置."""

    field_name: str
    label: str | None = None
    # None = 跟随字段定义（DataField.required）
    required: bool | None = None
    # False = 表单编辑态只读（新建时仍可写入默认值）
    editable: bool = True
    visible: bool = True
    default_value: Any = None
    help_text: str | None = None


class FormCreate(BaseModel):
    """创建表单定义."""

    table_id: int
    name: str
    description: str = ""
    field_config: list[FormFieldConfig] = Field(default_factory=list)
    layout: dict[str, Any] = Field(default_factory=dict)
    use_role: str = ""
    edit_role: str = ""
    delete_role: str = ""
    order: int = 0

    @field_validator("use_role", "edit_role", "delete_role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        return _validate_role_threshold(v)


class FormUpdate(BaseModel):
    """更新表单定义（PATCH 语义，未传字段不更新）."""

    name: str | None = None
    description: str | None = None
    field_config: list[FormFieldConfig] | None = None
    layout: dict[str, Any] | None = None
    use_role: str | None = None
    edit_role: str | None = None
    delete_role: str | None = None
    order: int | None = None

    @field_validator("use_role", "edit_role", "delete_role")
    @classmethod
    def _check_role(cls, v: str | None) -> str | None:
        return None if v is None else _validate_role_threshold(v)


class FormResponse(BaseModel):
    """表单定义详情响应."""

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
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class FormListItemResponse(BaseModel):
    """表单列表项（附所属表名，便于工作区级聚合展示）."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    table_id: int
    table_name: str
    name: str
    description: str
    use_role: str
    edit_role: str
    delete_role: str
    order: int
    updated_at: dt.datetime | None = None


class FormValuesUpdate(BaseModel):
    """表单行写入载荷（新建/编辑共用，键为字段名）."""

    values: dict[str, Any] = Field(default_factory=dict)


class FormMetaResponse(BaseModel):
    """表单运行时元数据：解析后字段 + 当前用户操作位."""

    id: int
    table_id: int
    table_name: str
    name: str
    description: str
    layout: dict[str, Any]
    # 运行时解析后的字段配置（已过滤 trashed / 表级隐藏字段）
    fields: list[dict[str, Any]]
    # 配置中引用但已失效（软删/隐藏）的字段名清单
    invalid_fields: list[str]
    can_submit: bool
    can_edit: bool
    can_delete: bool


__all__ = [
    "FormCreate",
    "FormFieldConfig",
    "FormListItemResponse",
    "FormMetaResponse",
    "FormResponse",
    "FormUpdate",
    "FormValuesUpdate",
]
