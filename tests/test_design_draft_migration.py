"""设计个人草稿迁移 c1d2e3f4a5b7 往返测试（ADR 0125 P0）."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from cndb.core.migrations import _build_config

REVISION = "c1d2e3f4a5b7"
PREVIOUS = "b0c1d2e3f4a5"
TABLE = "design_designdraft"


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


class TestDesignDraftMigration:
    def test_upgrade_creates_table_and_columns(self, tmp_path: Path):
        db_path = tmp_path / "draft.db"
        _upgrade(f"sqlite:///{db_path}")
        assert TABLE in _tables(db_path)
        assert _columns(db_path, TABLE) == {
            "id",
            "design_id",
            "user_id",
            "content",
            "content_size",
            "content_hash",
            "base_version_number",
            "created_at",
            "updated_at",
        }

    def test_upgrade_idempotent(self, tmp_path: Path):
        db_path = tmp_path / "idem.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _upgrade(url)
        assert TABLE in _tables(db_path)

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
        assert TABLE in _tables(db_path)

    def test_downgrade_drops_table(self, tmp_path: Path):
        db_path = tmp_path / "down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)
        assert TABLE not in _tables(db_path)
        assert "design_design" in _tables(db_path)
        assert "design_designversion" in _tables(db_path)
