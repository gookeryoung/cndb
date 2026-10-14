"""documents 插件 Pydantic schemas：请求/响应 DTO."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── 文档 ──


class DocumentCreate(BaseModel):
    """创建文档（或文件夹）."""

    title: str = Field(min_length=1, max_length=500)
    parent_id: int | None = None
    content: str = ""  # markdown 原文；创建文件夹时忽略
    is_folder: bool = False
    status: str = Field(default="draft", pattern="^(draft|published|archived)$")
    tag_ids: list[int] = Field(default_factory=list)
    sort_order: int = 0


class DocumentUpdate(BaseModel):
    """更新文档元数据（不含内容；内容走 PUT content）."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    parent_id: int | None = None
    status: str | None = Field(default=None, pattern="^(draft|published|archived)$")
    sort_order: int | None = None
    tag_ids: list[int] | None = None  # None=不变；[] = 清空


class ContentUpdate(BaseModel):
    """更新文档内容（乐观锁：客户端回传读取时的 updated_at）."""

    content: str
    change_summary: str = Field(default="", max_length=500)
    # 乐观锁版本戳：客户端上次读取/保存时拿到的 updated_at ISO 字符串
    base_updated_at: str | None = None


class DocumentOut(BaseModel):
    """文档列表项 / 详情（不含内容正文）."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    parent_id: int | None
    title: str
    slug: str | None
    content_type: str
    author: str
    summary: str
    toc_json: list[dict[str, Any]]
    status: str
    is_folder: bool
    sort_order: int
    content_size: int
    created_at: dt.datetime
    updated_at: dt.datetime
    created_by_id: int | None
    updated_by_id: int | None
    tag_ids: list[int] = Field(default_factory=list)
    version_count: int = 0


class DocumentDetail(DocumentOut):
    """文档详情：附带最新版本内容."""

    content: str = ""


# ── 版本 ──


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version_number: int
    content_size: int
    content_hash: str | None
    change_summary: str
    change_type: str
    created_at: dt.datetime
    created_by_id: int | None


class VersionDetail(VersionOut):
    """版本详情：附带内容."""

    content: str


class DiffResponse(BaseModel):
    """两版本差异（unified diff 文本）."""

    document_id: int
    base_version: int
    head_version: int
    diff: str
    added: int = 0
    removed: int = 0


class RollbackRequest(BaseModel):
    target_version: int


class DailyNoteRequest(BaseModel):
    """每日笔记：date 缺省为服务器当天。"""

    date: dt.date | None = None


# ── 标签 ──


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(default="#1890FF", pattern="^#[0-9A-Fa-f]{6}$")
    description: str = ""


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, pattern="^#[0-9A-Fa-f]{6}$")
    description: str | None = None


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    name: str
    color: str
    description: str
    doc_count: int


class TagIdsRequest(BaseModel):
    tag_ids: list[int] = Field(default_factory=list)


# ── 链接修复 ──


class LinkRepairItem(BaseModel):
    """单条断链修复：把正文中的 ``[[title]]`` 改指为 ``target_document_id``."""

    title: str = Field(min_length=1, max_length=500)
    target_document_id: int


class LinkRepairRequest(BaseModel):
    """断链修复请求（一次可修多条；全部未命中时返回 409）."""

    repairs: list[LinkRepairItem] = Field(min_length=1, max_length=100)


# ── 搜索 ──


class SearchHit(BaseModel):
    """单条搜索命中."""

    id: int
    title: str
    title_hit: str  # 高亮后标题
    summary_hit: str  # 高亮后摘要
    workspace_id: int
    status: str
    updated_at: dt.datetime
    rank: float


class SearchResponse(BaseModel):
    items: list[SearchHit]
    total: int
    query: str


# ── 权限 / 分享 ──


class PermissionEntry(BaseModel):
    user_id: int
    role: str = Field(pattern="^(owner|editor|viewer)$")


class PermissionUpdateRequest(BaseModel):
    entries: list[PermissionEntry] = Field(default_factory=list)


class ShareCreate(BaseModel):
    permission: str = Field(default="viewer", pattern="^(viewer|editor)$")
    password: str | None = Field(default=None, max_length=100)
    expires_at: dt.datetime | None = None


class ShareOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    token: str
    permission: str
    has_password: bool = False
    expires_at: dt.datetime | None
    view_count: int
    is_active: bool
    created_at: dt.datetime


class ShareAccessRequest(BaseModel):
    """匿名访问分享（带密码时）."""

    password: str | None = None


__all__ = [
    "ContentUpdate",
    "DailyNoteRequest",
    "DiffResponse",
    "DocumentCreate",
    "DocumentDetail",
    "DocumentOut",
    "DocumentUpdate",
    "LinkRepairItem",
    "LinkRepairRequest",
    "PermissionEntry",
    "PermissionUpdateRequest",
    "RollbackRequest",
    "SearchHit",
    "SearchResponse",
    "ShareAccessRequest",
    "ShareCreate",
    "ShareOut",
    "TagCreate",
    "TagIdsRequest",
    "TagOut",
    "TagUpdate",
    "VersionDetail",
    "VersionOut",
]
