"""采集策略迁移 a1b2c3d4e5f6 往返测试（ADR 0085 P0）."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from cndb.core.migrations import _build_config

REVISION = "a7c1d2e3f4b5"
PREVIOUS = "b6c7d8e9f0a1"
STRATEGY = "acquisition_strategy"
RUN = "acquisition_run"
ROUND = "acquisition_round"
ITEM = "acquisition_item"
TABLES = (STRATEGY, RUN, ROUND, ITEM)


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
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"PRAGMA index_list({table})").fetchall()  # nosec B608 - 测试内部常量
        return sum(1 for row in rows if row[2] == 1)
    finally:
        conn.close()


class TestAcquisitionMigration:
    def test_upgrade_creates_four_tables_and_indexes(self, tmp_path: Path):
        db_path = tmp_path / "acquisition.db"
        _upgrade(f"sqlite:///{db_path}")

        assert set(TABLES) <= _tables(db_path)
        assert "ix_acquisition_strategy_ws_enabled" in _indexes(db_path, STRATEGY)
        assert "ix_acquisition_run_strategy_started" in _indexes(db_path, RUN)
        assert "ix_acquisition_round_run_id" in _indexes(db_path, ROUND)
        assert "ix_acquisition_item_run" in _indexes(db_path, ITEM)

    def test_unique_constraints_exist(self, tmp_path: Path):
        db_path = tmp_path / "acquisition_unique.db"
        _upgrade(f"sqlite:///{db_path}")
        # (run_id, round_no) 与 (strategy_id, dedupe_key) 各一条唯一约束
        assert _unique_index_count(db_path, ROUND) == 1
        assert _unique_index_count(db_path, ITEM) == 1

    def test_schema_matches_models(self, tmp_path: Path):
        from cndb.plugins.acquisition.models import (
            AcquisitionItem,
            AcquisitionRound,
            AcquisitionRun,
            AcquisitionStrategy,
        )

        db_path = tmp_path / "acquisition_model.db"
        _upgrade(f"sqlite:///{db_path}")
        pairs = (
            (STRATEGY, AcquisitionStrategy),
            (RUN, AcquisitionRun),
            (ROUND, AcquisitionRound),
            (ITEM, AcquisitionItem),
        )
        for table_name, model in pairs:
            assert _columns(db_path, table_name) == {column.name for column in model.__table__.columns}

    def test_downgrade_removes_tables_and_reupgrade_restores(self, tmp_path: Path):
        db_path = tmp_path / "acquisition_down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)
        assert set(TABLES).isdisjoint(_tables(db_path))

        _upgrade(url)
        assert set(TABLES) <= _tables(db_path)
