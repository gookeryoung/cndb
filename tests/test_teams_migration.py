"""团队迁移 e7d8c9b0a1f2 往返测试（ADR 0153 P1：幂等、存量零迁移、downgrade 可还原）.

H13 口径：不回填任何存量数据（`team_id` 全空 ⇒ 判定与升级前逐条一致，I3）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from cndb.core.migrations import _build_config

REVISION = "e7d8c9b0a1f2"
PREVIOUS = "b7c8d9e0f1a2"
TEAM = "workspaces_team"
TEAM_MEMBER = "workspaces_team_member"
WORKSPACE = "workspaces_workspace"


def _upgrade(url: str, revision: str = REVISION) -> None:
    command.upgrade(_build_config(url), revision)


def _downgrade(url: str, revision: str) -> None:
    command.downgrade(_build_config(url), revision)


def _tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}  # nosec B608 - 测试内部常量
    finally:
        conn.close()


def _insert_workspace(db_path: Path, name: str) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            f"INSERT INTO {WORKSPACE} (name, description, visibility, tags, allow_edit, modules, created_at, updated_at) "  # nosec B608
            "VALUES (?, '', 'member', '[]', 1, '[\"tables\"]', datetime('now'), datetime('now'))",
            (name,),
        )
        conn.commit()
    finally:
        conn.close()


def _team_ids(db_path: Path) -> dict[str, int | None]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"SELECT name, team_id FROM {WORKSPACE}").fetchall()  # nosec B608
        return dict(rows)
    finally:
        conn.close()


class TestTeamsMigration:
    def test_upgrade_creates_tables_and_column(self, tmp_path: Path):
        db_path = tmp_path / "teams.db"
        _upgrade(f"sqlite:///{db_path}")
        tables = _tables(db_path)
        assert TEAM in tables
        assert TEAM_MEMBER in tables
        assert "team_id" in _columns(db_path, WORKSPACE)
        # 单层扁平：不建 parent_team_id（D2 / I7）
        assert "parent_team_id" not in _columns(db_path, TEAM)

    def test_existing_workspaces_are_not_backfilled(self, tmp_path: Path):
        """存量零迁移（H13 / I3）：升级后 team_id 全为 NULL，判定与升级前一致."""
        db_path = tmp_path / "backfill.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, PREVIOUS)
        _insert_workspace(db_path, "存量工作区A")
        _insert_workspace(db_path, "存量工作区B")
        _upgrade(url)

        assert _team_ids(db_path) == {"存量工作区A": None, "存量工作区B": None}

    def test_upgrade_is_idempotent(self, tmp_path: Path):
        db_path = tmp_path / "idem.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _upgrade(url)
        assert TEAM in _tables(db_path)
        assert "team_id" in _columns(db_path, WORKSPACE)

    def test_downgrade_removes_everything(self, tmp_path: Path):
        db_path = tmp_path / "down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)

        tables = _tables(db_path)
        assert TEAM not in tables
        assert TEAM_MEMBER not in tables
        assert "team_id" not in _columns(db_path, WORKSPACE)
