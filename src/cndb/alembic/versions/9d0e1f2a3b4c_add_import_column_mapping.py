"""add_import_column_mapping — ImportTask 增加列映射（ADR 0020 P2/P3）.

Revision ID: 9d0e1f2a3b4c
Revises: 7b8c9d0e1f2a
Create Date: 2026-10-22 17:55:00.000000

- ``tables_importtask.column_mapping``：``{源列名: 目标字段名 | null}``；
  确认导入时按映射把源列写入目标字段（AI 列映射建议的落地点）。
- JSON 列，非空默认 ``{}``；downgrade 删除该列。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d0e1f2a3b4c"
down_revision: str | Sequence[str] | None = "7b8c9d0e1f2a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "tables_importtask"
_COLUMN = "column_mapping"


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _table_exists(table):
        return False
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """新增 column_mapping（幂等：表 / 列已存在跳过）."""
    if not _table_exists(_TABLE):
        return
    if _has_column(_TABLE, _COLUMN):
        return
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    """删除 column_mapping（幂等：不存在跳过）."""
    if not _has_column(_TABLE, _COLUMN):
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_column(_COLUMN)
