"""design_version_change_type —— 设计版本区分主动保存 / 自动小版本（ADR 0113 P0）.

Revision ID: 3b5d7f9a1c2e
Revises: 2a4c6e8f0b1d
Create Date: 2026-11-06 14:00:00.000000

``design_designversion`` 新增 ``change_type``：``manual`` 主动保存 / ``auto``
自动小版本 / ``refresh`` 依赖刷新 / ``rollback`` 版本恢复。存量行由默认值补齐
（零数据改写），版本号仍单序列。upgrade / downgrade 均幂等。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3b5d7f9a1c2e"
down_revision: str | Sequence[str] | None = "2a4c6e8f0b1d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VERSION = "design_designversion"


def _table_exists(table: str) -> bool:
    """目标表是否存在（缺失则由启动期 create_all 兜底）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _columns(table: str) -> set[str]:
    """目标表现有列名集合（幂等判断用）."""
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """新增 ``change_type``（已存在则跳过；存量行默认 manual）."""
    if not _table_exists(_VERSION) or "change_type" in _columns(_VERSION):
        return
    op.add_column(
        _VERSION,
        sa.Column("change_type", sa.String(length=20), nullable=False, server_default="manual"),
    )


def downgrade() -> None:
    """删除 ``change_type``（列不存在则跳过，不触碰其他列与数据）."""
    if not _table_exists(_VERSION) or "change_type" not in _columns(_VERSION):
        return
    # 直接 ALTER TABLE DROP COLUMN：不走 batch 模式，避免反射缺表的历史库触发
    # NoSuchTableError（该列自身无约束 / 索引，无需重建表）
    op.drop_column(_VERSION, "change_type")
