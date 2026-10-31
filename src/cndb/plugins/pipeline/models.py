"""pipeline 插件 ORM 模型：流水线定义 / 运行 / 检查发现物（ADR 0076）.

设计要点：
- 定义（``pipeline_workflow``）以 **YAML 原文为唯一真相源**，保存期编译出的 IR
  快照存 ``compiled`` 列；运行只读 IR，因此运行期不出现语法 / 结构错误（I2）。
- 一次运行一条 ``pipeline_run``（状态 + 结论树快照 ``stats``）；发现物拆到
  ``pipeline_finding`` 行，便于按严重度 / 目标 / 动作过滤与分页（D6）。
- 三表均工作区级（``workspace_id`` 级联删除）；定义随工作区备份导出，运行与发现物
  属流水、不进备份（D12）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cndb.models.base import Base, TimestampMixin

# ── 运行状态 ──

RUN_STATUS_PENDING = "pending"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_SUCCESS = "success"
RUN_STATUS_PARTIAL = "partial"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_CANCELED = "canceled"
RUN_STATUSES = (
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCESS,
    RUN_STATUS_PARTIAL,
    RUN_STATUS_FAILED,
    RUN_STATUS_CANCELED,
)
#: 活跃状态：同一流水线同时只允许一个活跃运行（单飞）
ACTIVE_RUN_STATUSES = (RUN_STATUS_PENDING, RUN_STATUS_RUNNING)

# ── 触发方式 ──

TRIGGER_MANUAL = "manual"
TRIGGER_EVENT = "event"
TRIGGER_SCHEDULE = "schedule"
TRIGGERS = (TRIGGER_MANUAL, TRIGGER_EVENT, TRIGGER_SCHEDULE)

# ── 严重度 ──

SEVERITY_ERROR = "error"
SEVERITY_WARN = "warn"
SEVERITY_INFO = "info"
SEVERITIES = (SEVERITY_ERROR, SEVERITY_WARN, SEVERITY_INFO)
SEVERITY_RANK: dict[str, int] = {SEVERITY_INFO: 0, SEVERITY_WARN: 1, SEVERITY_ERROR: 2}

# ── 结论 ──

CONCLUSION_SUCCESS = "success"
CONCLUSION_FAILED = "failed"
CONCLUSION_SKIPPED = "skipped"


class PipelineWorkflow(TimestampMixin, Base):
    """流水线定义：工作区内同名唯一，绑定一份 YAML DSL 与编译产物."""

    __tablename__ = "pipeline_workflow"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uniq_pipeline_workflow_name"),
        Index("ix_pipeline_workflow_ws_updated", "workspace_id", "updated_at"),
        {"extend_existing": True},
    )

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: DSL 原文（YAML），用户可读可编辑的唯一真相源
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: 保存期编译出的 IR 快照（JSON），运行读此列不重新解析 YAML
    compiled: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"PipelineWorkflow(id={self.id}, name={self.name!r}, ws={self.workspace_id})"


class PipelineRun(TimestampMixin, Base):
    """一次流水线运行：状态 + 结论树快照（``stats``）."""

    __tablename__ = "pipeline_run"
    __table_args__ = (
        Index("ix_pipeline_run_workflow_created", "workflow_id", "created_at"),
        Index("ix_pipeline_run_ws_status", "workspace_id", "status"),
        {"extend_existing": True},
    )

    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_workflow.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default=TRIGGER_MANUAL)
    #: 事件 / 定时触发上下文（供 ``if:`` 表达式消费），手动触发为空
    trigger_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=RUN_STATUS_PENDING, index=True)
    #: 结论树与汇总：jobs / steps / findings 计数 / duration_ms
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"PipelineRun(id={self.id}, workflow={self.workflow_id}, status={self.status!r})"


class PipelineFinding(TimestampMixin, Base):
    """结构化检查发现物（对标 GitHub check run 的 annotation）.

    ``locator`` 只承载字段名 / 行 ID / 块序号 / 引用原文等**定位信息**，
    不携带字段值与单元格内容（D7 侧信道口径）。
    """

    __tablename__ = "pipeline_finding"
    __table_args__ = (
        Index("ix_pipeline_finding_run_severity", "run_id", "severity"),
        {"extend_existing": True},
    )

    run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: 产生该发现的检查动作名（如 ``table/null-rate``）
    check: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    severity: Mapped[str] = mapped_column(String(8), nullable=False, default=SEVERITY_WARN, index=True)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"PipelineFinding(id={self.id}, check={self.check!r}, severity={self.severity!r})"


__all__ = [
    "ACTIVE_RUN_STATUSES",
    "CONCLUSION_FAILED",
    "CONCLUSION_SKIPPED",
    "CONCLUSION_SUCCESS",
    "RUN_STATUSES",
    "RUN_STATUS_CANCELED",
    "RUN_STATUS_FAILED",
    "RUN_STATUS_PARTIAL",
    "RUN_STATUS_PENDING",
    "RUN_STATUS_RUNNING",
    "RUN_STATUS_SUCCESS",
    "SEVERITIES",
    "SEVERITY_ERROR",
    "SEVERITY_INFO",
    "SEVERITY_RANK",
    "SEVERITY_WARN",
    "TRIGGERS",
    "TRIGGER_EVENT",
    "TRIGGER_MANUAL",
    "TRIGGER_SCHEDULE",
    "PipelineFinding",
    "PipelineRun",
    "PipelineWorkflow",
]
