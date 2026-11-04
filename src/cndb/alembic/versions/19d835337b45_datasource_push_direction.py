"""datasource_push_direction —— 数据同步支持对外推送（需求 0099）.

Revision ID: 19d835337b45
Revises: 134adcb233cb
Create Date: 2026-11-05 10:00:00.000000

- ``datasource_sync_job.direction``：pull（默认，外部→表）/ push（表→外部）；
- ``datasource_sync_job.push_spec``：推送目标、批次、字段与游标声明（JSON）。

存量任务回填 pull；upgrade 幂等，downgrade 可还原。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "19d835337b45"
down_revision: str | Sequence[str] | None = "134adcb233cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "datasource_sync_job"


def _column_exists(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table in inspector.get_table_names() and column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    if not _column_exists(_TABLE, "direction"):
        op.add_column(
            _TABLE,
            sa.Column("direction", sa.String(length=16), nullable=False, server_default="pull"),
        )
    if not _column_exists(_TABLE, "push_spec"):
        op.add_column(
            _TABLE,
            sa.Column("push_spec", sa.JSON(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    if _column_exists(_TABLE, "push_spec"):
        op.drop_column(_TABLE, "push_spec")
    if _column_exists(_TABLE, "direction"):
        op.drop_column(_TABLE, "direction")
