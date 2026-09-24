"""workspaces 插件 Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from cndb.plugins.workspaces.models import WorkspaceRole, WorkspaceVisibility


class WorkspaceCreate(BaseModel):
    """创建工作区请求."""

    name: str
    description: str = ""
    visibility: WorkspaceVisibility = WorkspaceVisibility.MEMBER
    tags: list[str] = []
    allow_edit: bool = True


class WorkspaceUpdate(BaseModel):
    """更新工作区请求（部分字段）."""

    model_config = ConfigDict(from_attributes=True)
    name: str | None = None
    description: str | None = None
    visibility: WorkspaceVisibility | None = None
    tags: list[str] | None = None
    allow_edit: bool | None = None


class WorkspaceResponse(BaseModel):
    """工作区响应."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    visibility: WorkspaceVisibility
    tags: list[str]
    allow_edit: bool
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime


class WorkspaceWithPinnedResponse(WorkspaceResponse):
    """列表响应：附带当前用户的 pinned 状态、统计和在该工作区的角色."""

    pinned: bool = False
    table_count: int = 0
    member_count: int = 0
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
    # 当前请求用户在该工作区的角色（null 表示非成员）
    current_user_role: WorkspaceRole | None = None


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
    errors: list[str] = []
    """部分内容导入失败/跳过的明细（空列表表示全部成功）。"""


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
