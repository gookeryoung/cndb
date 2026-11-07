"""复用模块库迁移：四表建 / 删与模型一致（ADR 0118 P0）."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from cndb.core.migrations import _build_config

HEAD = "d7e8f9a0b1c2"
PREVIOUS = "4c6e8a0b2d3f"
TABLES = (
    "design_library_module",
    "design_library_version",
    "design_libraryref",
    "design_library_vendor",
)


def _tables(db_path: Path) -> set[str]:
    with sqlite3.connect(str(db_path)) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _columns(db_path: Path, table: str) -> set[str]:
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}  # nosec B608


def _indexes(db_path: Path, table: str) -> set[str]:
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA index_list({table})").fetchall()}  # nosec B608


def test_upgrade_creates_tables_and_downgrade_drops(tmp_path: Path):
    db_path = tmp_path / "design_library.db"
    url = f"sqlite:///{db_path}"
    command.upgrade(_build_config(url), HEAD)

    assert set(TABLES) <= _tables(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        unique = [row for row in conn.execute(f"PRAGMA index_list({TABLES[0]})").fetchall() if row[2] == 1]  # nosec B608
    assert unique, "module_key 唯一约束应存在"
    assert "ix_design_library_module_visibility_updated" in _indexes(db_path, TABLES[0])
    assert "ix_design_libraryref_ws" in _indexes(db_path, TABLES[2])

    from cndb.plugins.design.models import (
        DesignLibraryModule,
        DesignLibraryref,
        DesignLibraryVendor,
        DesignLibraryVersion,
    )

    assert _columns(db_path, TABLES[0]) == {column.name for column in DesignLibraryModule.__table__.columns}
    assert _columns(db_path, TABLES[1]) == {column.name for column in DesignLibraryVersion.__table__.columns}
    assert _columns(db_path, TABLES[2]) == {column.name for column in DesignLibraryref.__table__.columns}
    assert _columns(db_path, TABLES[3]) == {column.name for column in DesignLibraryVendor.__table__.columns}

    command.downgrade(_build_config(url), PREVIOUS)
    assert not (set(TABLES) & _tables(db_path))
