"""add_rowpermission — 行级权限规则表 tables_rowpermission（ADR 0004）.

Revision ID: c8d9e0f1a2b3
Revises: b9c0d1e2f3a4
Create Date: 2026-10-19 10:00:00.000000

只建**新表**，不动存量 ``TablePermission``（ADR 0004 §8：存量零数据迁移，I3）。
升级后未配置任何行规则的库，行为与升级前逐条一致。

幂等约束（与 b5c6d7e8f9a0 / a4b5c6d7e8f9 同源）：
- 表已存在 → 跳过建表（由启动 create_all 兜底）
- 索引已存在 → 跳过
- downgrade：drop 索引 + drop 表（不改存量表）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "tables_rowpermission"
_INDEX = "ix_tables_rowpermission_table_id"


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _table_exists(table: str) -> bool:
    return table in set(_inspector().get_table_names())


def _index_names(table: str) -> set[str]:
    insp = _inspector()
    if table not in set(insp.get_table_names()):
        return set()
    return {ix["name"] for ix in insp.get_indexes(table) if ix.get("name")}


def upgrade() -> None:
    """Upgrade schema: 建 tables_rowpermission（行级规则主体 / 动作 / 条件）."""
    if _table_exists(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("table_id", sa.Integer(), nullable=False),
        sa.Column("subject_type", sa.String(16), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("filter_type", sa.String(3), nullable=False, server_default=sa.text("'AND'")),
        sa.Column("granted_by_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "table_id", "subject_type", "subject_id", "action", name="uniq_rowpermission_subject_action"
        ),
        sa.ForeignKeyConstraint(["table_id"], ["tables_datatable.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_id"], ["accounts_user.id"], ondelete="SET NULL"),
    )
    op.create_index(_INDEX, _TABLE, ["table_id"])


def downgrade() -> None:
    """Downgrade schema: drop 行级规则表（删除规则数据，不改存量 TablePermission）."""
    if not _table_exists(_TABLE):
        return
    if _INDEX in _index_names(_TABLE):
        op.drop_index(op.f(_INDEX), table_name=_TABLE)
    op.drop_table(_TABLE)
