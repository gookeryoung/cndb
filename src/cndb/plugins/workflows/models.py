"""workflows 插件 ORM 模型：审批流图 + 审批运行时实例.

图结构三表（workflows_workflow / workflownode / workflowedge）由迁移
62817ea574fa 预先创建，本模块 ORM 逐列对齐该迁移；运行时两表
（approvalinstance / approvalaction）由迁移 add_form_approval 创建。

审批形态：线性链（start → approval* → end），沿出边推进；
表单提交的行数据以 JSON 快照存于 ApprovalInstance，链尾通过后落库。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cndb.models.base import Base, TimestampMixin

# 实例状态：pending=审批中 / approved=已通过（行已落库）/ rejected=已驳回
APPROVAL_STATUS_PENDING = "pending"
APPROVAL_STATUS_APPROVED = "approved"
APPROVAL_STATUS_REJECTED = "rejected"
APPROVAL_STATUSES = (APPROVAL_STATUS_PENDING, APPROVAL_STATUS_APPROVED, APPROVAL_STATUS_REJECTED)

# 节点类型：start=提交起点 / approval=审批节点 / end=链尾
NODE_TYPE_START = "start"
NODE_TYPE_APPROVAL = "approval"
NODE_TYPE_END = "end"

# 变更单操作类型（op 为 NULL 表示传统表单提交语义，落库等价 create）
CHANGE_OP_CREATE = "create"
CHANGE_OP_UPDATE = "update"
CHANGE_OP_DELETE = "delete"
CHANGE_OPS = (CHANGE_OP_CREATE, CHANGE_OP_UPDATE, CHANGE_OP_DELETE)


class Workflow(TimestampMixin, Base):
    """工作区级审批流定义（名称与元信息，节点/边见 WorkflowNode/WorkflowEdge）."""

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

    nodes: Mapped[list[WorkflowNode]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"Workflow(id={self.id}, name={self.name!r}, workspace_id={self.workspace_id})"


class WorkflowNode(TimestampMixin, Base):
    """审批流节点：类型与审批人角色存于 config JSON.

    config 结构（由 workflows/schemas 校验后写入）：
        {"node_type": "start"|"approval"|"end", "approver_role": "<WorkspaceRole.value>"}
    仅 approval 节点要求 approver_role 非空。
    """

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

    @property
    def node_type(self) -> str:
        """节点类型（config.node_type，缺省 start 兼容历史空配置）."""
        return str((self.config or {}).get("node_type", NODE_TYPE_START))

    @property
    def approver_role(self) -> str:
        """审批人角色阈值（仅 approval 节点有意义）."""
        return str((self.config or {}).get("approver_role", ""))


class WorkflowEdge(TimestampMixin, Base):
    """审批流有向边：source → target（线性链约束由 services.graph 校验）."""

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
        ForeignKey("workflows_workflownode.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_node_id: Mapped[int] = mapped_column(
        ForeignKey("workflows_workflownode.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class ApprovalInstance(TimestampMixin, Base):
    """审批实例：表单提交或网格变更单产生的待审批数据快照.

    双载荷形态：
    - 表单提交：form_id 非空、op 为 NULL，values 为提交值快照，
      审批全部通过后以快照调 records.create_row 落库并回写 record_id；
    - 变更单（表级「编辑需审批」开启后由网格/表单编辑提交）：
      form_id 为 NULL、op ∈ create/update/delete，row_id 为
      update/delete 的目标行 id；通过后按 op 落库。
    current_approver_role 为冗余列（与当前节点的 approver_role 同步），
    用于"待我审批"查询避免跨表 JSON 过滤。
    """

    __tablename__ = "workflows_approvalinstance"
    __table_args__ = {"extend_existing": True}

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows_workflow.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    form_id: Mapped[int | None] = mapped_column(
        ForeignKey("forms_formdefinition.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    table_id: Mapped[int] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 变更单操作类型；NULL 表示传统表单提交语义
    op: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # update/delete 变更单的目标行 id；create/表单提交为 NULL
    row_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 终态通过后回写落库行 id；pending/rejected 阶段为 NULL
    record_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    values: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # 当前所在 approval 节点；图被重存导致节点重建后可能悬空（SET NULL）
    current_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflows_workflownode.id", ondelete="SET NULL"),
        nullable=True,
    )
    current_approver_role: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=APPROVAL_STATUS_PENDING, index=True)
    submitted_by: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class ApprovalAction(TimestampMixin, Base):
    """审批动作流水：每个成功推进/驳回动作一条记录（失败不落流水）."""

    __tablename__ = "workflows_approvalaction"
    __table_args__ = {"extend_existing": True}

    instance_id: Mapped[int] = mapped_column(
        ForeignKey("workflows_approvalinstance.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 动作发生时所在节点；图重存后悬空置 NULL
    node_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflows_workflownode.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # approve / reject
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    acted_by: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"),
        nullable=True,
    )


__all__ = [
    "APPROVAL_STATUSES",
    "APPROVAL_STATUS_APPROVED",
    "APPROVAL_STATUS_PENDING",
    "APPROVAL_STATUS_REJECTED",
    "CHANGE_OPS",
    "CHANGE_OP_CREATE",
    "CHANGE_OP_DELETE",
    "CHANGE_OP_UPDATE",
    "NODE_TYPE_APPROVAL",
    "NODE_TYPE_END",
    "NODE_TYPE_START",
    "ApprovalAction",
    "ApprovalInstance",
    "Workflow",
    "WorkflowEdge",
    "WorkflowNode",
]
