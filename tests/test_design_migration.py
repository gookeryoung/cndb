"""设计模块迁移 z4a5b6c7d8e9 往返测试（ADR 0079 P0）."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from cndb.core.migrations import _build_config

REVISION = "z4a5b6c7d8e9"
PREVIOUS = "y3z4a5b6c7d8"
DESIGN = "design_design"
VERSION = "design_designversion"


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


def _indexes(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in conn.execute(f"PRAGMA index_list({table})").fetchall()}  # nosec B608 - 测试内部常量
    finally:
        conn.close()


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}  # nosec B608 - 测试内部常量
    finally:
        conn.close()


def _unique_index_count(db_path: Path, table: str) -> int:
    """PRAGMA index_list 统计唯一索引个数（唯一约束存在性）."""
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"PRAGMA index_list({table})").fetchall()  # nosec B608 - 测试内部常量
        return sum(1 for row in rows if row[2] == 1)
    finally:
        conn.close()


class TestDesignMigration:
    def test_upgrade_creates_tables_and_indexes(self, tmp_path: Path):
        db_path = tmp_path / "design.db"
        _upgrade(f"sqlite:///{db_path}")

        tables = _tables(db_path)
        assert {DESIGN, VERSION} <= tables
        assert "ix_design_design_workspace_id" in _indexes(db_path, DESIGN)
        assert "ix_design_design_ws_updated" in _indexes(db_path, DESIGN)
        assert "ix_design_designversion_design_id" in _indexes(db_path, VERSION)
        assert "ix_design_designversion_ws_created" in _indexes(db_path, VERSION)

    def test_unique_constraints_exist(self, tmp_path: Path):
        """(workspace_id, title) 与 (design_id, version_number) 各建唯一约束.

        SQLite 下唯一约束索引名为自动生成（sqlite_autoindex_*），按唯一标志统计。
        """
        db_path = tmp_path / "design_unique.db"
        _upgrade(f"sqlite:///{db_path}")
        assert _unique_index_count(db_path, DESIGN) == 1
        assert _unique_index_count(db_path, VERSION) == 1

    def test_schema_matches_models(self, tmp_path: Path):
        from cndb.plugins.design.models import DesignDesign, DesignDesignVersion

        db_path = tmp_path / "design_model.db"
        _upgrade(f"sqlite:///{db_path}")
        assert _columns(db_path, DESIGN) == {column.name for column in DesignDesign.__table__.columns}
        assert _columns(db_path, VERSION) == {column.name for column in DesignDesignVersion.__table__.columns}

    def test_downgrade_removes_tables(self, tmp_path: Path):
        db_path = tmp_path / "design_down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)
        assert {DESIGN, VERSION}.isdisjoint(_tables(db_path))

    def test_reupgrade_after_downgrade(self, tmp_path: Path):
        db_path = tmp_path / "design_round.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)
        _upgrade(url)
        assert {DESIGN, VERSION} <= _tables(db_path)

    def test_upgrade_idempotent_when_tables_exist(self, tmp_path: Path):
        """create_all 已建表：stamp 到上一版再 upgrade，迁移跳过建表不报错."""
        from sqlalchemy import create_engine

        import cndb.core.events
        import cndb.plugins.accounts.models
        import cndb.plugins.design.models
        import cndb.plugins.documents.models
        import cndb.plugins.pipeline.models
        import cndb.plugins.tables.models
        import cndb.plugins.workspaces.models  # noqa: F401
        from cndb.models.base import Base

        db_path = tmp_path / "design_idempotent.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        engine.dispose()

        command.stamp(_build_config(url), PREVIOUS)
        _upgrade(url)
        assert {DESIGN, VERSION} <= _tables(db_path)
