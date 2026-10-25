"""add_datasource_entrant_cursor — 按标的回补水位表 + 任务标的动态来源列.

Revision ID: a9d4e8f1c2b6
Revises: d0c1b2a3f4e5
Create Date: 2026-10-25 20:30:00.000000

见 ADR 0034（D2 / D3）：

- 新表 ``datasource_entrant_cursor``：``backfill_date`` 游标的按标的水位
  （每 (job, entrant) 一行，值为已回补到的最早日期，ISO 串）；
- ``datasource_sync_job`` 新列 ``entrant_source``（JSON NULL）：标的动态来源声明
  ``{"table","field","prefix_in"?}``，NULL 表示仅用静态 ``entrant_keys``（旧行为）。

幂等：表 / 列已存在则跳过；downgrade 删表删列可完整还原，水位可由重跑重算。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9d4e8f1c2b6"
down_revision: str | Sequence[str] | None = "d0c1b2a3f4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB = "datasource_sync_job"
_CURSOR = "datasource_entrant_cursor"


def _table_exists(table: str) -> bool:
    """目标表是否已存在（存在则整表跳过，保证迁移幂等）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    """目标列是否已存在（存在则跳过加列，保证迁移幂等）."""
    return column in {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Upgrade schema: 建按标的水位表，任务表加标的动态来源列（均幂等）."""
    if not _table_exists(_CURSOR):
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
        # 显式具名唯一索引（SQLite 内联 UniqueConstraint 会落成 sqlite_autoindex_N，
        # 具名索引便于 PRAGMA 校验与 downgrade 对位删除）
        op.create_index(f"uq_{_CURSOR}_job_entrant", _CURSOR, ["job_id", "entrant"], unique=True)
        op.create_index(f"ix_{_CURSOR}_job_id", _CURSOR, ["job_id"])

    if _table_exists(_JOB) and not _column_exists(_JOB, "entrant_source"):
        # 普通可空列，原生 ALTER ADD COLUMN 即可（batch 反射会连带解析 FK 目标表，
        # 在「表结构不完整」的存根库上会因引用表缺失而失败）
        op.add_column(_JOB, sa.Column("entrant_source", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema: 删任务表的动态来源列与按标的水位表（缺对象则跳过）."""
    if _table_exists(_JOB) and _column_exists(_JOB, "entrant_source"):
        # 原生 ALTER DROP COLUMN（同 1b2c3d4e5f60 先例）：batch 重建需反射全表，
        # 存根库上引用表缺失会炸；该列无索引/约束引用，原生 DROP 安全
        op.drop_column(_JOB, "entrant_source")
    if _table_exists(_CURSOR):
        op.drop_index(f"ix_{_CURSOR}_job_id", table_name=_CURSOR)
        op.drop_index(f"uq_{_CURSOR}_job_entrant", table_name=_CURSOR)
        op.drop_table(_CURSOR)
