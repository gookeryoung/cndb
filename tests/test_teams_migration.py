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


VISIBILITY_REVISION = "f2b3c4d5e6a7"
TEAMS_REVISION = "e7d8c9b0a1f2"


def _visibility_by_name(db_path: Path) -> dict[str, str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"SELECT name, visibility FROM {WORKSPACE}").fetchall()  # nosec B608
        return dict(rows)
    finally:
        conn.close()


def _insert_workspace_with_visibility(db_path: Path, name: str, visibility: str) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            f"INSERT INTO {WORKSPACE} (name, description, visibility, tags, allow_edit, modules, created_at, updated_at) "  # nosec B608
            "VALUES (?, '', ?, '[]', 1, '[\"tables\"]', datetime('now'), datetime('now'))",
            (name, visibility),
        )
        conn.commit()
    finally:
        conn.close()


class TestVisibilityNormalization:
    """D6 / P2 补充：存量 `private` 归一为 `member`（行为与升级前一致）。"""

    def test_private_is_normalized_to_member(self, tmp_path: Path):
        db_path = tmp_path / "vis.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, TEAMS_REVISION)
        for name, visibility in (("私有一", "private"), ("成员二", "member"), ("公开三", "public")):
            _insert_workspace_with_visibility(db_path, name, visibility)

        _upgrade(url, VISIBILITY_REVISION)
        assert _visibility_by_name(db_path) == {"私有一": "member", "成员二": "member", "公开三": "public"}

    def test_normalization_is_idempotent(self, tmp_path: Path):
        db_path = tmp_path / "vis_idem.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, TEAMS_REVISION)
        _insert_workspace_with_visibility(db_path, "私有一", "private")
        _upgrade(url, VISIBILITY_REVISION)
        _upgrade(url, VISIBILITY_REVISION)
        assert _visibility_by_name(db_path) == {"私有一": "member"}

    def test_downgrade_keeps_data_and_is_noop(self, tmp_path: Path):
        """downgrade 空操作：旧版不读 visibility，回滚数据会篡改用户意图."""
        db_path = tmp_path / "vis_down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, TEAMS_REVISION)
        _insert_workspace_with_visibility(db_path, "私有一", "private")
        _upgrade(url, VISIBILITY_REVISION)
        _downgrade(url, TEAMS_REVISION)
        assert _visibility_by_name(db_path) == {"私有一": "member"}

    def test_skips_missing_table(self, tmp_path: Path):
        db_path = tmp_path / "vis_missing.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, TEAMS_REVISION)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(f"DROP TABLE {WORKSPACE}")  # nosec B608 - 测试内部常量
            conn.commit()
        finally:
            conn.close()
        _upgrade(url, VISIBILITY_REVISION)  # 不抛错


LINKS_REVISION = "a9b8c7d6e5f4"
LINK_TABLE = "workspaces_workspacelink"


class TestWorkspaceLinksMigration:
    """ADR 0154 P0：链接表迁移（幂等 / 存量零迁移 / downgrade 可还原）."""

    def test_upgrade_creates_table(self, tmp_path: Path):
        db_path = tmp_path / "links.db"
        _upgrade(f"sqlite:///{db_path}", LINKS_REVISION)
        assert LINK_TABLE in _tables(db_path)
        cols = _columns(db_path, LINK_TABLE)
        assert {"workspace_id", "source_workspace_id", "target_table_id", "alias", "status"} <= cols
        # 链接不引入新的工作区层级列
        assert "parent_workspace_id" not in _columns(db_path, WORKSPACE)

    def test_existing_workspaces_untouched(self, tmp_path: Path):
        db_path = tmp_path / "links_backfill.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, VISIBILITY_REVISION)
        _insert_workspace(db_path, "存量工作区")
        before = _team_ids(db_path)
        _upgrade(url, LINKS_REVISION)
        assert _team_ids(db_path) == before == {"存量工作区": None}

    def test_upgrade_is_idempotent(self, tmp_path: Path):
        db_path = tmp_path / "links_idem.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, LINKS_REVISION)
        _upgrade(url, LINKS_REVISION)
        assert LINK_TABLE in _tables(db_path)

    def test_downgrade_drops_table(self, tmp_path: Path):
        db_path = tmp_path / "links_down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, LINKS_REVISION)
        _downgrade(url, VISIBILITY_REVISION)
        assert LINK_TABLE not in _tables(db_path)
        assert "team_id" in _columns(db_path, WORKSPACE)  # 只回滚链接表
