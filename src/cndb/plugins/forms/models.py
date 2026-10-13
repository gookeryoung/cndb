"""forms 插件 ORM 模型：FormDefinition.

设计来源：迁移 b8a7c6d5e4f3 forms_formdefinition 表结构。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cndb.models.base import Base, TimestampMixin


class FormDefinition(TimestampMixin, Base):
    """表单定义：绑定数据表 + 字段可见性/必填配置 + 三权限阈值.

    field_config 结构示例:
        [
            {"field_name": "姓名", "editable": true, "visible": true, "required": true},
            {"field_name": "工号", "editable": true, "visible": true, "required": true},
            {"field_name": "职位", "editable": true, "visible": true, "required": false},
            {"field_name": "薪资", "editable": true, "visible": true, "required": false},
        ]
    """

    __tablename__ = "forms_formdefinition"
    __table_args__ = {"extend_existing": True}

    workspace_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tables_datatable.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 字段配置列表：[field_name, editable, visible, required]
    field_config: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # 布局配置（预留，默认空对象）
    layout: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # 三权限阈值：空字符串=无限制
    use_role: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    edit_role: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    delete_role: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    trashed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    trashed_at: Mapped[str | None] = mapped_column(default=None)
    # 审批流绑定（可选，迁移 c1d2e3f4a5b6 已建列，ORM 层声明）
    approval_workflow_id: Mapped[int | None] = mapped_column(default=None)

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"FormDefinition(id={self.id}, name={self.name!r}, table_id={self.table_id})"


__all__ = ["FormDefinition"]
