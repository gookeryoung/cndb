"""workflows 插件 ORM 模型：Workflow / WorkflowNode / WorkflowEdge.

编排导航型工作流：
- Workflow 归属工作区，节点通过 table_id 绑定 DataTable（可空，表被删除时置 NULL）
- 节点坐标持久化，前端节点图按坐标渲染
- 边表达业务流程顺序，随节点删除级联清理
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cndb.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.workspaces.models import Workspace


class Workflow(TimestampMixin, Base):
    """业务流程：一组节点的有序编排."""

    __tablename__ = "workflows_workflow"
    __table_args__ = {"extend_existing": True}

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    workspace: Mapped[Workspace] = relationship("Workspace")
    nodes: Mapped[list[WorkflowNode]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowNode.id"
    )
    edges: Mapped[list[WorkflowEdge]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowEdge.id"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"Workflow(id={self.id}, name={self.name!r})"


class WorkflowNode(TimestampMixin, Base):
    """流程节点：绑定一张数据表，config 携带默认视图等展示配置."""

    __tablename__ = "workflows_workflownode"
    __table_args__ = {"extend_existing": True}

    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows_workflow.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    table_id: Mapped[int | None] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    pos_x: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pos_y: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    workflow: Mapped[Workflow] = relationship(back_populates="nodes")
    table: Mapped[DataTable | None] = relationship("DataTable")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"WorkflowNode(id={self.id}, name={self.name!r}, table_id={self.table_id})"


class WorkflowEdge(TimestampMixin, Base):
    """流程边：source → target 的业务流转顺序."""

    __tablename__ = "workflows_workflowedge"
    __table_args__ = (
        UniqueConstraint("workflow_id", "source_node_id", "target_node_id", name="uniq_wf_edge"),
        {"extend_existing": True},
    )

    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows_workflow.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_node_id: Mapped[int] = mapped_column(
        ForeignKey("workflows_workflownode.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_node_id: Mapped[int] = mapped_column(
        ForeignKey("workflows_workflownode.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    workflow: Mapped[Workflow] = relationship(back_populates="edges")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"WorkflowEdge(id={self.id}, {self.source_node_id}->{self.target_node_id})"


__all__ = ["Workflow", "WorkflowEdge", "WorkflowNode"]
