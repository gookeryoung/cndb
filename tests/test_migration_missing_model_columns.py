"""迁移 f7a8b9c0d1e2（add_missing_model_columns）回归测试.

背景：accounts_user.role / tables_dataview.is_public / tables_dataview.public_slug /
tables_tablepermission.manage_data_role 四列历史上只加在 ORM 模型上，迁移链从未
覆盖。旧库（典型：恢复 0.2.0 native 备份后 upgrade head）永远缺列，业务查询
报 "no such column"（表现为恢复后所有数据表内容无法显示）。

本迁移的关键约束：
- 幂等加列（部分旧库经 create_all 时代建表已含其中部分列）
- 目标表整体不存在时跳过（由启动 create_all 兜底建表）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.script import ScriptDirectory

from cndb.core.migrations import _build_config, upgrade_to_head

PRE_REVISION = "e5f6a7b8c9d0"  # f7a8b9c0d1e2 之前的 head（0.2.0 时代 schema）


def _upgrade_to(engine_target: str, revision: str) -> None:
    cfg = _build_config(engine_target)
    from alembic import command

    command.upgrade(cfg, revision)


def _current_head() -> str:
    cfg = _build_config("sqlite:///:memory:")
    return str(ScriptDirectory.from_config(cfg).get_current_head())


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}  # nosec B608 - 测试内部常量表名
    finally:
        conn.close()


class TestAddMissingModelColumns:
    def test_old_schema_db_upgrade_adds_all_columns(self, tmp_path: Path) -> None:
        """0.2.0 时代库（stamp 在 e5f6a7b8c9d0）upgrade head 后四列全部补齐."""
        db_path = tmp_path / "old.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        for table, col in (
            ("accounts_user", "role"),
            ("tables_dataview", "is_public"),
            ("tables_tablepermission", "manage_data_role"),
        ):
            assert col not in _columns(db_path, table)

        upgrade_to_head(url)

        assert "role" in _columns(db_path, "accounts_user")
        assert {"is_public", "public_slug"} <= _columns(db_path, "tables_dataview")
        assert "manage_data_role" in _columns(db_path, "tables_tablepermission")
        conn = sqlite3.connect(str(db_path))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        finally:
            conn.close()
        assert version == _current_head()

    def test_upgrade_is_idempotent_when_columns_preexist(self, tmp_path: Path) -> None:
        """create_all 时代旧库已含部分列 → upgrade head 不报 duplicate column."""
        db_path = tmp_path / "partial.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        # 模拟 create_all 时代已补过其中的列（带各自默认值）
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("ALTER TABLE accounts_user ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'user'")
            conn.execute(
                "ALTER TABLE tables_tablepermission ADD COLUMN manage_data_role VARCHAR(16) NOT NULL DEFAULT ''"
            )
            conn.commit()
        finally:
            conn.close()

        upgrade_to_head(url)  # 不抛 duplicate column 即通过

        assert "public_slug" in _columns(db_path, "tables_dataview")
        # 幂等：重复 upgrade 仍成功
        upgrade_to_head(url)

    def test_upgrade_skips_missing_tables(self, tmp_path: Path) -> None:
        """目标表整体不存在（legacy 库仅 reports_template）→ 迁移跳过不失败.

        该场景由启动期 create_all 按完整 ORM 元数据兜底建表，本迁移只负责
        存量表的缺列（test_migrations_heal.py 验证自愈层兜住同场景）。
        """
        db_path = tmp_path / "legacy.db"
        url = f"sqlite:///{db_path.as_posix()}"
        # 手工建一个最小库：只有 alembic_version stamp 在 e5f6a7b8c9d0
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

    def test_upgrade_preserves_existing_data(self, tmp_path: Path) -> None:
        """加列后存量数据保留，新列取 server_default 值."""
        db_path = tmp_path / "data.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO accounts_user (username, email, nickname, hashed_password, is_active, is_superuser) "
                "VALUES ('legacy', 'legacy@example.com', '旧用户', 'x', 1, 0)"
            )
            conn.commit()
        finally:
            conn.close()

        upgrade_to_head(url)

        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute("SELECT username, role FROM accounts_user").fetchone()
        finally:
            conn.close()
        assert row == ("legacy", "user")

    def test_downgrade_removes_columns(self, tmp_path: Path) -> None:
        """downgrade 移除本迁移新增的列与索引（幂等，缺列时跳过）."""
        db_path = tmp_path / "down.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        upgrade_to_head(url)
        cfg = _build_config(url)
        from alembic import command

        command.downgrade(cfg, PRE_REVISION)

        assert "role" not in _columns(db_path, "accounts_user")
        assert "manage_data_role" not in _columns(db_path, "tables_tablepermission")
        assert "is_public" not in _columns(db_path, "tables_dataview")

    def test_downgrade_idempotent(self, tmp_path: Path) -> None:
        """已降级的库重复 downgrade 不报错（缺列跳过）."""
        db_path = tmp_path / "down2.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        upgrade_to_head(url)
        cfg = _build_config(url)
        from alembic import command

        command.downgrade(cfg, PRE_REVISION)
        command.downgrade(cfg, PRE_REVISION)  # 第二次：列已不存在，跳过

        assert "role" not in _columns(db_path, "accounts_user")
