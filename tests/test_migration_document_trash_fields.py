"""迁移 b1c2d3e4f5a6（add_document_trash_fields）回归测试.

背景：documents 插件此前只有布尔软删除标记，进回收站后无法列出/恢复，也无法
区分"随父级联删除"与"先被单独删除"的子项。本迁移为 documents_document 补齐
deleted_at / deleted_by_id 两列。

关键约束与 f7a8b9c0d1e2 同类：幂等加列（create_all 时代旧库可能已含），
目标表不存在时跳过（由启动 create_all 兜底），downgrade 幂等。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.script import ScriptDirectory

from cndb.core.migrations import _build_config, upgrade_to_head

PRE_REVISION = "f0a1b2c3d4e5"  # 本迁移之前的 head（documents 插件首版）


def _upgrade_to(engine_target: str, revision: str) -> None:
    cfg = _build_config(engine_target)
    from alembic import command

    command.upgrade(cfg, revision)


def _downgrade_to(engine_target: str, revision: str) -> None:
    cfg = _build_config(engine_target)
    from alembic import command

    command.downgrade(cfg, revision)


def _current_head() -> str:
    cfg = _build_config("sqlite:///:memory:")
    return str(ScriptDirectory.from_config(cfg).get_current_head())


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}  # nosec B608 - 测试内部常量表名
    finally:
        conn.close()


class TestDocumentTrashFieldsMigration:
    def test_upgrade_adds_trash_columns(self, tmp_path: Path) -> None:
        db_path = tmp_path / "old.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        assert not {"deleted_at", "deleted_by_id"} & _columns(db_path, "documents_document")

        upgrade_to_head(url)

        assert {"deleted_at", "deleted_by_id"} <= _columns(db_path, "documents_document")
        conn = sqlite3.connect(str(db_path))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        finally:
            conn.close()
        assert version == _current_head()

    def test_upgrade_preserves_existing_rows(self, tmp_path: Path) -> None:
        db_path = tmp_path / "data.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO documents_document "
                "(workspace_id, title, content_type, author, summary, toc_json, status, is_folder, "
                " sort_order, is_deleted, content_size, created_at, updated_at) "
                "VALUES (1, '旧文档', 'markdown', '', '', '[]', 'draft', 0, 0, 0, 0, "
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
            conn.commit()
        finally:
            conn.close()

        upgrade_to_head(url)

        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute("SELECT title, deleted_at, deleted_by_id FROM documents_document").fetchone()
        finally:
            conn.close()
        assert row == ("旧文档", None, None)

    def test_upgrade_idempotent_when_columns_preexist(self, tmp_path: Path) -> None:
        """create_all 时代旧库已含两列 → upgrade head 不报 duplicate column."""
        db_path = tmp_path / "partial.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("ALTER TABLE documents_document ADD COLUMN deleted_at DATETIME")
            conn.execute("ALTER TABLE documents_document ADD COLUMN deleted_by_id INTEGER")
            conn.commit()
        finally:
            conn.close()

        upgrade_to_head(url)  # 不抛 duplicate column 即通过
        upgrade_to_head(url)  # 幂等：重复升级仍成功

        assert {"deleted_at", "deleted_by_id"} <= _columns(db_path, "documents_document")

    def test_upgrade_skips_missing_table(self, tmp_path: Path) -> None:
        """目标表整体不存在（极简旧库）→ 迁移跳过不失败，由启动 create_all 兜底."""
        db_path = tmp_path / "legacy.db"
        url = f"sqlite:///{db_path.as_posix()}"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            conn.execute("INSERT INTO alembic_version VALUES (?)", (PRE_REVISION,))
            conn.commit()
        finally:
            conn.close()

        upgrade_to_head(url)  # 不抛 no such table 即通过

        conn = sqlite3.connect(str(db_path))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        finally:
            conn.close()
        assert version == _current_head()

    def test_downgrade_removes_columns_then_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "down.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        upgrade_to_head(url)
        assert {"deleted_at", "deleted_by_id"} <= _columns(db_path, "documents_document")

        _downgrade_to(url, PRE_REVISION)
        assert not {"deleted_at", "deleted_by_id"} & _columns(db_path, "documents_document")

        _downgrade_to(url, PRE_REVISION)  # 第二次：列已不存在，跳过
        assert "deleted_at" not in _columns(db_path, "documents_document")
