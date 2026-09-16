"""tables 插件 Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

# ── DataTable schemas ─────────────────────────────────


class TableCreate(BaseModel):
    """创建数据表 —— 可选同时从其他表引入字段.

    三种引入方式互斥（优先级从高到低）：
    - import_field_ids: 精确指定源字段 id 列表
    - import_field_names: 按字段名匹配（优先级最低）
    - import_all_fields: True 时引入源表全部字段
    """

    name: str
    description: str = ""
    # 从其他表引入字段（可选）
    import_from_table_id: int | None = None
    import_field_ids: list[int] | None = None
    import_field_names: list[str] | None = None
    import_all_fields: bool = False


class TableUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str | None = None
    description: str | None = None
    order: int | None = None
    trashed: bool | None = None


class TableOwnerBrief(BaseModel):
    """表级拥有者简要信息（仅 id + username，用于数据表列表/详情返回）."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str


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
    # 可选统计字段 —— list_tables / get_table 按需填充
    field_count: int | None = None
    record_count: int | None = None
    view_count: int | None = None
    # 表级拥有者（DataTable.owner_id 关联的用户；owner_id 为空时为 None）
    owner: TableOwnerBrief | None = None
    # 数据资产目录相关 —— 由 list_tables 聚合填充
    member_count: int | None = None
    my_access: str | None = None  # "owner" | "write" | "read" | "none"


class ViewBrief(BaseModel):
    """视图精简摘要（嵌入 TableDetailResponse 用）."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    view_type: str
    is_default: bool


class WorkspaceBrief(BaseModel):
    """表详情中嵌入的工作区精简摘要（避免前端再调一次 workspaceApi.get）."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    visibility: str = ""
    allow_edit: bool = True
    current_user_role: str | None = None


class OwnerBrief(BaseModel):
    """拥有者简要信息（对齐 WorkspaceDetailResponse.owner 的 dict 结构但保持类型安全）."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    nickname: str = ""


class TableDetailResponse(TableResponse):
    fields: list[FieldResponse] = []
    views: list[ViewBrief] = []
    # 当前用户在该表上可执行的动作（由 check_action 批量计算）
    current_user_actions: list[str] = []
    # 表所属工作区的 owner（从 WorkspaceMember + User 查出，注意：与继承自 TableResponse 的表级 owner 区分）
    workspace_owner: OwnerBrief | None = None
    # 所属工作区摘要
    workspace: WorkspaceBrief | None = None


# ── DataField schemas ────────────────────────────────


class FieldCreate(BaseModel):
    name: str
    field_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    required: bool = False
    is_unique: bool = False
    default_value: Any = None
    hidden: bool = False
    order: int = 0


class FieldUpdate(BaseModel):
    name: str | None = None
    field_type: str | None = None
    config: dict[str, Any] | None = None
    required: bool | None = None
    is_unique: bool | None = None
    default_value: Any = None
    hidden: bool | None = None
    order: int | None = None
    trashed: bool | None = None


# ── 字段从其他表引入 schemas ─────────────────────────


class FieldImportRequest(BaseModel):
    """从其他表引入字段到当前表的请求体.

    三种字段来源互斥（优先级从高到低）：
    - field_ids:          精确指定源字段 id 列表
    - field_names:         按源字段名列表
    - import_all_fields:   True 时引入源表全部字段

    field_mapping 支持源字段 → 目标字段重命名 / 跳过：
    ``{"源字段名": "目标字段名"}`` — 重命名
    ``{"源字段名": null}``       — 跳过该源字段
    未显式列出的源字段按 源名 == 目标名 自动处理.
    """

    source_table_id: int
    field_ids: list[int] | None = None
    field_names: list[str] | None = None
    import_all_fields: bool = False
    exclude_trashed: bool = True
    skip_conflicts: bool = False
    field_mapping: dict[str, str | None] | None = None
    # 预览模式：True 时只返回建议/缺口分析，不实际创建字段（前端先让用户确认映射再执行）
    preview_only: bool = False


class FieldImportResponse(BaseModel):
    """字段导入结果 —— 新建字段列表 + 跳过原因 + 可选的缺口分析/智能建议."""

    created: list[FieldResponse] = []
    skipped: list[str] = []
    total_source_count: int = 0
    # 总是返回 —— 前端用它渲染"参照对比"面板
    gap_analysis: dict[str, Any] | None = None
    # suggest_mapping 的建议列表，preview_only=True 时主要返回这个
    suggestions: list[dict[str, Any]] | None = None


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
    hidden: bool = False
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

    @computed_field
    @property
    def items(self) -> list[dict[str, Any]]:
        """前端兼容别名 — items == rows."""
        return self.rows


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


# ── TableMember / Owner Transfer schemas ───────────────


class MemberOut(BaseModel):
    """表成员详情 —— 列表响应."""

    model_config = ConfigDict(from_attributes=True)
    user_id: int
    username: str
    nickname: str = ""
    role: str  # "read" | "write"


class MemberCreate(BaseModel):
    """添加表成员."""

    user_id: int
    role: str = "read"


class MemberUpdate(BaseModel):
    """变更表成员角色（仅允许修改 role）."""

    role: str


class OwnerTransfer(BaseModel):
    """转让表所有权."""

    user_id: int


__all__ = [
    "BulkDeleteRequest",
    "FieldCreate",
    "FieldImportRequest",
    "FieldImportResponse",
    "FieldResponse",
    "FieldUpdate",
    "MemberCreate",
    "MemberOut",
    "MemberUpdate",
    "OwnerBrief",
    "OwnerTransfer",
    "PermissionCreate",
    "PermissionResponse",
    "PermissionUpdate",
    "RecordCreate",
    "RecordListRequest",
    "RecordListResponse",
    "RecordUpdate",
    "TableCreate",
    "TableDetailResponse",
    "TableOwnerBrief",
    "TableResponse",
    "TableUpdate",
    "ViewBrief",
    "ViewCreate",
    "ViewResponse",
    "ViewUpdate",
    "WorkspaceBrief",
]
