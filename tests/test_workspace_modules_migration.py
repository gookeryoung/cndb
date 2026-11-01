"""工作区模块迁移 b6c7d8e9f0a1 往返测试（ADR 0080 P0：幂等 + 回填映射 + 有损 downgrade）."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from alembic import command

from cndb.core.migrations import _build_config

REVISION = "b6c7d8e9f0a1"
PREVIOUS = "z4a5b6c7d8e9"
TABLE = "workspaces_workspace"


def _upgrade(url: str, revision: str = REVISION) -> None:
    command.upgrade(_build_config(url), revision)


def _downgrade(url: str, revision: str) -> None:
    command.downgrade(_build_config(url), revision)


def _columns(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({TABLE})").fetchall()}  # nosec B608 - 测试内部常量
    finally:
        conn.close()


def _insert_legacy(db_path: Path, name: str, workspace_type: str) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            f"INSERT INTO {TABLE} (name, description, visibility, tags, allow_edit, workspace_type, created_at, updated_at) "  # nosec B608
            "VALUES (?, '', 'member', '[]', 1, ?, datetime('now'), datetime('now'))",
            (name, workspace_type),
        )
        conn.commit()
    finally:
        conn.close()


def _modules_by_name(db_path: Path) -> dict[str, list[str]]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"SELECT name, modules FROM {TABLE}").fetchall()  # nosec B608 - 测试内部常量
        return {name: json.loads(modules) for name, modules in rows}
    finally:
        conn.close()


def _types_by_name(db_path: Path) -> dict[str, str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"SELECT name, workspace_type FROM {TABLE}").fetchall()  # nosec B608 - 测试内部常量
        return dict(rows)
    finally:
        conn.close()


class TestWorkspaceModulesMigration:
    def test_upgrade_replaces_columns(self, tmp_path: Path):
        db_path = tmp_path / "ws.db"
        _upgrade(f"sqlite:///{db_path}")
        cols = _columns(db_path)
        assert "modules" in cols
        assert "workspace_type" not in cols

    def test_backfill_mapping(self, tmp_path: Path):
        """三种旧枚举逐值映射（ADR 0080 D5，I3）."""
        db_path = tmp_path / "backfill.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, PREVIOUS)
        _insert_legacy(db_path, "全开", "DATA_DOC")
        _insert_legacy(db_path, "仅数据", "DATA")
        _insert_legacy(db_path, "仅文档", "DOC")
        _upgrade(url)

        modules = _modules_by_name(db_path)
        assert modules["全开"] == ["tables", "documents", "design"]
        assert modules["仅数据"] == ["tables"]
        assert modules["仅文档"] == ["documents", "design"]

    def test_upgrade_idempotent(self, tmp_path: Path):
        db_path = tmp_path / "idem.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _upgrade(url)
        cols = _columns(db_path)
        assert "modules" in cols and "workspace_type" not in cols

    def test_upgrade_idempotent_on_create_all_schema(self, tmp_path: Path):
        """create_all 已建新模型（含 modules 无 workspace_type）：stamp 上一版再 upgrade 不报错."""
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
        assert "workspace_type" not in _columns(db_path)

    def test_downgrade_lossy_mapping(self, tmp_path: Path):
        """downgrade 有损映射（D6）：tables+documents→DATA_DOC、tables→DATA、其余→DOC."""
        db_path = tmp_path / "down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)

        conn = sqlite3.connect(str(db_path))
        try:
            for name, modules in (
                ("全开", ["tables", "documents", "design"]),
                ("表加设计", ["tables", "design"]),
                ("仅数据", ["tables"]),
                ("仅设计", ["design"]),
            ):
                conn.execute(
                    f"INSERT INTO {TABLE} (name, description, visibility, tags, allow_edit, modules, created_at, updated_at) "  # nosec B608
                    "VALUES (?, '', 'member', '[]', 1, ?, datetime('now'), datetime('now'))",
                    (name, json.dumps(modules)),
                )
            conn.commit()
        finally:
            conn.close()

        _downgrade(url, PREVIOUS)
        cols = _columns(db_path)
        assert "workspace_type" in cols and "modules" not in cols
        types = _types_by_name(db_path)
        assert types["全开"] == "DATA_DOC"
        assert types["表加设计"] == "DATA"  # 有损：design 信息丢失
        assert types["仅数据"] == "DATA"
        assert types["仅设计"] == "DOC"
