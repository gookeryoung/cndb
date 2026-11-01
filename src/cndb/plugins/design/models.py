"""design 插件 ORM 模型：设计定义 / 版本（ADR 0079 P0）.

设计要点：

- ``design_design`` 以 **DSL 原文（``.cnmd``）为唯一真相源**，保存期编译出的
  IR 快照存 ``compiled`` 列；预览 / 渲染只读 IR，运行期不出现语法错误（I2）。
- 每次保存落一条 ``design_designversion``（对齐 ``DocumentVersion`` 范式，D7）。
- 两表均工作区级（``workspace_id`` 级联删除）；权限完全继承工作区角色（D6）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cndb.models.base import Base, TimestampMixin


class DesignDesign(TimestampMixin, Base):
    """一份结构设计：工作区内同题唯一，绑定一份 DSL 原文与编译产物."""

    __tablename__ = "design_design"
    __table_args__ = (
        UniqueConstraint("workspace_id", "title", name="uniq_design_design_title"),
        Index("ix_design_design_ws_updated", "workspace_id", "updated_at"),
        {"extend_existing": True},
    )

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    #: DSL 原文（.cnmd），用户可读可编辑的唯一真相源
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: 保存期编译出的 IR 快照（JSON）；编译不通过拒绝落库，预览 / 渲染只读此列
    compiled: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    #: 软删（列表过滤）；回收站 UI 不在本期范围（ADR 0079 §1）
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"DesignDesign(id={self.id}, title={self.title!r}, ws={self.workspace_id})"


class DesignDesignVersion(TimestampMixin, Base):
    """设计版本：每次保存原文即落一版（对齐 DocumentVersion）."""

    __tablename__ = "design_designversion"
    __table_args__ = (
        UniqueConstraint("design_id", "version_number", name="uniq_design_version_number"),
        Index("ix_design_designversion_ws_created", "workspace_id", "created_at"),
        {"extend_existing": True},
    )

    design_id: Mapped[int] = mapped_column(
        ForeignKey("design_design.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    compiled: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    comment: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"DesignDesignVersion(id={self.id}, design={self.design_id}, no={self.version_number})"


__all__ = [
    "DesignDesign",
    "DesignDesignVersion",
]
