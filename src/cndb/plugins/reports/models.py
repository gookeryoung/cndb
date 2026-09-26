"""reports 插件 ORM 模型：ReportTemplate.

设计来源：cndb Django reports 模块，改用 SQLAlchemy 2.0 重写.
"""

from __future__ import annotations

import enum
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cndb.models.base import Base, TimestampMixin


class OutputFormat(enum.StrEnum):
    """报告输出格式."""

    DOCX = "docx"
    PDF = "pdf"
    XLSX = "xlsx"
    HTML = "html"


class ThemeStyle(enum.StrEnum):
    """报告主题风格：影响导出文档的文字与格式."""

    BUSINESS = "business"
    MINIMAL = "minimal"
    MODERN = "modern"
    ENGINEERING = "engineering"
    ACADEMIC = "academic"


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
    output_format: Mapped[str] = mapped_column(String(16), nullable=False, default=OutputFormat.DOCX)
    template_content: Mapped[str] = mapped_column(Text, nullable=False)
    # 参数定义：[{name, type, default, required, label}]
    parameters: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # 可选归属表：模板可绑定默认表，也可通用
    table_id: Mapped[int | None] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # 额外引用表 id 列表（可跨工作区，渲染时注入 records_by_table；迁移 b3c4d5e6f7a8 已建列）
    extra_table_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    # 主题风格（迁移 add_report_template_theme 已建列，存量行为 minimal）
    theme: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ThemeStyle.MINIMAL.value, server_default=ThemeStyle.MINIMAL.value
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"ReportTemplate(id={self.id}, name={self.name!r}, format={self.output_format!r}, theme={self.theme!r})"


__all__ = ["OutputFormat", "ReportTemplate", "ThemeStyle"]
