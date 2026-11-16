"""add_table_groups — 工作区级数据表分组（需求 0137）.

Revision ID: c9d0e1f2a3b4
Revises: e3f4a5b6c7d8
Create Date: 2026-11-16 10:00:00.000000

新增 ``tables_tablegroup``（工作区级表分组）与 ``tables_datatable.group_id``
（可空 = 未分组，默认不分组）。分组删除 / 工作区删除时表回落未分组，不删表。
迁移可重入：表 / 列 / 索引已存在时跳过。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GROUP_TABLE = "tables_tablegroup"
_TABLE_TABLE = "tables_datatable"


def _table_exists(bind: sa.engine.Connection, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def _column_names(bind: sa.engine.Connection, table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(bind).get_columns(table)}


def _index_names(bind: sa.engine.Connection, table: str) -> set[str]:
    return {str(idx["name"]) for idx in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, _GROUP_TABLE):
        op.create_table(
            _GROUP_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "workspace_id",
                sa.Integer(),
                sa.ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(length=80), nullable=False),
            sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_ungrouped", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("workspace_id", "name", name="uq_tables_tablegroup_ws_name"),
        )
        op.create_index("ix_tables_tablegroup_workspace_id", _GROUP_TABLE, ["workspace_id"])

    if _table_exists(bind, _TABLE_TABLE) and "group_id" not in _column_names(bind, _TABLE_TABLE):
        op.add_column(_TABLE_TABLE, sa.Column("group_id", sa.Integer(), nullable=True))
        # SQLite 不支持 ALTER TABLE ADD CONSTRAINT（外键），保留普通列；
        # 分组删除由接口显式把成员表置 NULL，口径不依赖库级 FK。
        if bind.dialect.name != "sqlite":
            op.create_foreign_key(
                "fk_tables_datatable_group_id",
                _TABLE_TABLE,
                _GROUP_TABLE,
                ["group_id"],
                ["id"],
                ondelete="SET NULL",
            )
    if _table_exists(bind, _TABLE_TABLE) and "ix_tables_datatable_group_id" not in _index_names(bind, _TABLE_TABLE):
        op.create_index("ix_tables_datatable_group_id", _TABLE_TABLE, ["group_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, _TABLE_TABLE):
        if "ix_tables_datatable_group_id" in _index_names(bind, _TABLE_TABLE):
            op.drop_index("ix_tables_datatable_group_id", table_name=_TABLE_TABLE)
        if "group_id" in _column_names(bind, _TABLE_TABLE):
            # SQLite 不支持直接 DROP COLUMN 的外键约束 → 批量模式重建表
            with op.batch_alter_table(_TABLE_TABLE) as batch:
                batch.drop_column("group_id")
    if _table_exists(bind, _GROUP_TABLE):
        op.drop_index("ix_tables_tablegroup_workspace_id", table_name=_GROUP_TABLE)
        op.drop_table(_GROUP_TABLE)
