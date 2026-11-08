"""workspaces 插件 Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from cndb.plugins.workspaces.models import (
    DEFAULT_STORAGE_QUOTA_BYTES,
    DEFAULT_WORKSPACE_MODULES,
    WorkspaceRole,
    WorkspaceVisibility,
)
from cndb.plugins.workspaces.modules import normalize_modules


class WorkspaceCreate(BaseModel):
    """创建工作区请求."""

    name: str
    description: str = ""
    visibility: WorkspaceVisibility = WorkspaceVisibility.MEMBER
    tags: list[str] = []
    allow_edit: bool = True
    modules: list[str] = DEFAULT_WORKSPACE_MODULES
    #: 选用模板创建（需求 0094）：模板存在时按模板 modules 与 spec 初始化
    template_id: int | None = None

    @field_validator("modules", mode="before")
    @classmethod
    def _normalize_modules(cls, v: Any) -> list[str]:
        """模块集合校验：非空、白名单、去重、固定顺序（ADR 0080 I1）."""
        return normalize_modules(v)


class WorkspaceUpdate(BaseModel):
    """更新工作区请求（部分字段）."""

    model_config = ConfigDict(from_attributes=True)
    name: str | None = None
    description: str | None = None
    visibility: WorkspaceVisibility | None = None
    tags: list[str] | None = None
    allow_edit: bool | None = None
    modules: list[str] | None = None

    @field_validator("modules", mode="before")
    @classmethod
    def _normalize_modules(cls, v: Any) -> list[str] | None:
        """None 表示不改；否则非空、白名单、去重、固定顺序（空集 / 非法值 422）."""
        if v is None:
            return None
        return normalize_modules(v)


class WorkspaceResponse(BaseModel):
    """工作区响应."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    visibility: WorkspaceVisibility
    tags: list[str]
    allow_edit: bool
    modules: list[str] = DEFAULT_WORKSPACE_MODULES
    # 存储配额（字节），默认 100MB；由系统管理员在管理台「空间分配」调整
    storage_quota_bytes: int = DEFAULT_STORAGE_QUOTA_BYTES
    # 工作区模板引用（需求 0094）：NULL = 自由工作区
    template_id: int | None = None
    template_version: int | None = None
    template_stage: str | None = None
    #: 项目上下文模式（ADR 0122）：workspace / project
    project_mode: str = "workspace"
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime


class WorkspaceWithPinnedResponse(WorkspaceResponse):
    """列表响应：附带当前用户的 pinned 状态、统计和在该工作区的角色."""

    pinned: bool = False
    table_count: int = 0
    member_count: int = 0
    # 文档 / 设计计数（需求 0093；展开详情页展示）
    document_count: int = 0
    design_count: int = 0
    current_user_role: WorkspaceRole | None = None


class WorkspaceDetailResponse(WorkspaceResponse):
    """工作区详情响应：附带拥有者信息、统计和当前用户角色."""

    model_config = ConfigDict(from_attributes=True)
    # 拥有者简要信息
    owner: dict[str, Any] | None = None
    # 统计信息
    table_count: int = 0
    member_count: int = 0
    view_count: int = 0
    total_rows: int = 0
    # 文档 / 设计计数（需求 0093）：文件夹与回收站内容不计入
    document_count: int = 0
    design_count: int = 0
    # 已用存储空间（字节）：附件 + 文档外存内容
    storage_bytes: int = 0
    # 当前请求用户在该工作区的角色（null 表示非成员）
    current_user_role: WorkspaceRole | None = None


# ── 贡献统计 schemas（需求 0126） ──────────────────────


class WorkspaceContributionItem(BaseModel):
    """单个用户的贡献统计行."""

    user_id: int
    username: str | None = None
    nickname: str | None = None
    # 当前工作区角色；None = 已移出工作区的曾为编辑者
    role: WorkspaceRole | None = None
    is_member: bool = False
    # 当前不是 owner / editor（含已移出）但存在直接写活动
    is_former_editor: bool = False
    rows_created: int = 0
    rows_updated: int = 0
    documents_created: int = 0
    documents_edited: int = 0
    designs_created: int = 0
    designs_edited: int = 0
    total: int = 0
    last_active_at: datetime | None = None


class WorkspaceContributionsResponse(BaseModel):
    """工作区贡献统计响应（全部时间，按合计降序）."""

    generated_at: datetime
    items: list[WorkspaceContributionItem] = []


# ── 成员 schemas ──────────────────────────────────────


class MemberAddRequest(BaseModel):
    """添加成员请求."""

    username: str
    role: WorkspaceRole


class MemberUpdateRequest(BaseModel):
    """修改成员角色请求."""

    role: WorkspaceRole


class WorkspaceOwnerTransferRequest(BaseModel):
    """转让工作区所有权请求."""

    user_id: int


class MemberUserBrief(BaseModel):
    """成员列表中的用户简要信息."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    nickname: str
    email: str | None = None


class WorkspaceMemberResponse(BaseModel):
    """成员响应."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    workspace_id: int
    user_id: int
    role: WorkspaceRole
    pinned: bool
    created_at: datetime
    user: MemberUserBrief


class PinRequest(BaseModel):
    """钉住切换请求."""

    workspace_id: int


class PinToggleResponse(BaseModel):
    """钉住切换响应."""

    pinned: bool


