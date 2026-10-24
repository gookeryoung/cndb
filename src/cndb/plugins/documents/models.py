"""documents 插件 ORM 模型：文档 / 版本 / 标签 / 分享.

设计要点：
- 文档挂在工作区下，支持文件夹层级（parent_id 自引用）；
- 内容通过 document_versions 版本化，每次保存自动创建新版本；
- 全文检索由 SQLite FTS5 虚拟表承担（见迁移脚本中的 documents_fts + 触发器），
  ORM 不声明 FTS 虚拟表模型，检索走 services.search 中的原生 SQL；
- 权限完全继承工作区角色，不设文档级覆盖项。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cndb.models.base import Base, TimestampMixin
from cndb.plugins.issues.models import (
    ISSUE_CATEGORY_OTHER,
    ISSUE_STATUS_OPEN,
)

# ── 常量 ──

DOC_STATUS_DRAFT = "draft"
DOC_STATUS_PUBLISHED = "published"
DOC_STATUS_ARCHIVED = "archived"
DOC_STATUSES = (DOC_STATUS_DRAFT, DOC_STATUS_PUBLISHED, DOC_STATUS_ARCHIVED)

CONTENT_TYPE_MARKDOWN = "markdown"
CONTENT_TYPE_FOLDER = "folder"
# 原件族（ADR 0025）：PDF / 图片 / Excel / PowerPoint 原样存档，正文只读
CONTENT_TYPE_PDF = "pdf"
CONTENT_TYPE_IMAGE = "image"
CONTENT_TYPE_XLSX = "xlsx"
CONTENT_TYPE_PPTX = "pptx"
#: 原件族集合：这些文档不参与 Markdown 写路径
ASSET_CONTENT_TYPES = (CONTENT_TYPE_PDF, CONTENT_TYPE_IMAGE, CONTENT_TYPE_XLSX, CONTENT_TYPE_PPTX)

CHANGE_TYPE_MANUAL = "manual"
CHANGE_TYPE_IMPORT = "auto_import"
CHANGE_TYPE_ROLLBACK = "rollback"
CHANGE_TYPES = (CHANGE_TYPE_MANUAL, CHANGE_TYPE_IMPORT, CHANGE_TYPE_ROLLBACK)

SHARE_PERM_VIEWER = "viewer"
SHARE_PERM_EDITOR = "editor"

# 分级存储阈值（字节数）
INLINE_MAX_SIZE = 50 * 1024  # ≤50KB 直接存 DB
EXTERNAL_MIN_SIZE = 2 * 1024 * 1024  # >2MB 落文件系统，DB 存路径


class Document(TimestampMixin, Base):
    """文档：工作区下的 Markdown 文档或文件夹节点."""

    __tablename__ = "documents_document"
    __table_args__ = (
        Index("ix_documents_document_ws_parent", "workspace_id", "parent_id", "sort_order"),
        {"extend_existing": True},
    )

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents_document.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    slug: Mapped[str | None] = mapped_column(String(500), nullable=True, unique=True)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False, default=CONTENT_TYPE_MARKDOWN)

    # 解析提取的元数据
    author: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    toc_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    # 状态
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=DOC_STATUS_DRAFT, index=True)
    is_folder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    # 回收站元数据：删除时间与操作人（历史数据为 NULL，仅表示"删除时刻未知"）。
    # 文件夹级联删除时整棵子树写入同一个 deleted_at，恢复时据此精确还原同批次子项，
    # 不连带复活"先被单独删除"的节点。
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True
    )

    # 大文件外存路径（NULL = 内容内联在 document_versions）
    content_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 原件（ADR 0025）：非 Markdown 格式的文件原样存档，file_key 指向工作区上传目录
    asset_file_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    asset_mime: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True
    )

    # 关系
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_number.desc()",
    )
    tags: Mapped[list[Tag]] = relationship(secondary="documents_documenttag", back_populates="documents")


class DocumentVersion(TimestampMixin, Base):
    """文档版本：每次保存自动创建的不可变内容快照."""

    __tablename__ = "documents_documentversion"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_docver_doc_num"),
        {"extend_existing": True},
    )

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents_document.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_html: Mapped[str | None] = mapped_column(Text, nullable=True)  # 渲染缓存（预留）
    content_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    change_summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    change_type: Mapped[str] = mapped_column(String(20), nullable=False, default=CHANGE_TYPE_MANUAL)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True
    )

    document: Mapped[Document] = relationship(back_populates="versions")


class Tag(TimestampMixin, Base):
    """标签：工作区级，可关联多个文档."""

    __tablename__ = "documents_tag"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_documents_tag_ws_name"),
        {"extend_existing": True},
    )

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#1890FF")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    documents: Mapped[list[Document]] = relationship(secondary="documents_documenttag", back_populates="tags")


class DocumentTag(Base):
    """文档-标签关联."""

    __tablename__ = "documents_documenttag"
    __table_args__ = {"extend_existing": True}

    document_id: Mapped[int] = mapped_column(ForeignKey("documents_document.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("documents_tag.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    tagged_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    tagged_by_id: Mapped[int | None] = mapped_column(ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True)


class DocumentShare(TimestampMixin, Base):
    """文档分享链接."""

    __tablename__ = "documents_share"
    __table_args__ = {"extend_existing": True}

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents_document.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    permission: Mapped[str] = mapped_column(String(20), nullable=False, default=SHARE_PERM_VIEWER)
    password_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True
    )


# ── 文档个人草稿（保存不落版本；显式提交后才生成版本 / 修改申请） ──


class DocumentDraft(TimestampMixin, Base):
    """个人工作草稿：每位用户对每篇文档至多一份，仅供本人读写.

    设计意图（替代「保存即提交」）：
    - 保存只更新本表，不创建 ``DocumentVersion``，正式内容不受影响；
    - 显式提交时才把草稿落库为版本（有直编资格）或修改申请；
    - ``base_version_number`` 记录开始编辑时所基于的版本，提交时用于
      段落级三方合并与修改申请的基准漂移判定。
    """

    __tablename__ = "documents_draft"
    __table_args__ = (
        UniqueConstraint("document_id", "user_id", name="uq_documents_draft_doc_user"),
        {"extend_existing": True},
    )

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents_document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("accounts_user.id", ondelete="CASCADE"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    base_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"DocumentDraft(document_id={self.document_id}, user_id={self.user_id})"


# ── 文档修改申请（双轨制写入：viewer / 关闭直编的 editor 保存时生成） ──

DCR_STATUS_OPEN = "open"
DCR_STATUS_MERGED = "merged"
DCR_STATUS_CLOSED = "closed"
DCR_STATUSES = (DCR_STATUS_OPEN, DCR_STATUS_MERGED, DCR_STATUS_CLOSED)


class DocumentChangeRequest(TimestampMixin, Base):
    """文档修改申请：对单篇文档正文的待审改动，通过后才生成新的文档版本.

    - ``base_version_number``：提交者编辑时所基于的版本号（0 = 空文档），
      merge 与 stale 判定均以它为基准；
    - ``proposed_content``：待审正文全文，未生效、不占用 document_versions；
    - 同一文档可并存多个 open 申请，版本前进一步后其余 open 申请置 ``stale``。
    """

    __tablename__ = "documents_changerequest"
    __table_args__ = (
        Index("ix_documents_changerequest_doc_status", "document_id", "status"),
        {"extend_existing": True},
    )

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents_document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 待审正文全文 + 字节数（列表页展示规模，无需回读正文）
    proposed_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    proposed_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    change_summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # 提交时的内容基准版本号（0 = 空文档）
    base_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DCR_STATUS_OPEN, index=True)
    # 基准过期标记：提交后文档又前进了版本，合并前需刷新基准
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    submitted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, nullable=False, default="")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"DocumentChangeRequest(id={self.id}, document_id={self.document_id}, status={self.status!r})"


# ── 文档问题清单（文档级 Issue：数据表问题清单的文档对应物） ──
# 类别 / 状态取值复用 issues 插件的常量，保证两类问题清单的前端标签一致；
# 载体独立：问题挂在文档上，随文档级联删除。

DI_ACTION_CREATED = "created"
DI_ACTION_CLOSED = "closed"
DI_ACTION_REOPENED = "reopened"


class DocumentPin(TimestampMixin, Base):
    """文档置顶（个人）：每个用户维护自己的置顶集合，互不影响.

    设计取舍：与「工作区置顶」一致做成**按用户**（`WorkspaceMember.pinned` 亦是个人偏好），
    避免某个成员置顶后影响整工作区的树顺序。
    """

    __tablename__ = "documents_pin"
    __table_args__ = (
        UniqueConstraint("document_id", "user_id", name="uq_documents_pin_doc_user"),
        {"extend_existing": True},
    )

    # id / created_at / updated_at 由 TimestampMixin 提供
    # （重复声明 id 会触发 pyrefly missing-override-decorator）
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents_document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("accounts_user.id", ondelete="CASCADE"), nullable=False, index=True)


class DocumentIssue(TimestampMixin, Base):
    """文档问题：文档上的反馈条目（数据错误/建议/疑问等）."""

    __tablename__ = "documents_issue"
    __table_args__ = (
        Index("ix_documents_issue_ws_status", "workspace_id", "status"),
        {"extend_existing": True},
    )

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents_document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False, default=ISSUE_CATEGORY_OTHER)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ISSUE_STATUS_OPEN, index=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )

    comments: Mapped[list[DocumentIssueComment]] = relationship(back_populates="issue", cascade="all, delete-orphan")
    events: Mapped[list[DocumentIssueEvent]] = relationship(back_populates="issue", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"DocumentIssue(id={self.id}, document_id={self.document_id}, status={self.status!r})"


class DocumentIssueComment(TimestampMixin, Base):
    """文档问题评论."""

    __tablename__ = "documents_issuecomment"
    __table_args__ = {"extend_existing": True}

    issue_id: Mapped[int] = mapped_column(
        ForeignKey("documents_issue.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True
    )

    issue: Mapped[DocumentIssue] = relationship(back_populates="comments")


class DocumentIssueEvent(Base):
    """文档问题状态事件流水：记录谁在何时创建/关闭/重开问题."""

    __tablename__ = "documents_issueevent"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("documents_issue.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    issue: Mapped[DocumentIssue] = relationship(back_populates="events")


__all__ = [
    "ASSET_CONTENT_TYPES",
    "CHANGE_TYPES",
    "CHANGE_TYPE_IMPORT",
    "CHANGE_TYPE_MANUAL",
    "CHANGE_TYPE_ROLLBACK",
    "CONTENT_TYPE_FOLDER",
    "CONTENT_TYPE_IMAGE",
    "CONTENT_TYPE_MARKDOWN",
    "CONTENT_TYPE_PDF",
    "CONTENT_TYPE_PPTX",
    "CONTENT_TYPE_XLSX",
    "DCR_STATUSES",
    "DCR_STATUS_CLOSED",
    "DCR_STATUS_MERGED",
    "DCR_STATUS_OPEN",
    "DI_ACTION_CLOSED",
    "DI_ACTION_CREATED",
    "DI_ACTION_REOPENED",
    "DOC_STATUSES",
    "DOC_STATUS_ARCHIVED",
    "DOC_STATUS_DRAFT",
    "DOC_STATUS_PUBLISHED",
    "EXTERNAL_MIN_SIZE",
    "INLINE_MAX_SIZE",
    "SHARE_PERM_EDITOR",
    "SHARE_PERM_VIEWER",
    "Document",
    "DocumentChangeRequest",
    "DocumentDraft",
    "DocumentIssue",
    "DocumentIssueComment",
    "DocumentIssueEvent",
    "DocumentPin",
    "DocumentShare",
    "DocumentTag",
    "DocumentVersion",
    "Tag",
]
