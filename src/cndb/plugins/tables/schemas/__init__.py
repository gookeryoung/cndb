"""tables 插件 Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── DataTable schemas ─────────────────────────────────


class TableCreate(BaseModel):
    name: str
    description: str = ""


class TableUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str | None = None
    description: str | None = None
    order: int | None = None
    trashed: bool | None = None


class TableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workspace_id: int
    name: str
    db_table_name: str
    description: str = ""
    order: int
    trashed: bool
    trashed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TableDetailResponse(TableResponse):
    fields: list[FieldResponse] = []


# ── DataField schemas ────────────────────────────────


class FieldCreate(BaseModel):
    name: str
    field_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    required: bool = False
    is_unique: bool = False
    default_value: Any = None
    order: int = 0


class FieldUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    required: bool | None = None
    is_unique: bool | None = None
    default_value: Any = None
    order: int | None = None
    trashed: bool | None = None


class FieldResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    table_id: int
    name: str
    field_type: str
    db_column_name: str
    config: dict[str, Any]
    required: bool
    is_unique: bool
    default_value: Any = None
    order: int
    trashed: bool
    trashed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ── Record schemas ───────────────────────────────────


class RecordCreate(BaseModel):
    values: dict[str, Any]


class RecordUpdate(BaseModel):
    values: dict[str, Any]


class RecordListRequest(BaseModel):
    filters: list[dict[str, Any]] = Field(default_factory=list)
    filter_logic: str = "AND"
    sorts: list[dict[str, str]] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=10000)
    offset: int = Field(default=0, ge=0)


class RecordListResponse(BaseModel):
    rows: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class BulkDeleteRequest(BaseModel):
    row_ids: list[int]


# ── DataView schemas ──────────────────────────────────


class ViewCreate(BaseModel):
    name: str
    view_type: str = "grid"
    filter_type: str = "AND"
    filters: list[dict[str, Any]] = Field(default_factory=list)
    sortings: list[dict[str, str]] = Field(default_factory=list)
    field_options: dict[str, Any] = Field(default_factory=dict)
    field_order: list[str] = Field(default_factory=list)
    view_options: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    order: int = 0


class ViewUpdate(BaseModel):
    name: str | None = None
    view_type: str | None = None
    filter_type: str | None = None
    filters: list[dict[str, Any]] | None = None
    sortings: list[dict[str, str]] | None = None
    field_options: dict[str, Any] | None = None
    field_order: list[str] | None = None
    view_options: dict[str, Any] | None = None
    is_default: bool | None = None
    order: int | None = None


class ViewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    table_id: int
    owner_id: int | None = None
    name: str
    view_type: str
    filter_type: str
    filters: list[dict[str, Any]]
    sortings: list[dict[str, str]]
    field_options: dict[str, Any]
    field_order: list[str]
    view_options: dict[str, Any]
    is_default: bool
    order: int
    created_at: datetime
    updated_at: datetime


TableDetailResponse.model_rebuild()


# ── TablePermission schemas ──────────────────────────


class PermissionCreate(BaseModel):
    read_role: str = ""
    edit_records_role: str = ""
    edit_views_role: str = ""
    edit_schema_role: str = ""
    comment_role: str = ""
    hidden_fields: dict[str, Any] = Field(default_factory=dict)
    row_filters: list[dict[str, Any]] = Field(default_factory=list)
    row_filter_type: str = "AND"


class PermissionUpdate(BaseModel):
    read_role: str | None = None
    edit_records_role: str | None = None
    edit_views_role: str | None = None
    edit_schema_role: str | None = None
    comment_role: str | None = None
    hidden_fields: dict[str, Any] | None = None
    row_filters: list[dict[str, Any]] | None = None
    row_filter_type: str | None = None


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    table_id: int
    read_role: str
    edit_records_role: str
    edit_views_role: str
    edit_schema_role: str
    comment_role: str
    hidden_fields: dict[str, Any]
    row_filters: list[dict[str, Any]]
    row_filter_type: str
    created_at: datetime
    updated_at: datetime


__all__ = [
    "BulkDeleteRequest",
    "FieldCreate",
    "FieldResponse",
    "FieldUpdate",
    "PermissionCreate",
    "PermissionResponse",
    "PermissionUpdate",
    "RecordCreate",
    "RecordListRequest",
    "RecordListResponse",
    "RecordUpdate",
    "TableCreate",
    "TableDetailResponse",
    "TableResponse",
    "TableUpdate",
    "ViewCreate",
    "ViewResponse",
    "ViewUpdate",
]
