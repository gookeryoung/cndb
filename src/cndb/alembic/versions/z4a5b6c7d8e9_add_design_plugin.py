"""add_design_plugin —— 设计模块两表（ADR 0079 P0）.

Revision ID: z4a5b6c7d8e9
Revises: y3z4a5b6c7d8
Create Date: 2026-11-01 15:00:00.000000

- ``design_design``：结构 DSL（.cnmd）原文 + 保存期编译的 IR 快照；
- ``design_designversion``：每次保存落一版（对齐 DocumentVersion 范式）。

纯新增表，存量零迁移；upgrade 幂等（表已存在跳过），downgrade 按依赖序删表。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "z4a5b6c7d8e9"
down_revision: str | Sequence[str] | None = "y3z4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DESIGN = "design_design"
_VERSION = "design_designversion"


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """建设计两表（幂等：已存在跳过）."""
    if _table_exists(_DESIGN):
        return
    op.create_table(
        _DESIGN,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("compiled", sa.JSON(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("accounts_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_id",
            sa.Integer(),
            sa.ForeignKey("accounts_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "title", name="uniq_design_design_title"),
    )
    op.create_index("ix_design_design_workspace_id", _DESIGN, ["workspace_id"])
    op.create_index("ix_design_design_is_deleted", _DESIGN, ["is_deleted"])
    op.create_index("ix_design_design_created_by_id", _DESIGN, ["created_by_id"])
    op.create_index("ix_design_design_updated_by_id", _DESIGN, ["updated_by_id"])
    op.create_index("ix_design_design_ws_updated", _DESIGN, ["workspace_id", "updated_at"])

    op.create_table(
        _VERSION,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "design_id",
            sa.Integer(),
            sa.ForeignKey(f"{_DESIGN}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("compiled", sa.JSON(), nullable=False),
        sa.Column("comment", sa.String(length=200), nullable=False),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("accounts_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("design_id", "version_number", name="uniq_design_version_number"),
    )
    op.create_index("ix_design_designversion_design_id", _VERSION, ["design_id"])
    op.create_index("ix_design_designversion_workspace_id", _VERSION, ["workspace_id"])
    op.create_index("ix_design_designversion_created_by_id", _VERSION, ["created_by_id"])
    op.create_index("ix_design_designversion_ws_created", _VERSION, ["workspace_id", "created_at"])


def downgrade() -> None:
    """按依赖序删表（幂等：不存在跳过）."""
    if _table_exists(_VERSION):
        op.drop_table(_VERSION)
    if _table_exists(_DESIGN):
        op.drop_table(_DESIGN)
