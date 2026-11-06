"""设计模块迁移往返测试（ADR 0079 P0 / ADR 0086 P0：文件库列 + 唯一键换轨 + 引用表）."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from cndb.core.migrations import _build_config

REVISION = "c8e2f4a6b8d0"
HEAD = "3b5d7f9a1c2e"  # 当前 alembic head：设计版本 change_type（ADR 0113）
PREVIOUS = "z4a5b6c7d8e9"
DESIGN = "design_design"
VERSION = "design_designversion"
REF = "design_designref"

NEW_COLUMNS = {"kind", "file_key", "folder", "dependencies", "dependencies_stale", "refactored_from_version"}


def _upgrade(url: str, revision: str = REVISION) -> None:
    command.upgrade(_build_config(url), revision)


def _downgrade(url: str, revision: str) -> None:
    command.downgrade(_build_config(url), revision)


def _conn(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path))


def _tables(db_path: Path) -> set[str]:
    with _conn(db_path) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _indexes(db_path: Path, table: str) -> set[str]:
    with _conn(db_path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA index_list({table})").fetchall()}  # nosec B608 - 测试内部常量


def _columns(db_path: Path, table: str) -> set[str]:
    with _conn(db_path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}  # nosec B608 - 测试内部常量


def _unique_index_count(db_path: Path, table: str) -> int:
    """PRAGMA index_list 统计唯一索引个数（唯一约束存在性）."""
    with _conn(db_path) as conn:
        rows = conn.execute(f"PRAGMA index_list({table})").fetchall()  # nosec B608 - 测试内部常量
        return sum(1 for row in rows if row[2] == 1)


class TestDesignMigration:
    def test_upgrade_creates_tables_and_indexes(self, tmp_path: Path):
        db_path = tmp_path / "design.db"
        _upgrade(f"sqlite:///{db_path}")

        tables = _tables(db_path)
        assert {DESIGN, VERSION, REF} <= tables
        assert "ix_design_design_ws_updated" in _indexes(db_path, DESIGN)
        assert "ix_design_designversion_design_id" in _indexes(db_path, VERSION)
        assert "ix_design_designref_target" in _indexes(db_path, REF)
        assert "ix_design_designref_ws" in _indexes(db_path, REF)

    def test_unique_constraints_swapped(self, tmp_path: Path):
        """唯一键换轨：(ws, folder, title) + (ws, file_key) 替代 (ws, title)."""
        db_path = tmp_path / "design_unique.db"
        _upgrade(f"sqlite:///{db_path}")
        assert _unique_index_count(db_path, DESIGN) == 2
        assert _unique_index_count(db_path, VERSION) == 1
        assert _unique_index_count(db_path, REF) == 1

    def test_schema_matches_models(self, tmp_path: Path):
        from cndb.plugins.design.models import DesignDesign, DesignDesignref, DesignDesignVersion

        db_path = tmp_path / "design_model.db"
        _upgrade(f"sqlite:///{db_path}", HEAD)
        assert _columns(db_path, DESIGN) == {column.name for column in DesignDesign.__table__.columns}
        assert _columns(db_path, VERSION) == {column.name for column in DesignDesignVersion.__table__.columns}
        assert _columns(db_path, REF) == {column.name for column in DesignDesignref.__table__.columns}

    def test_legacy_file_key_backfilled(self, tmp_path: Path):
        """z4a5 旧库升级：存量行 file_key 回填 design-<id>，kind 缺省 assembly."""
        db_path = tmp_path / "design_legacy.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, PREVIOUS)
        with _conn(db_path) as conn:
            conn.execute(
                f"INSERT INTO {DESIGN} (workspace_id, title, content, compiled, description, is_deleted, created_at, updated_at)"  # nosec B608 - 测试常量
                " VALUES (1, '支架', '', '{}', '', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
            conn.commit()
        _upgrade(url)
        with _conn(db_path) as conn:
            kind, file_key, folder = conn.execute(
                f"SELECT kind, file_key, folder FROM {DESIGN} WHERE title = '支架'"  # nosec B608 - 测试常量
            ).fetchone()
        assert (kind, file_key, folder) == ("assembly", "design-1", "")

    def test_downgrade_restores_old_schema(self, tmp_path: Path):
        db_path = tmp_path / "design_down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)
        assert REF not in _tables(db_path)
        assert NEW_COLUMNS.isdisjoint(_columns(db_path, DESIGN))
        assert "dependencies" not in _columns(db_path, VERSION)
        assert _unique_index_count(db_path, DESIGN) == 1

    def test_downgrade_restores_refactored_content(self, tmp_path: Path):
        """D12：refactored_from_version 非空的设计 downgrade 时从该版本行还原 content/compiled."""
        db_path = tmp_path / "design_refactor_down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        with _conn(db_path) as conn:
            conn.execute(
                f"INSERT INTO {DESIGN} (workspace_id, title, kind, file_key, folder, content, compiled, description, refactored_from_version, is_deleted, created_at, updated_at)"  # nosec B608 - 测试常量
                " VALUES (1, '支架', 'assembly', 'design-1', '', 'use \"x\"()', '{}', '', 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
            conn.execute(
                f"INSERT INTO {VERSION} (design_id, workspace_id, version_number, content, compiled, comment, created_at)"  # nosec B608 - 测试常量
                " VALUES (1, 1, 1, 'module m() {\n  box(size=[1,1,1])\n}\nm()', '{\"legacy\": true}', '', CURRENT_TIMESTAMP)"
            )
            conn.commit()
        _downgrade(url, PREVIOUS)
        with _conn(db_path) as conn:
            content, compiled = conn.execute(
                f"SELECT content, compiled FROM {DESIGN} WHERE title = '支架'"  # nosec B608 - 测试常量
            ).fetchone()
        assert content == "module m() {\n  box(size=[1,1,1])\n}\nm()"
        assert compiled == '{"legacy": true}'

    def test_reupgrade_after_downgrade(self, tmp_path: Path):
        db_path = tmp_path / "design_round.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)
        _upgrade(url)
        assert {DESIGN, VERSION, REF} <= _tables(db_path)
        assert _columns(db_path, DESIGN) >= NEW_COLUMNS

    def test_upgrade_idempotent_when_tables_exist(self, tmp_path: Path):
        """create_all 已按新模型建表：stamp 到上一版再 upgrade，不报错且补齐引用表."""
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
        assert {DESIGN, VERSION, REF} <= _tables(db_path)
        assert _columns(db_path, DESIGN) >= NEW_COLUMNS
