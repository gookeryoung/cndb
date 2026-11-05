"""drop_datasource_entrant_cursor —— 删除按标的回补水位表（ADR 0104）.

Revision ID: 2a4c6e8f0b1d
Revises: 19d835337b45
Create Date: 2026-11-05 14:00:00.000000

ADR 0104 移除 ``backfill_date`` 游标与多 pass 回补，``datasource_entrant_cursor``
随之失去写入方：表数据可由重跑重算，无迁移价值，直接 drop。

upgrade / downgrade 均幂等：对象缺失则跳过。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2a4c6e8f0b1d"
down_revision: str | Sequence[str] | None = "19d835337b45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB = "datasource_sync_job"
_CURSOR = "datasource_entrant_cursor"
_UK_JOB_ENTRANT = f"uq_{_CURSOR}_job_entrant"
_IX_JOB_ID = f"ix_{_CURSOR}_job_id"


def _table_exists(table: str) -> bool:
    """目标表是否已存在（不存在则跳过，保证迁移幂等）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _index_exists(table: str, index: str) -> bool:
    """目标索引是否已存在（不存在则跳过，兼容手工删过索引的库）."""
    return index in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    """Upgrade schema: 删除按标的回补水位表（幂等）."""
    if not _table_exists(_CURSOR):
        return
    if _index_exists(_CURSOR, _IX_JOB_ID):
        op.drop_index(_IX_JOB_ID, table_name=_CURSOR)
    if _index_exists(_CURSOR, _UK_JOB_ENTRANT):
        op.drop_index(_UK_JOB_ENTRANT, table_name=_CURSOR)
    op.drop_table(_CURSOR)


def downgrade() -> None:
    """Downgrade schema: 按原结构重建水位表与索引（空表，水位可由重跑重算）."""
    if _table_exists(_CURSOR):
        return
    op.create_table(
        _CURSOR,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey(f"{_JOB}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entrant", sa.String(length=255), nullable=False),
        sa.Column("cursor_value", sa.String(length=64), nullable=False),
    )
    # 显式具名索引，便于 PRAGMA 校验与再次 upgrade 对位删除
    op.create_index(_UK_JOB_ENTRANT, _CURSOR, ["job_id", "entrant"], unique=True)
    op.create_index(_IX_JOB_ID, _CURSOR, ["job_id"])
