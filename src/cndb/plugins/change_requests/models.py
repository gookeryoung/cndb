"""change_requests 插件 ORM 模型：修改申请（ChangeRequest）+ 变更项 + 动作流水.

设计来源：GitHub Pull Request 协作模式。所有工作区成员可发起修改申请，
仅 owner/editor 可 merge（逐项 apply/skip 决策后正式落库）/close/reopen；
同一行允许多个 open 申请并存，merge 后其余同行申请标记 stale。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cndb.models.base import Base, TimestampMixin

# 申请状态
CR_STATUS_OPEN = "open"
CR_STATUS_MERGED = "merged"
CR_STATUS_CLOSED = "closed"
CR_STATUSES = (CR_STATUS_OPEN, CR_STATUS_MERGED, CR_STATUS_CLOSED)

# 变更项操作类型
CHANGE_OP_CREATE = "create"
CHANGE_OP_UPDATE = "update"
CHANGE_OP_DELETE = "delete"
CHANGE_OPS = (CHANGE_OP_CREATE, CHANGE_OP_UPDATE, CHANGE_OP_DELETE)

# 动作流水类型
CR_ACTION_COMMENT = "comment"
CR_ACTION_MERGE = "merge"
CR_ACTION_CLOSE = "close"
CR_ACTION_REOPEN = "reopen"
CR_ACTION_UPDATE_BASE = "update_base"


class ChangeRequest(TimestampMixin, Base):
    """修改申请：对某张数据表的一组行级变更，处理（merge）后才正式落库."""

    __tablename__ = "change_requests_changerequest"
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
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=CR_STATUS_OPEN, index=True)
    # 基准过期标记：merge 落库后其他引用相同行的 open 申请置 True，
    # 提交人可 update-base 重新读取当前行刷新基准后复位
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    submitted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # 关系
    items: Mapped[list[ChangeItem]] = relationship(back_populates="request", cascade="all, delete-orphan")
    actions: Mapped[list[ChangeRequestAction]] = relationship(back_populates="request", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"ChangeRequest(id={self.id}, title={self.title!r}, status={self.status!r})"


class ChangeItem(TimestampMixin, Base):
    """变更项：申请内的单行操作.

    - base_values：提交时目标行快照中「本次涉及字段」的原值（create 为空 dict），
      作为 merge 时基准漂移检测的依据；
    - values：新值增量（delete 为空 dict）。
    """

    __tablename__ = "change_requests_changeitem"
    __table_args__ = {"extend_existing": True}

    request_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests_changerequest.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    op: Mapped[str] = mapped_column(String(16), nullable=False)
    # update/delete 的目标行 id；create 为 NULL
    row_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    base_values: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    values: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # 关系
    request: Mapped[ChangeRequest] = relationship(back_populates="items")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"ChangeItem(id={self.id}, request_id={self.request_id}, op={self.op!r}, row_id={self.row_id})"


class ChangeRequestAction(TimestampMixin, Base):
    """修改申请动作流水：评论与 merge/close/reopen/update_base 统一记录."""

    __tablename__ = "change_requests_changeaction"
    __table_args__ = {"extend_existing": True}

    request_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests_changerequest.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    acted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 关系
    request: Mapped[ChangeRequest] = relationship(back_populates="actions")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"ChangeRequestAction(id={self.id}, request_id={self.request_id}, action={self.action!r})"


__all__ = [
    "CHANGE_OPS",
    "CHANGE_OP_CREATE",
    "CHANGE_OP_DELETE",
    "CHANGE_OP_UPDATE",
    "CR_ACTION_CLOSE",
    "CR_ACTION_COMMENT",
    "CR_ACTION_MERGE",
    "CR_ACTION_REOPEN",
    "CR_ACTION_UPDATE_BASE",
    "CR_STATUSES",
    "CR_STATUS_CLOSED",
    "CR_STATUS_MERGED",
    "CR_STATUS_OPEN",
    "ChangeItem",
    "ChangeRequest",
    "ChangeRequestAction",
]
