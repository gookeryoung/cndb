"""设计版本 change_type 迁移 3b5d7f9a1c2e 往返测试（ADR 0113 P0：幂等 + 存量默认 manual）."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from cndb.core.migrations import _build_config

REVISION = "3b5d7f9a1c2e"
PREVIOUS = "2a4c6e8f0b1d"
TABLE = "design_designversion"


def _upgrade(url: str, revision: str = REVISION) -> None:
    command.upgrade(_build_config(url), revision)


def _downgrade(url: str, revision: str) -> None:
    command.downgrade(_build_config(url), revision)


def _columns(db_path: Path, table: str = TABLE) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}  # nosec B608 - 测试内部常量
    finally:
        conn.close()


def _insert_legacy_version(db_path: Path) -> None:
    """在迁移前结构里插入设计与版本行（无 change_type 列）."""
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            "INSERT INTO design_design (workspace_id, title, kind, file_key, folder, content, compiled,"
            " description, dependencies, dependencies_stale, is_deleted, created_at, updated_at)"
            " VALUES (1, 'legacy', 'assembly', 'legacy', '', 'box(size = [1, 1, 1])', '{}', '', '[]', 0, 0,"
            " datetime('now'), datetime('now'))"
        )
        design_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO design_designversion (design_id, workspace_id, version_number, content, compiled,"
            " dependencies, comment, created_at, updated_at)"
            " VALUES (?, 1, 1, 'box(size = [1, 1, 1])', '{}', '[]', '历史版本', datetime('now'), datetime('now'))",
            (design_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _change_types(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return [row[0] for row in conn.execute(f"SELECT change_type FROM {TABLE}").fetchall()]  # nosec B608
    finally:
        conn.close()


class TestDesignVersionChangeTypeMigration:
    def test_upgrade_adds_column_and_backfills_manual(self, tmp_path: Path):
        db_path = tmp_path / "design.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, PREVIOUS)
        _insert_legacy_version(db_path)
        _upgrade(url)
        assert "change_type" in _columns(db_path)
        assert _change_types(db_path) == ["manual"], "存量行由默认值补齐，零数据改写"

    def test_upgrade_idempotent(self, tmp_path: Path):
        db_path = tmp_path / "idem.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _upgrade(url)
        assert "change_type" in _columns(db_path)

    def test_downgrade_drops_column(self, tmp_path: Path):
        db_path = tmp_path / "down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)
        assert "change_type" not in _columns(db_path)
        # 再升级幂等
        _upgrade(url)
        assert "change_type" in _columns(db_path)
