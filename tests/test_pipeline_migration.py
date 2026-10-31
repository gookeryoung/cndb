"""流水线迁移 y3z4a5b6c7d8 往返测试（ADR 0076 P0）."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from cndb.core.migrations import _build_config

REVISION = "y3z4a5b6c7d8"
PREVIOUS = "x2y3z4a5b6c7"
WORKFLOW = "pipeline_workflow"
RUN = "pipeline_run"
FINDING = "pipeline_finding"


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


class TestPipelineMigration:
    def test_upgrade_creates_tables_and_indexes(self, tmp_path: Path):
        db_path = tmp_path / "pipeline.db"
        _upgrade(f"sqlite:///{db_path}")

        tables = _tables(db_path)
        assert {WORKFLOW, RUN, FINDING} <= tables
        assert "ix_pipeline_workflow_workspace_id" in _indexes(db_path, WORKFLOW)
        assert "ix_pipeline_workflow_ws_updated" in _indexes(db_path, WORKFLOW)
        assert "ix_pipeline_run_workflow_created" in _indexes(db_path, RUN)
        assert "ix_pipeline_run_ws_status" in _indexes(db_path, RUN)
        assert "ix_pipeline_finding_run_severity" in _indexes(db_path, FINDING)

    def test_schema_matches_models(self, tmp_path: Path):
        from cndb.plugins.pipeline.models import PipelineFinding, PipelineRun, PipelineWorkflow

        db_path = tmp_path / "pipeline_model.db"
        _upgrade(f"sqlite:///{db_path}")
        assert _columns(db_path, WORKFLOW) == {column.name for column in PipelineWorkflow.__table__.columns}
        assert _columns(db_path, RUN) == {column.name for column in PipelineRun.__table__.columns}
        assert _columns(db_path, FINDING) == {column.name for column in PipelineFinding.__table__.columns}

    def test_downgrade_removes_tables(self, tmp_path: Path):
        db_path = tmp_path / "pipeline_down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)
        tables = _tables(db_path)
        assert {WORKFLOW, RUN, FINDING}.isdisjoint(tables)

    def test_reupgrade_after_downgrade(self, tmp_path: Path):
        db_path = tmp_path / "pipeline_round.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)
        _upgrade(url)
        assert {WORKFLOW, RUN, FINDING} <= _tables(db_path)

    def test_upgrade_idempotent_when_tables_exist(self, tmp_path: Path):
        """create_all 已建表：stamp 到上一版再 upgrade，迁移跳过建表不报错."""
        from sqlalchemy import create_engine

        import cndb.core.events
        import cndb.plugins.accounts.models
        import cndb.plugins.documents.models
        import cndb.plugins.pipeline.models
        import cndb.plugins.tables.models
        import cndb.plugins.workspaces.models  # noqa: F401
        from cndb.models.base import Base

        db_path = tmp_path / "pipeline_idempotent.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        engine.dispose()

        command.stamp(_build_config(url), PREVIOUS)
        _upgrade(url)
        assert {WORKFLOW, RUN, FINDING} <= _tables(db_path)
