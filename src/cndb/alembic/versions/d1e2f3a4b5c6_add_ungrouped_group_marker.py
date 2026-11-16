"""add_ungrouped_group_marker — 「未分组」占位分组（需求 0137）.

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-11-16 12:00:00.000000

为 ``tables_tablegroup`` 增加 ``is_ungrouped`` 标记：每个工作区一条「未分组」
占位行，让未分组在分组排序里有明确位置（不再恒在最后）；占位行不可改名 / 删除。
迁移可重入：列已存在时跳过。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GROUP_TABLE = "tables_tablegroup"


def _table_exists(bind: sa.engine.Connection, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def _column_names(bind: sa.engine.Connection, table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, _GROUP_TABLE) and "is_ungrouped" not in _column_names(bind, _GROUP_TABLE):
        op.add_column(
            _GROUP_TABLE,
            sa.Column("is_ungrouped", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, _GROUP_TABLE) and "is_ungrouped" in _column_names(bind, _GROUP_TABLE):
        if bind.dialect.name == "sqlite":
            # SQLite 不支持 batch 反射引用缺失表的场景（残缺库降级），直接 DROP COLUMN
            bind.execute(sa.text(f"ALTER TABLE {_GROUP_TABLE} DROP COLUMN is_ungrouped"))
        else:
            op.drop_column(_GROUP_TABLE, "is_ungrouped")
