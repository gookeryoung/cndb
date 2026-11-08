"""工作区项目上下文迁移 b0c1d2e3f4a5 往返测试（ADR 0122 P0）."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from alembic import command

from cndb.core.migrations import _build_config

REVISION = "b0c1d2e3f4a5"
PREVIOUS = "d7e8f9a0b1c2"
WORKSPACE = "workspaces_workspace"
STATE = "workspaces_workspace_project_state"
DOC = "workspaces_workspace_project_document"


def _upgrade(url: str, revision: str = REVISION) -> None:
    command.upgrade(_build_config(url), revision)


def _downgrade(url: str, revision: str) -> None:
    command.downgrade(_build_config(url), revision)


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}  # nosec B608
    finally:
        conn.close()


def _tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()


def _insert_legacy(db_path: Path, name: str) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            f"INSERT INTO {WORKSPACE} (name, description, visibility, tags, allow_edit, modules, created_at, updated_at) "  # nosec B608
            "VALUES (?, '', 'member', '[]', 1, ?, datetime('now'), datetime('now'))",
            (name, json.dumps(["tables", "documents"])),
        )
        conn.commit()
    finally:
        conn.close()


class TestWorkspaceProjectContextMigration:
    def test_upgrade_adds_mode_and_tables(self, tmp_path: Path):
        db_path = tmp_path / "ws.db"
        _upgrade(f"sqlite:///{db_path}")
        assert "project_mode" in _columns(db_path, WORKSPACE)
        tables = _tables(db_path)
        assert STATE in tables and DOC in tables

    def test_legacy_workspace_defaults_to_workspace_mode(self, tmp_path: Path):
        db_path = tmp_path / "legacy.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, PREVIOUS)
        _insert_legacy(db_path, "旧工作区")
        _upgrade(url)

        conn = sqlite3.connect(str(db_path))
        try:
            mode = conn.execute(f"SELECT project_mode FROM {WORKSPACE}").fetchone()[0]  # nosec B608
        finally:
            conn.close()
        assert mode == "workspace"

    def test_upgrade_idempotent(self, tmp_path: Path):
        db_path = tmp_path / "idem.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _upgrade(url)
        assert "project_mode" in _columns(db_path, WORKSPACE)

    def test_upgrade_on_create_all_schema(self, tmp_path: Path):
        from sqlalchemy import create_engine

        import cndb.core.events
        import cndb.plugins.accounts.models
        import cndb.plugins.design.models
        import cndb.plugins.documents.models
        import cndb.plugins.pipeline.models
        import cndb.plugins.tables.models
        import cndb.plugins.workspaces.models  # noqa: F401
        from cndb.models.base import Base

        db_path = tmp_path / "create_all.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        engine.dispose()

        command.stamp(_build_config(url), PREVIOUS)
        _upgrade(url)
        assert "project_mode" in _columns(db_path, WORKSPACE)

    def test_downgrade_removes_context(self, tmp_path: Path):
        db_path = tmp_path / "down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)
        assert "project_mode" not in _columns(db_path, WORKSPACE)
        tables = _tables(db_path)
        assert STATE not in tables and DOC not in tables
