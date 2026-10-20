"""datasource M2：迁移 0a1b2c3d4e5f 往返测试（建表 / 幂等 / downgrade）."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from cndb.core.migrations import _build_config

REVISION = "1b2c3d4e5f60"
PREVIOUS = "e7f8a9b0c1d2"
SYNC_REVISION = "0a1b2c3d4e5f"
JOB_TABLE = "datasource_sync_job"
RUN_TABLE = "datasource_sync_run"
SESSION_TABLE = "datasource_session"


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


class TestMigration:
    def test_upgrade_creates_tables_and_indexes(self, tmp_path: Path):
        db_path = tmp_path / "mig.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)

        tables = _tables(db_path)
        assert {JOB_TABLE, RUN_TABLE} <= tables
        assert f"ix_{JOB_TABLE}_workspace_id" in _indexes(db_path, JOB_TABLE)
        assert f"ix_{JOB_TABLE}_lease_until" in _indexes(db_path, JOB_TABLE)
        assert f"ix_{RUN_TABLE}_job_id" in _indexes(db_path, RUN_TABLE)

    def test_schema_matches_models(self, tmp_path: Path):
        from cndb.plugins.datasource.models import DatasourceSyncJob, DatasourceSyncRun

        db_path = tmp_path / "mig_model.db"
        _upgrade(f"sqlite:///{db_path}")
        assert _columns(db_path, JOB_TABLE) == {column.name for column in DatasourceSyncJob.__table__.columns}
        assert _columns(db_path, RUN_TABLE) == {column.name for column in DatasourceSyncRun.__table__.columns}

    def test_downgrade_removes_tables(self, tmp_path: Path):
        db_path = tmp_path / "mig_down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)
        tables = _tables(db_path)
        assert JOB_TABLE not in tables
        assert RUN_TABLE not in tables

    def test_reupgrade_after_downgrade(self, tmp_path: Path):
        db_path = tmp_path / "mig_round.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)
        _upgrade(url)
        assert {JOB_TABLE, RUN_TABLE} <= _tables(db_path)

    def test_upgrade_idempotent_when_tables_exist(self, tmp_path: Path):
        """create_all 时代已建过表的库：stamp 到上一版再 upgrade，迁移跳过建表不报错."""
        from sqlalchemy import create_engine

        import cndb.core.events
        import cndb.plugins.accounts.models
        import cndb.plugins.datasource.models
        import cndb.plugins.tables.models
        import cndb.plugins.workspaces.models  # noqa: F401
        from cndb.models.base import Base

        db_path = tmp_path / "mig_idempotent.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        engine.dispose()

        command.stamp(_build_config(url), PREVIOUS)
        _upgrade(url)
        assert {JOB_TABLE, RUN_TABLE} <= _tables(db_path)


class TestSessionMigration:
    def test_upgrade_adds_session_table_and_job_columns(self, tmp_path: Path):
        db_path = tmp_path / "mig_session.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)

        assert SESSION_TABLE in _tables(db_path)
        job_columns = _columns(db_path, JOB_TABLE)
        assert {"session_id", "rate_limit_ms"} <= job_columns
        assert f"ix_{JOB_TABLE}_session_id" in _indexes(db_path, JOB_TABLE)

    def test_schema_matches_models(self, tmp_path: Path):
        from cndb.plugins.datasource.models import DatasourceSession

        db_path = tmp_path / "mig_session_model.db"
        _upgrade(f"sqlite:///{db_path}")
        assert _columns(db_path, SESSION_TABLE) == {column.name for column in DatasourceSession.__table__.columns}

    def test_downgrade_removes_session_artifacts(self, tmp_path: Path):
        db_path = tmp_path / "mig_session_down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, SYNC_REVISION)

        assert SESSION_TABLE not in _tables(db_path)
        job_columns = _columns(db_path, JOB_TABLE)
        assert "session_id" not in job_columns
        assert "rate_limit_ms" not in job_columns

    def test_upgrade_idempotent_after_create_all(self, tmp_path: Path):
        from sqlalchemy import create_engine

        import cndb.core.events
        import cndb.plugins.accounts.models
        import cndb.plugins.datasource.models
        import cndb.plugins.tables.models
        import cndb.plugins.workspaces.models  # noqa: F401
        from cndb.models.base import Base

        db_path = tmp_path / "mig_session_idempotent.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        engine.dispose()

        command.stamp(_build_config(url), SYNC_REVISION)
        _upgrade(url)
        assert SESSION_TABLE in _tables(db_path)
