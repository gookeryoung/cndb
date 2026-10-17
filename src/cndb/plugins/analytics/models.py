"""analytics 插件 ORM 模型：分析模板.

设计要点：
- 模板挂在工作区下（`workspace_id`），数据源为工作区内任意数据表（`table_id`，
  表删除后置 NULL，模板配置仍保留）；
- `config` 为 JSON：存公式清单与图表配置（结构由前端与服务层共同约定，
  服务层保存时校验公式表达式合法性）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cndb.models.base import Base, TimestampMixin


class AnalyticsTemplate(TimestampMixin, Base):
    """分析模板：一组公式 + 可视化配置的可复用快照."""

    __tablename__ = "analytics_template"
    __table_args__ = (
        Index("ix_analytics_template_ws_updated", "workspace_id", "updated_at"),
        {"extend_existing": True},
    )

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 数据源表（可空：表被删除后置 NULL，模板仍保留；前端加载时提示重新选表）
    table_id: Mapped[int | None] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 公式清单 + 图表配置，详见 services/templates.py 的 normalize_config
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True
    )


__all__ = ["AnalyticsTemplate"]
