"""workspaces 插件 Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

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
    """列表响应：附带当前用户的 pinned 状态和统计."""

    pinned: bool = False
    table_count: int = 0
    member_count: int = 0


class WorkspaceDetailResponse(WorkspaceResponse):
    """工作区详情响应：附带拥有者信息和统计."""

    model_config = ConfigDict(from_attributes=True)
    # 拥有者简要信息
    owner: dict[str, Any] | None = None
    # 统计信息
    table_count: int = 0
    member_count: int = 0
    view_count: int = 0
    total_rows: int = 0


# ── 成员 schemas ──────────────────────────────────────


class MemberAddRequest(BaseModel):
    """添加成员请求."""

    username: str
    role: WorkspaceRole


class MemberUpdateRequest(BaseModel):
    """修改成员角色请求."""

    role: WorkspaceRole


class MemberUserBrief(BaseModel):
    """成员列表中的用户简要信息."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    nickname: str


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


__all__ = [
    "MemberAddRequest",
    "MemberUpdateRequest",
    "MemberUserBrief",
    "PinRequest",
    "PinToggleResponse",
    "WorkspaceCreate",
    "WorkspaceDetailResponse",
    "WorkspaceExportResponse",
    "WorkspaceImportRequest",
    "WorkspaceImportResponse",
    "WorkspaceMemberResponse",
    "WorkspaceResponse",
    "WorkspaceUpdate",
    "WorkspaceWithPinnedResponse",
]
