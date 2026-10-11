"""forms 插件 ORM 模型：FormDefinition.

表单定制视图：为数据表配置字段子集/顺序/必填/只读等展示规则，
并通过表单级三权限阈值（use/edit/delete）控制行增删查改。
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cndb.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.workspaces.models import Workspace


class FormDefinition(TimestampMixin, Base):
    """表单定义：绑定单张数据表的定制化表单配置.

    field_config 元素结构（由 forms/schemas.FormFieldConfig 校验）：
        {field_name, label?, required?, editable, visible, default_value?, help_text?}

    权限阈值列（use_role/edit_role/delete_role）：
        ""  = 未配置，回退表级权限判定
        非空 = 工作区角色名（WorkspaceRole.value），要求当前用户角色达到该阈值
    """

    __tablename__ = "forms_formdefinition"
    __table_args__ = (
        UniqueConstraint("table_id", "name", name="uniq_form_table_name"),
        {"extend_existing": True},
    )

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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    field_config: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    layout: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    use_role: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    edit_role: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    delete_role: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trashed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trashed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 关系
    workspace: Mapped[Workspace] = relationship("Workspace")
    table: Mapped[DataTable] = relationship("DataTable")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"FormDefinition(id={self.id}, name={self.name!r}, table_id={self.table_id})"


__all__ = ["FormDefinition"]
