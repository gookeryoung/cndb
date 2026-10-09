"""add_missing_model_columns — 补齐 ORM 模型有而迁移链缺失的列.

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-10-09 09:00:00.000000

背景：以下列历史上只加在了 ORM 模型上（靠 create_all 建新库生效），迁移链
从未覆盖。旧库（典型：恢复 0.2.0 native 备份后执行 upgrade head）永远缺列，
业务查询 SELECT 全列直接报 "no such column"（表现为恢复后所有数据表内容
无法显示）。schema 自愈层因 NOT NULL 且无 server_default 拒绝补建，缺列
持续存在。本迁移把缺口一次性补齐。

关键约束 —— 幂等加列：部分旧库（如 0.2.0 时代经 seed/create_all 建表后再
备份的库）已经带有其中部分列，逐列检查存在性后才 add_column，避免
"duplicate column name" 中断恢复迁移。

- accounts_user.role          String(32)  NOT NULL DEFAULT 'user'（角色字段）
- tables_dataview.is_public   Boolean     NOT NULL DEFAULT 0（公开分享开关）
- tables_dataview.public_slug String(12)  NULL，唯一索引（分享标识）
- tables_tablepermission.manage_data_role String(16) NOT NULL DEFAULT ''
  （数据治理角色阈值；恢复 0.2.0 备份后缺此列是"表内容无法显示"的直接根因）

链上加列迁移均不建 FK（既有先例，SQLite 不支持裸 ALTER 加约束）。
"""
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set[str]:
    """读取表当前已有的列名集合（表不存在时返回空集）."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _table_exists(table: str) -> bool:
    """目标表是否存在（不存在则整表由启动 create_all 兜底，本迁移跳过）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _add_column_if_missing(table: str, column: sa.Column[str]) -> None:
    """列不存在才 add_column（幂等，兼容 create_all 时代已含该列的旧库）.

    表整体不存在时直接跳过——该场景由启动期 create_all 按完整 ORM 元数据
    建表，本迁移只负责存量表的缺列。
    """
    if not _table_exists(table) or column.name in _existing_columns(table):
        return
    op.add_column(table, column)


def upgrade() -> None:
    """Upgrade schema: 逐列检查后补齐四个模型列与分享标识索引."""
    _add_column_if_missing(
        "accounts_user",
        sa.Column("role", sa.String(32), nullable=False, server_default="user"),
    )
    _add_column_if_missing(
        "tables_dataview",
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing(
        "tables_dataview",
        sa.Column("public_slug", sa.String(12), nullable=True),
    )
    # 唯一索引按名称幂等创建（列已存在的旧库由启动自愈层兜底补索引）
    if _table_exists("tables_dataview"):
        insp = sa.inspect(op.get_bind())
        idx_names = {i["name"] for i in insp.get_indexes("tables_dataview")}
        if "ix_tables_dataview_public_slug" not in idx_names:
            op.create_index(
                op.f("ix_tables_dataview_public_slug"),
                "tables_dataview",
                ["public_slug"],
                unique=True,
            )
    _add_column_if_missing(
        "tables_tablepermission",
        sa.Column("manage_data_role", sa.String(16), nullable=False, server_default=""),
    )


def downgrade() -> None:
    """Downgrade schema: 移除本迁移新增的列与索引（缺表或缺列时跳过）."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    table_names = set(insp.get_table_names())
    if "tables_dataview" in table_names:
        idx_names = {i["name"] for i in insp.get_indexes("tables_dataview")}
        if "ix_tables_dataview_public_slug" in idx_names:
            op.drop_index(op.f("ix_tables_dataview_public_slug"), table_name="tables_dataview")
        dv_cols = {c["name"] for c in insp.get_columns("tables_dataview")}
        if "public_slug" in dv_cols:
            op.drop_column("tables_dataview", "public_slug")
        if "is_public" in dv_cols:
            op.drop_column("tables_dataview", "is_public")
    if "tables_tablepermission" in table_names:
        tp_cols = {c["name"] for c in insp.get_columns("tables_tablepermission")}
        if "manage_data_role" in tp_cols:
            op.drop_column("tables_tablepermission", "manage_data_role")
    if "accounts_user" in table_names:
        user_cols = {c["name"] for c in insp.get_columns("accounts_user")}
        if "role" in user_cols:
            op.drop_column("accounts_user", "role")
