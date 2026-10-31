"""add_pipeline_plugin — 流水线质量检查三表（ADR 0076 P0）.

Revision ID: y3z4a5b6c7d8
Revises: x2y3z4a5b6c7
Create Date: 2026-10-31 10:00:00.000000

- ``pipeline_workflow``：YAML DSL 原文 + 保存期编译的 IR 快照；
- ``pipeline_run``：一次运行的状态 / 触发上下文 / 结论树汇总；
- ``pipeline_finding``：结构化发现物（按严重度 / 目标 / 动作过滤）。

纯新增表，存量零迁移；upgrade 幂等（表已存在跳过），downgrade 按依赖序删表。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "y3z4a5b6c7d8"
down_revision: str | Sequence[str] | None = "x2y3z4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WORKFLOW = "pipeline_workflow"
_RUN = "pipeline_run"
_FINDING = "pipeline_finding"


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """建三张流水线表（幂等：已存在跳过）."""
    if _table_exists(_WORKFLOW):
        return
    op.create_table(
        _WORKFLOW,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("compiled", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("accounts_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "name", name="uniq_pipeline_workflow_name"),
    )
    op.create_index("ix_pipeline_workflow_workspace_id", _WORKFLOW, ["workspace_id"])
    op.create_index("ix_pipeline_workflow_created_by_id", _WORKFLOW, ["created_by_id"])
    op.create_index("ix_pipeline_workflow_ws_updated", _WORKFLOW, ["workspace_id", "updated_at"])

    op.create_table(
        _RUN,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workflow_id",
            sa.Integer(),
            sa.ForeignKey(f"{_WORKFLOW}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("trigger_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_pipeline_run_workflow_id", _RUN, ["workflow_id"])
    op.create_index("ix_pipeline_run_workspace_id", _RUN, ["workspace_id"])
    op.create_index("ix_pipeline_run_status", _RUN, ["status"])
    op.create_index("ix_pipeline_run_workflow_created", _RUN, ["workflow_id", "created_at"])
    op.create_index("ix_pipeline_run_ws_status", _RUN, ["workspace_id", "status"])

    op.create_table(
        _FINDING,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey(f"{_RUN}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("check", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_pipeline_finding_run_id", _FINDING, ["run_id"])
    op.create_index("ix_pipeline_finding_check", _FINDING, ["check"])
    op.create_index("ix_pipeline_finding_severity", _FINDING, ["severity"])
    op.create_index("ix_pipeline_finding_run_severity", _FINDING, ["run_id", "severity"])


def downgrade() -> None:
    """按依赖序删表（幂等：不存在跳过）."""
    if _table_exists(_FINDING):
        op.drop_table(_FINDING)
    if _table_exists(_RUN):
        op.drop_table(_RUN)
    if _table_exists(_WORKFLOW):
        op.drop_table(_WORKFLOW)
