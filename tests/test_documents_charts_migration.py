"""迁移 e0f1a2b3c4d5（add_documents_chart）回归测试.

关键约束（与 documents 插件历次迁移同类）：幂等建表（create_all 时代旧库可能
已含），downgrade 幂等可还原。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.script import ScriptDirectory

from cndb.core.migrations import _build_config, upgrade_to_head

PRE_REVISION = "c4d5e6f7a8b9"  # 本迁移之前的 head

_EXPECTED_COLUMNS = {
    "id",
    "workspace_id",
    "title",
    "template_key",
    "config",
    "created_by_id",
    "updated_by_id",
    "created_at",
    "updated_at",
}


def _upgrade_to(engine_target: str, revision: str) -> None:
    from alembic import command

    command.upgrade(_build_config(engine_target), revision)


def _downgrade_to(engine_target: str, revision: str) -> None:
    from alembic import command

    command.downgrade(_build_config(engine_target), revision)


def _current_head() -> str:
    cfg = _build_config("sqlite:///:memory:")
    return str(ScriptDirectory.from_config(cfg).get_current_head())


def _tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}  # nosec B608 - 测试内部常量表名
    finally:
        conn.close()


def test_upgrade_creates_documents_chart(tmp_path: Path) -> None:
    db_path = tmp_path / "new.db"
    url = f"sqlite:///{db_path.as_posix()}"
    _upgrade_to(url, PRE_REVISION)
    assert "documents_chart" not in _tables(db_path)

    upgrade_to_head(url)

    assert _columns(db_path, "documents_chart") >= _EXPECTED_COLUMNS
    conn = sqlite3.connect(str(db_path))
    try:
        indexes = {r[1] for r in conn.execute("PRAGMA index_list(documents_chart)").fetchall()}
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        conn.close()
    assert "ix_documents_chart_ws" in indexes
    assert version == _current_head()


def test_upgrade_idempotent_when_table_preexists(tmp_path: Path) -> None:
    """create_all 时代旧库已含该表 → upgrade head 不报 duplicate table."""
    db_path = tmp_path / "partial.db"
    url = f"sqlite:///{db_path.as_posix()}"
    _upgrade_to(url, PRE_REVISION)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE documents_chart "
            "(id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL, title VARCHAR(255), "
            " template_key VARCHAR(64) NOT NULL, config JSON, created_at DATETIME, updated_at DATETIME)"
        )
        conn.commit()
    finally:
        conn.close()

    upgrade_to_head(url)  # 不抛 duplicate table 即通过
    upgrade_to_head(url)  # 幂等：重复升级仍成功

    assert "documents_chart" in _tables(db_path)


def test_downgrade_drops_table_then_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "down.db"
    url = f"sqlite:///{db_path.as_posix()}"
    _upgrade_to(url, PRE_REVISION)
    upgrade_to_head(url)
    assert "documents_chart" in _tables(db_path)

    _downgrade_to(url, PRE_REVISION)
    assert "documents_chart" not in _tables(db_path)

    _downgrade_to(url, PRE_REVISION)  # 第二次：表已不存在，跳过
    assert "documents_chart" not in _tables(db_path)
