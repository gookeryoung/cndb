"""reports 插件 ORM 模型：ReportTemplate.

设计来源：cndb Django reports 模块，改用 SQLAlchemy 2.0 重写.
"""

from __future__ import annotations

import enum
from typing import Any

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cndb.models.base import Base, TimestampMixin


class OutputFormat(enum.StrEnum):
    """报告输出格式."""

    DOCX = "docx"
    PDF = "pdf"
    XLSX = "xlsx"


class ReportTemplate(TimestampMixin, Base):
    """报告模板：用 Jinja2 语法定义，渲染时注入 table records + 用户参数.

    template_content 为 Jinja2 模板字符串，渲染上下文包含：
    - records: 行数据列表（dict）
    - table_name: 表名（str）
    - params: 用户传入的参数（dict）
    """

    __tablename__ = "reports_template"
    __table_args__ = {"extend_existing": True}

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output_format: Mapped[str] = mapped_column(
        String(16), nullable=False, default=OutputFormat.DOCX
    )
    template_content: Mapped[str] = mapped_column(Text, nullable=False)
    # 参数定义：[{name, type, default, required, label}]
    parameters: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"ReportTemplate(id={self.id}, name={self.name!r}, format={self.output_format!r})"


__all__ = ["OutputFormat", "ReportTemplate"]