# ── 工作区级导入导出 schemas ─────────────────────────


class WorkspaceExportResponse(BaseModel):
    """工作区整体导出 JSON 响应."""

    version: str
    exported_at: datetime
    workspace: dict[str, Any]
    tables: list[dict[str, Any]]


class WorkspaceImportRequest(BaseModel):
    """工作区整体导入请求（JSON body 或 FormData 文件解析后的 JSON）."""

    json_data: dict[str, Any]


class WorkspaceImportResponse(BaseModel):
    """工作区整体导入响应."""

    imported_tables: int
    imported_rows: int
    imported_views: int
    imported_documents: int = 0
    """成功导入的文档数（仅最新正文；旧版备份无 documents 键时为 0）。"""
    imported_sync_jobs: int = 0
    """成功导入的外部数据同步任务数（v5 起；旧版备份无 sync_jobs 键时为 0）。"""
    imported_charts: int = 0
    """成功导入的文档图表实例数（v8 起；旧版备份无 charts 键时为 0）。"""
    imported_pipelines: int = 0
    """成功导入的流水线定义数（v10 起；旧版备份无 pipelines 键时为 0）。"""
    imported_designs: int = 0
    """成功导入的结构设计数（v11 起；旧版备份无 designs 键时为 0）。"""
    errors: list[str] = []
    """部分内容导入失败/跳过的明细（空列表表示全部成功）。"""


class WorkspaceArchiveTarget(BaseModel):
    """归档导入时可覆盖恢复的已有工作区（当前用户为 owner）."""

    id: int
    name: str
    role: WorkspaceRole = WorkspaceRole.OWNER


class WorkspaceArchiveInspectResponse(BaseModel):
    """归档导入前的预检信息（不落库）.

    前端据 ``existing_workspace`` 决定是否展示「覆盖恢复到已有工作区」入口：
    只有归档内工作区名与当前用户为 owner 的既有工作区同名时才返回该字段。
    """

    workspace_name: str
    backup_version: str
    created_at: datetime | None = None
    include_secrets: bool = True
    stats: dict[str, Any] = {}
    existing_workspace: WorkspaceArchiveTarget | None = None


class WorkspaceCreateFromBackup(BaseModel):
    """从备份 JSON 创建工作区请求."""

    name: str | None = None
    """新工作区名称，为空则使用备份文件中的 workspace.name."""

    json_data: dict[str, Any]
    """备份文件的完整 JSON 内容."""


class WorkspaceCreateFromBackupResponse(BaseModel):
    """从备份创建工作区响应."""

    workspace: WorkspaceResponse
    imported_tables: int
    imported_rows: int
    imported_views: int
    imported_documents: int = 0
    """成功导入的文档数（仅最新正文；旧版备份无 documents 键时为 0）。"""
    imported_sync_jobs: int = 0
    """成功导入的外部数据同步任务数（v5 起；旧版备份无 sync_jobs 键时为 0）。"""
    imported_charts: int = 0
    """成功导入的文档图表实例数（v8 起；旧版备份无 charts 键时为 0）。"""
    imported_pipelines: int = 0
    """成功导入的流水线定义数（v10 起；旧版备份无 pipelines 键时为 0）。"""
    errors: list[str] = []
    """部分内容导入失败/跳过的明细（空列表表示全部成功）。"""


# ── Role schemas ──────────────────────────────────────


class RoleCreate(BaseModel):
    """创建数据角色请求."""

    code: str
    name: str
    description: str = ""
    permissions: dict[str, bool] = {}

    @field_validator("permissions", mode="before")
    @classmethod
    def _strict_bool_perms(cls, v: Any) -> dict[str, bool]:
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("permissions 必须是对象")
        for key, val in v.items():
            if not isinstance(val, bool):
                raise ValueError(f"permissions.{key} 必须为 bool，实际为 {type(val).__name__}")
        return dict(v)


class RoleUpdate(BaseModel):
    """更新数据角色请求（部分字段）."""

    model_config = ConfigDict(from_attributes=True)
    name: str | None = None
    description: str | None = None
    permissions: dict[str, bool] | None = None

    @field_validator("permissions", mode="before")
    @classmethod
    def _strict_bool_perms(cls, v: Any) -> dict[str, bool] | None:
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("permissions 必须是对象")
        for key, val in v.items():
            if not isinstance(val, bool):
                raise ValueError(f"permissions.{key} 必须为 bool，实际为 {type(val).__name__}")
        return dict(v)


class RoleResponse(BaseModel):
    """数据角色响应."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    description: str
    permissions: dict[str, bool]
    is_builtin: bool
    created_at: datetime
    updated_at: datetime


__all__ = [
    "MemberAddRequest",
    "MemberUpdateRequest",
    "MemberUserBrief",
    "PinRequest",
    "PinToggleResponse",
    "RoleCreate",
    "RoleResponse",
    "RoleUpdate",
    "WorkspaceCreate",
    "WorkspaceCreateFromBackup",
    "WorkspaceCreateFromBackupResponse",
    "WorkspaceDetailResponse",
    "WorkspaceExportResponse",
    "WorkspaceImportRequest",
    "WorkspaceImportResponse",
    "WorkspaceMemberResponse",
    "WorkspaceOwnerTransferRequest",
    "WorkspaceResponse",
    "WorkspaceUpdate",
    "WorkspaceWithPinnedResponse",
]
