"""documents 插件 ORM 模型：文档 / 版本 / 标签 / 权限 / 分享.

设计要点：
- 文档挂在工作区下，支持文件夹层级（parent_id 自引用）；
- 内容通过 document_versions 版本化，每次保存自动创建新版本；
- 全文检索由 SQLite FTS5 虚拟表承担（见迁移脚本中的 documents_fts + 触发器），
  ORM 不声明 FTS 虚拟表模型，检索走 services.search 中的原生 SQL；
- 权限默认继承工作区角色，document_permissions 仅存覆盖项。
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

# ── 常量 ──

DOC_STATUS_DRAFT = "draft"
DOC_STATUS_PUBLISHED = "published"
DOC_STATUS_ARCHIVED = "archived"
DOC_STATUSES = (DOC_STATUS_DRAFT, DOC_STATUS_PUBLISHED, DOC_STATUS_ARCHIVED)

CONTENT_TYPE_MARKDOWN = "markdown"
CONTENT_TYPE_FOLDER = "folder"

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


class DocumentPermission(Base):
    """文档级权限覆盖（默认继承工作区角色）."""

    __tablename__ = "documents_permission"
    __table_args__ = {"extend_existing": True}

    document_id: Mapped[int] = mapped_column(ForeignKey("documents_document.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # owner/editor/viewer


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


__all__ = [
    "CHANGE_TYPES",
    "CHANGE_TYPE_IMPORT",
    "CHANGE_TYPE_MANUAL",
    "CHANGE_TYPE_ROLLBACK",
    "CONTENT_TYPE_FOLDER",
    "CONTENT_TYPE_MARKDOWN",
    "DOC_STATUSES",
    "DOC_STATUS_ARCHIVED",
    "DOC_STATUS_DRAFT",
    "DOC_STATUS_PUBLISHED",
    "EXTERNAL_MIN_SIZE",
    "INLINE_MAX_SIZE",
    "SHARE_PERM_EDITOR",
    "SHARE_PERM_VIEWER",
    "Document",
    "DocumentPermission",
    "DocumentShare",
    "DocumentTag",
    "DocumentVersion",
    "Tag",
]
