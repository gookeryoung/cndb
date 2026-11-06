"""pipeline_workflow_version — 流水线定义版本历史表（ADR 0114 P0）.

Revision ID: 4c6e8a0b2d3f
Revises: 3b5d7f9a1c2e
Create Date: 2026-11-06 15:00:00.000000

只新增 ``pipeline_workflow_version`` 一表：按定义单序列版本号存 DSL 原文快照
（``manual`` 主动保存 / ``rollback`` 版本恢复），随工作区与定义级联删除。
纯新增表，存量零迁移（不回填历史）；upgrade 幂等（表已存在跳过），
downgrade 只删本表，不触碰 ``pipeline_workflow`` / run / finding。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4c6e8a0b2d3f"
down_revision: str | Sequence[str] | None = "3b5d7f9a1c2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VERSION = "pipeline_workflow_version"


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """建版本表与索引（幂等：已存在跳过）."""
    if _table_exists(_VERSION):
        return
    op.create_table(
        _VERSION,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workflow_id",
            sa.Integer(),
            sa.ForeignKey("pipeline_workflow.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("comment", sa.String(length=200), nullable=False, server_default=""),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("accounts_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workflow_id", "version_number", name="uniq_pipeline_workflow_version_number"),
    )
    op.create_index("ix_pipeline_workflow_version_workspace_id", _VERSION, ["workspace_id"])
    op.create_index("ix_pipeline_workflow_version_workflow_id", _VERSION, ["workflow_id"])
    op.create_index("ix_pipeline_workflow_version_created_by_id", _VERSION, ["created_by_id"])
    op.create_index("ix_pipeline_workflow_version_ws_created", _VERSION, ["workspace_id", "created_at"])


def downgrade() -> None:
    """删版本表（幂等：不存在跳过，不触碰其他流水线表）."""
    if _table_exists(_VERSION):
        op.drop_table(_VERSION)
