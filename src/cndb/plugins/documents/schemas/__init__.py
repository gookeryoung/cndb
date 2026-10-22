"""documents 插件 Pydantic schemas：请求/响应 DTO."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

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


class DocumentAiActionRequest(BaseModel):
    """文档 AI 动作请求（ADR 0020 P1）.

    ``polish`` 用 ``selection`` / ``instruction`` / ``language`` / ``context``；
    ``summarize`` / ``suggest_tags`` 忽略这些字段、直接读文档最新正文。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    selection: str | None = Field(default=None, max_length=8000, description="待改写片段（polish 必填）")
    instruction: str = Field(
        default="polish", max_length=32, description="polish / shorten / expand / formal / translate"
    )
    language: str | None = Field(default=None, max_length=16, description="translate 的目标语言")
    context: str | None = Field(default=None, max_length=500, description="可选的上下文（标题 / 所在小节）")


class DocumentBatchRequest(BaseModel):
    """文档批量操作（移动 / 删除）."""

    action: Literal["move", "delete"]
    ids: list[int] = Field(min_length=1, max_length=200)
    # move 专用：目标父节点（0 或 None = 根目录）
    parent_id: int | None = None


class ContentUpdate(BaseModel):
    """更新文档内容（乐观锁：客户端回传读取时的 updated_at）."""

    content: str
    change_summary: str = Field(default="", max_length=500)
    # 乐观锁版本戳：客户端上次读取/保存时拿到的 updated_at ISO 字符串
    base_updated_at: str | None = None
    # 无直编资格时转修改申请所用的内容基准版本号（缺省取服务端当前最新版本）
    base_version_number: int | None = Field(default=None, ge=0)


class DocumentDraftSave(BaseModel):
    """保存个人工作草稿（不生成版本）."""

    content: str
    # 开始编辑时所基于的版本号；超过服务端最新版本会被拒绝
    base_version_number: int | None = Field(default=None, ge=0)


class DocumentSubmit(BaseModel):
    """显式提交修改：直编落库为新版本，否则生成修改申请."""

    # 缺省取服务端已保存的个人草稿
    content: str | None = None
    change_summary: str = Field(default="", max_length=500)
    base_version_number: int | None = Field(default=None, ge=0)


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
    # 当前用户个人置顶（个人偏好，非文档属性）
    pinned: bool = False


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


# ── 文档修改申请（双轨制写入的待审载体） ──


class DocumentChangeRequestCreate(BaseModel):
    """手动发起文档修改申请（自动分派路径不经此 DTO）."""

    document_id: int
    content: str
    title: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=2000)
    change_summary: str = Field(default="", max_length=500)
    # 提交者编辑所基于的版本号；缺省取服务端当前最新版本
    base_version_number: int | None = Field(default=None, ge=0)


class DocumentChangeRequestReview(BaseModel):
    """通过 / 驳回修改申请时的审核意见（可省略请求体）."""

    review_comment: str = Field(default="", max_length=2000)


class DocumentChangeRequestUpdateBase(BaseModel):
    """刷新基准：以指定版本（缺省取当前最新）作为新的对比基准."""

    base_version_number: int | None = Field(default=None, ge=0)


# ── 文档问题清单（文档级 Issue） ──


class DocumentIssueCreate(BaseModel):
    """提交文档问题（类别合法性由服务层统一校验，与数据表问题清单一致）."""

    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: int
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    category: str = "other"


class DocumentIssueCommentCreate(BaseModel):
    """文档问题评论."""

    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=2000)


__all__ = [
    "ContentUpdate",
    "DiffResponse",
    "DocumentChangeRequestCreate",
    "DocumentChangeRequestReview",
    "DocumentChangeRequestUpdateBase",
    "DocumentCreate",
    "DocumentDetail",
    "DocumentDraftSave",
    "DocumentIssueCommentCreate",
    "DocumentIssueCreate",
    "DocumentOut",
    "DocumentSubmit",
    "DocumentUpdate",
    "LinkRepairItem",
    "LinkRepairRequest",
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
