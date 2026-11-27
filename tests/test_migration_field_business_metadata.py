"""迁移 a7b8c9d0e1f2（add_field_business_metadata）回归测试（ADR 0188 C3 / H13）.

本迁移为 `tables_datafield` 补 6 列业务元数据。约束与既有迁移同类：

- 幂等：create_all 时代旧库可能已含这些列（全量建库后 stamp 回旧版重放）；
- 存量零迁移：旧行读出为 NULL（「未填写」），行为与升级前一致；
- downgrade 可还原：逆序删索引与列，重复执行不报错。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from cndb.core.migrations import _build_config, upgrade_to_head

PRE_REVISION = "e0f1a2b3c4d6"  # 本迁移之前的 head（ADR 0177 P3）
NEW_COLUMNS = {
    "business_meaning",
    "unit",
    "sensitivity",
    "owner_id",
    "standard_ref",
    "example_value",
}


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}  # nosec B608 - 测试内部常量表名
    finally:
        conn.close()


def _indexes(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA index_list({table})").fetchall()}  # nosec B608
    finally:
        conn.close()


def test_upgrade_adds_business_metadata_columns(tmp_path: Path) -> None:
    """升级后 6 列与 owner_id 索引存在，且存量行读为空."""
    db_path = tmp_path / "old.db"
    url = f"sqlite:///{db_path.as_posix()}"
    command.upgrade(_build_config(url), PRE_REVISION)
    assert not NEW_COLUMNS & _columns(db_path, "tables_datafield")

    # 旧行（升级前写入）：先插一条，验证升级后读出 NULL
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            'INSERT INTO tables_datatable (workspace_id, name, description, db_table_name, "order", trashed)'
            " VALUES (1, 'T', '', 'table_x', 0, 0)"
        )
        conn.execute(
            "INSERT INTO tables_datafield (table_id, name, field_type, db_column_name, config,"
            ' required, is_unique, hidden, "order", trashed)'
            " VALUES (1, 'A', 'text', 'field_x', '{}', 0, 0, 0, 0, 0)"
        )
        conn.commit()
    finally:
        conn.close()

    upgrade_to_head(url)

    assert _columns(db_path, "tables_datafield") >= NEW_COLUMNS
    assert "ix_tables_datafield_owner_id" in _indexes(db_path, "tables_datafield")

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT business_meaning, unit, sensitivity, owner_id, standard_ref, example_value"
            " FROM tables_datafield WHERE name = 'A'"
        ).fetchone()
    finally:
        conn.close()
    assert row == (None, None, None, None, None, None)


def test_upgrade_is_idempotent(tmp_path: Path) -> None:
    """重复 upgrade 不报错（列已存在即跳过）."""
    db_path = tmp_path / "idem.db"
    url = f"sqlite:///{db_path.as_posix()}"
    upgrade_to_head(url)
    upgrade_to_head(url)
    assert _columns(db_path, "tables_datafield") >= NEW_COLUMNS


def test_downgrade_removes_columns(tmp_path: Path) -> None:
    """downgrade 回到 PRE_REVISION：列与索引都消失."""
    db_path = tmp_path / "down.db"
    url = f"sqlite:///{db_path.as_posix()}"
    upgrade_to_head(url)
    assert _columns(db_path, "tables_datafield") >= NEW_COLUMNS

    command.downgrade(_build_config(url), PRE_REVISION)

    assert not NEW_COLUMNS & _columns(db_path, "tables_datafield")
    assert "ix_tables_datafield_owner_id" not in _indexes(db_path, "tables_datafield")
