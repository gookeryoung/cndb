"""workspaces 插件 Pydantic schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from cndb.plugins.workspaces.models import WorkspaceRole


class WorkspaceCreate(BaseModel):
    """创建工作区请求."""

    name: str
    description: str = ""


class WorkspaceUpdate(BaseModel):
    """更新工作区请求（部分字段）."""

    model_config = ConfigDict(from_attributes=True)
    name: str | None = None
    description: str | None = None


class WorkspaceResponse(BaseModel):
    """工作区响应."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime


class WorkspaceWithPinnedResponse(WorkspaceResponse):
    """列表响应：附带当前用户的 pinned 状态."""

    pinned: bool = False


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


__all__ = [
    "MemberAddRequest",
    "MemberUpdateRequest",
    "MemberUserBrief",
    "PinRequest",
    "PinToggleResponse",
    "WorkspaceCreate",
    "WorkspaceMemberResponse",
    "WorkspaceResponse",
    "WorkspaceUpdate",
    "WorkspaceWithPinnedResponse",
]
