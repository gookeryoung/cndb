"""add_document_trash_fields — 文档回收站元数据（deleted_at / deleted_by_id）.

Revision ID: b1c2d3e4f5a6
Revises: f0a1b2c3d4e5
Create Date: 2026-10-14 17:00:00.000000

背景：documents 插件此前只有布尔软删除标记 ``is_deleted``，既无处可查已删除
文档，也无法恢复；文件夹级联删除后无法区分"随父删除"与"先被单独删除"的子项。
本迁移为 ``documents_document`` 补齐两列：

- deleted_at    DateTime(tz) NULL：删除时刻（文件夹级联时整棵子树共用同一值）
- deleted_by_id Integer     NULL：删除操作人（FK 未建，与既有链上加列先例一致）

存量已删除行两列为 NULL，语义为"删除时刻未知"，回收站与恢复逻辑按"整棵子树"
宽松处理，不影响数据可读性。幂等加列，兼容 create_all 时代已含该列的旧库。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'f0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "documents_document"


def _table_exists(table: str) -> bool:
    """目标表是否存在（不存在则整表由启动 create_all 兜底，本迁移跳过）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _existing_columns(table: str) -> set[str]:
    """读取表当前已有的列名集合（表不存在时返回空集）."""
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> None:  # type: ignore[type-arg]
    """列不存在才 add_column（幂等，兼容已含该列的旧库）."""
    if not _table_exists(table) or column.name in _existing_columns(table):
        return
    op.add_column(table, column)


def upgrade() -> None:
    """Upgrade schema: 补齐回收站两列."""
    _add_column_if_missing(_TABLE, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(_TABLE, sa.Column("deleted_by_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema: 移除回收站两列（缺表或缺列时跳过）."""
    if not _table_exists(_TABLE):
        return
    cols = _existing_columns(_TABLE)
    if "deleted_by_id" in cols:
        op.drop_column(_TABLE, "deleted_by_id")
    if "deleted_at" in cols:
        op.drop_column(_TABLE, "deleted_at")
