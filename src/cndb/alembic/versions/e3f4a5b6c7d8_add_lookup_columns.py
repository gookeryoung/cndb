"""add_lookup_redundant_columns — lookup 冗余列与排序索引（ADR 0131）.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-11-11 10:00:00.000000

为每个未回收 lookup 字段在持有它的物理表上补齐：
- ``_lk_<db_column>``        多值 U+001F 拼接值 / 单值原值
- ``_lk_<db_column>_first``  最小解析值（升序排序）
- ``_lk_<db_column>_max``    最大解析值（降序排序 / 多值比较）
并创建 ``_first`` 的 B-tree 索引。

迁移可重入：列 / 索引均已存在时跳过；随后按批回填历史数据（同样幂等）。
回填复用迁移连接（SQLite 下新列对其它连接不可见），因此不会卡库。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from cndb.plugins.tables.services.core.lookup_columns import lookup_column_names_for

revision: str = "e3f4a5b6c7d8"
down_revision: str | Sequence[str] | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_FIELD_TABLE = "tables_datafield"
_TABLE_TABLE = "tables_datatable"


def _table_exists(bind: sa.engine.Connection, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def _column_names(bind: sa.engine.Connection, table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(bind).get_columns(table)}


def _lookup_targets(bind: sa.engine.Connection) -> list[tuple[int, str, str]]:
    """读取 (字段 id, 物理表名, db_column_name)；物理表或元数据表缺失时返回空."""
    if not _table_exists(bind, _FIELD_TABLE) or not _table_exists(bind, _TABLE_TABLE):
        return []
    rows = bind.execute(
        sa.text(
            f"SELECT f.id, t.db_table_name, f.db_column_name "
            f"FROM {_FIELD_TABLE} f JOIN {_TABLE_TABLE} t ON t.id = f.table_id "
            "WHERE f.field_type = 'lookup' AND f.trashed = 0"
        )
    ).all()
    return [(int(r[0]), str(r[1]), str(r[2])) for r in rows]


def _names(db_column: str) -> tuple[str, str, str]:
    return lookup_column_names_for(db_column)


def _physical_columns() -> dict[str, list[str]]:
    physical: dict[str, list[str]] = {}
    for _field_id, table_name, db_column in _lookup_targets(op.get_bind()):
        physical.setdefault(table_name, []).append(db_column)
    return physical


def _add_columns() -> int:
    bind = op.get_bind()
    col_type = "BLOB" if bind.dialect.name == "sqlite" else "TEXT"
    changed = 0
    for table_name, db_columns in _physical_columns().items():
        if not _table_exists(bind, table_name):
            logger.warning("[0131] 物理表 %s 不存在，跳过冗余列补齐", table_name)
            continue
        existing = _column_names(bind, table_name)
        for db_column in db_columns:
            names = _names(db_column)
            for name in names:
                if name in existing:
                    continue
                bind.execute(sa.text(f'ALTER TABLE "{table_name}" ADD COLUMN "{name}" {col_type}'))
                existing.add(name)
                changed += 1
            first = names[1]
            bind.execute(sa.text(f'CREATE INDEX IF NOT EXISTS "ix_{table_name}_{first}" ON "{table_name}" ("{first}")'))
    return changed


def _backfill() -> int:
    """按批回填历史数据（复用迁移连接）；单表失败只记录，不阻塞迁移."""
    from sqlalchemy.orm import Session

    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.tables.services.core.lookup_sync import backfill_lookup_columns

    bind = op.get_bind()
    # 极简 / 残缺库（元数据表未建）没有 lookup 字段可回填，直接跳过
    if not _table_exists(bind, _FIELD_TABLE) or not _table_exists(bind, _TABLE_TABLE):
        return 0
    db = Session(bind=bind)
    processed = 0
    try:
        tables = db.query(DataTable).filter(DataTable.trashed == False).all()  # noqa: E712
        for table in tables:
            if not any(f.field_type == "lookup" and not f.trashed for f in table.active_fields()):
                continue
            try:
                processed += backfill_lookup_columns(
                    bind.engine,
                    table,
                    db=db,
                    conn=bind,
                    bind=bind,
                )
            except Exception:  # pragma: no cover - 单表失败不阻塞其它表
                logger.warning(
                    "[0131] 表 %s 回填失败，可稍后用 cndb lookup backfill 重跑",
                    table.name,
                    exc_info=True,
                )
    finally:
        db.close()
    return processed


def upgrade() -> None:
    changed = _add_columns()
    rows = _backfill()
    logger.info("[0131] lookup 冗余列迁移完成：新增列 %d，回填行 %d", changed, rows)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name, db_columns in _physical_columns().items():
        if not _table_exists(bind, table_name):
            continue
        existing = _column_names(bind, table_name)
        target_names = [name for db_column in db_columns for name in _names(db_column) if name in existing]
        if not target_names:
            continue
        for db_column in db_columns:
            first = _names(db_column)[1]
            bind.execute(sa.text(f'DROP INDEX IF EXISTS "ix_{table_name}_{first}"'))
        with op.batch_alter_table(table_name) as batch:
            for name in target_names:
                batch.drop_column(name)
