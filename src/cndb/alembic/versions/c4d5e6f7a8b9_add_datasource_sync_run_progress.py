"""add_datasource_sync_run_progress — 同步运行记录加请求级进度列.

Revision ID: c4d5e6f7a8b9
Revises: a9d4e8f1c2b6
Create Date: 2026-10-26 10:00:00.000000

见 ADR 0037（D4）：运行中展示进度需要「计划请求数 / 已完成请求数 / 当前标的」，
运行记录新增三列（NOT NULL + 服务端默认值，存量行补 0 / 空串）。
幂等：列已存在则跳过；downgrade 原生删列可完整还原（进度可由重跑重算）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "a9d4e8f1c2b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN = "datasource_sync_run"


def _table_exists(table: str) -> bool:
    """目标表是否已存在（不存在则整表跳过，保证迁移幂等）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    """目标列是否已存在（存在则跳过加列，保证迁移幂等）."""
    return column in {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Upgrade schema: 运行记录加 progress_total / progress_done / progress_entrant."""
    if not _table_exists(_RUN):
        return
    if not _column_exists(_RUN, "progress_total"):
        op.add_column(
            _RUN,
            sa.Column("progress_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
    if not _column_exists(_RUN, "progress_done"):
        op.add_column(
            _RUN,
            sa.Column("progress_done", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
    if not _column_exists(_RUN, "progress_entrant"):
        op.add_column(
            _RUN,
            sa.Column("progress_entrant", sa.String(length=64), nullable=False, server_default=sa.text("''")),
        )


def downgrade() -> None:
    """Downgrade schema: 删运行记录的三列进度字段（缺列则跳过）."""
    if not _table_exists(_RUN):
        return
    for column in ("progress_entrant", "progress_done", "progress_total"):
        if _column_exists(_RUN, column):
            # 原生 ALTER DROP COLUMN（同 1b2c3d4e5f60 先例）：batch 重建需反射全表，存根库会炸
            op.drop_column(_RUN, column)
