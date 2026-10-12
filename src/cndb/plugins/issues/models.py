"""issues 插件 ORM 模型：问题清单（Issue）+ 评论 + 状态事件.

设计来源：GitHub Issue 协作模式。问题挂在工作区下的数据表上，
所有工作区成员均可提交与评论；关闭/重开由 owner/editor（或创建者本人）操作。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cndb.models.base import Base, TimestampMixin

# 问题类别
ISSUE_CATEGORY_DATA_ERROR = "data_error"
ISSUE_CATEGORY_SUGGESTION = "suggestion"
ISSUE_CATEGORY_QUESTION = "question"
ISSUE_CATEGORY_OTHER = "other"
ISSUE_CATEGORIES = (
    ISSUE_CATEGORY_DATA_ERROR,
    ISSUE_CATEGORY_SUGGESTION,
    ISSUE_CATEGORY_QUESTION,
    ISSUE_CATEGORY_OTHER,
)

# 问题状态
ISSUE_STATUS_OPEN = "open"
ISSUE_STATUS_CLOSED = "closed"
ISSUE_STATUSES = (ISSUE_STATUS_OPEN, ISSUE_STATUS_CLOSED)

# 状态事件动作
ISSUE_ACTION_CREATED = "created"
ISSUE_ACTION_CLOSED = "closed"
ISSUE_ACTION_REOPENED = "reopened"


class Issue(TimestampMixin, Base):
    """问题：数据表上的反馈条目（数据错误/建议/疑问等）."""

    __tablename__ = "issues_issue"
    __table_args__ = {"extend_existing": True}

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_id: Mapped[int] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False, default=ISSUE_CATEGORY_OTHER)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ISSUE_STATUS_OPEN, index=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # 关系
    comments: Mapped[list[IssueComment]] = relationship(back_populates="issue", cascade="all, delete-orphan")
    events: Mapped[list[IssueEvent]] = relationship(back_populates="issue", cascade="all, delete-orphan")


class IssueComment(TimestampMixin, Base):
    """问题评论."""

    __tablename__ = "issues_issuecomment"
    __table_args__ = {"extend_existing": True}

    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues_issue.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 关系
    issue: Mapped[Issue] = relationship(back_populates="comments")


class IssueEvent(Base):
    """问题状态事件流水：记录谁在何时创建/关闭/重开问题."""

    __tablename__ = "issues_issueevent"
    __table_args__ = (
        Index("ix_issues_issueevent_issue_id", "issue_id"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues_issue.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # 关系
    issue: Mapped[Issue] = relationship(back_populates="events")


__all__ = [
    "ISSUE_ACTION_CLOSED",
    "ISSUE_ACTION_CREATED",
    "ISSUE_ACTION_REOPENED",
    "ISSUE_CATEGORIES",
    "ISSUE_CATEGORY_DATA_ERROR",
    "ISSUE_CATEGORY_OTHER",
    "ISSUE_CATEGORY_QUESTION",
    "ISSUE_CATEGORY_SUGGESTION",
    "ISSUE_STATUSES",
    "ISSUE_STATUS_CLOSED",
    "ISSUE_STATUS_OPEN",
    "Issue",
    "IssueComment",
    "IssueEvent",
]
