"""restore.py 单元测试."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import io
import json
import sqlite3
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from cndb.backup import create_backup
from cndb.restore import (
    BackupInspection,
    RestoreError,
    _check_target_safe,
    _ensure_manifest_compatible,
    _from_json_safe,
    _migrate_after_restore,
    _reset_sqlite_database,
    _restore_sqlite_native,
    _restore_uploads,
    inspect_backup,
    restore_backup,
)

# ── 辅助 ──────────────────────────────────────────────


def _setup_src_sqlite(tmp_path: Path) -> Path:
    """创建有数据的源 SQLite 库."""
    db = tmp_path / "src.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, cid INTEGER, amount REAL);
        INSERT INTO customers (name) VALUES ('A'), ('B'), ('C');
        INSERT INTO orders (cid, amount) VALUES (1, 100.5), (2, 200.0);
        """
    )
    conn.commit()
    conn.close()
    return db


def _setup_uploads(tmp_path: Path) -> Path:
    up = tmp_path / "uploads"
    up.mkdir()
    (up / "1").mkdir()
    (up / "1" / "hello.txt").write_text("hello", encoding="utf-8")
    return up


def _make_backup_archive(tmp_path: Path) -> tuple[Path, Path]:
    """创建 native 模式备份并返回 (archive_path, target_db_path)."""
    src_db = _setup_src_sqlite(tmp_path)
    uploads = _setup_uploads(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    create_backup(
        output=archive,
        mode="native",
        database_url=f"sqlite:///{src_db}",
        upload_dir=uploads,
        include_uploads=True,
    )
    # 恢复目标：全新库
    target_db = tmp_path / "target.db"
    return archive, target_db


# ── _ensure_manifest_compatible ──────────────────────


def test_ensure_manifest_compatible_v1() -> None:
    _ensure_manifest_compatible({"version": "1"})  # 不抛异常即通过


def test_ensure_manifest_compatible_unknown() -> None:
    with pytest.raises(RestoreError, match="不支持的备份版本"):
        _ensure_manifest_compatible({"version": "999"})


# ── _check_target_safe ────────────────────────────────


def test_check_target_safe_new_file(tmp_path: Path) -> None:
    """目标文件不存在 → 安全."""
    _check_target_safe(f"sqlite:///{tmp_path / 'new.db'}", force=False)


def test_check_target_safe_empty_db(tmp_path: Path) -> None:
    """目标是个空 SQLite 库 → 安全."""
    db = tmp_path / "empty.db"
    sqlite3.connect(str(db)).close()
    _check_target_safe(f"sqlite:///{db}", force=False)


def test_check_target_safe_nonempty_requires_force(tmp_path: Path) -> None:
    """目标有数据且未 force → RestoreError."""
    src = _setup_src_sqlite(tmp_path)
    with pytest.raises(RestoreError, match=r"已有 .* 行数据"):
        _check_target_safe(f"sqlite:///{src}", force=False)


def test_check_target_safe_nonempty_with_force(tmp_path: Path) -> None:
    """目标有数据且 force=True → 通过."""
    src = _setup_src_sqlite(tmp_path)
    _check_target_safe(f"sqlite:///{src}", force=True)


# ── _reset_sqlite_database ────────────────────────────


def test_reset_sqlite_database_creates_clean_file(tmp_path: Path) -> None:
    target = tmp_path / "reset.db"
    # 先写些东西
    conn = sqlite3.connect(str(target))
    conn.execute("CREATE TABLE x (a INTEGER)")
    conn.commit()
    conn.close()

    # 再附属文件
    wal = Path(str(target) + "-wal")
    wal.write_text("junk")

    _reset_sqlite_database(target)

    assert target.is_file()
    assert not wal.exists()
    # 新库应当是空的（没有任何用户表）
    conn = sqlite3.connect(str(target))
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    conn.close()
    assert tables == []


# ── inspect_backup ─────────────────────────────────────


def test_inspect_backup_valid(tmp_path: Path) -> None:
    archive, _ = _make_backup_archive(tmp_path)
    result = inspect_backup(archive)
    assert isinstance(result, BackupInspection)
    assert result.manifest["version"] == "1"
    assert result.archive_size > 0
    assert "数据库类型" in result.summary
    assert "附件" in result.summary


def test_inspect_backup_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RestoreError, match="备份归档不存在"):
        inspect_backup(tmp_path / "no_such.tar.gz")


def test_inspect_backup_corrupted(tmp_path: Path) -> None:
    bad = tmp_path / "bad.tar.gz"
    bad.write_bytes(b"not a tar file")
    with pytest.raises(RestoreError, match=r"归档损坏|无法打开"):
        inspect_backup(bad)


def test_inspect_backup_no_manifest(tmp_path: Path) -> None:
    """归档合法但缺 manifest.json → RestoreError."""
    fake = tmp_path / "fake.tar.gz"
    with tarfile.open(fake, "w:gz") as tar:
        info = tarfile.TarInfo(name="backup/something.txt")
        data = b"hello"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    with pytest.raises(RestoreError, match=r"缺少 manifest.json"):
        inspect_backup(fake)


def test_inspect_backup_bad_json(tmp_path: Path) -> None:
    """manifest.json 存在但不是合法 JSON → RestoreError."""
    fake = tmp_path / "fake.tar.gz"
    with tarfile.open(fake, "w:gz") as tar:
        info = tarfile.TarInfo(name="backup/manifest.json")
        data = b"not-json{"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    with pytest.raises(RestoreError, match="不是合法 JSON"):
        inspect_backup(fake)


# ── restore_backup native 端到端 ───────────────────────


def test_restore_native_full_flow(tmp_path: Path) -> None:
    archive, target_db = _make_backup_archive(tmp_path)
    target_uploads = tmp_path / "uploads_target"

    restore_backup(
        archive,
        force=False,
        database_url=f"sqlite:///{target_db}",
        upload_dir=target_uploads,
    )

    # 数据库验证
    conn = sqlite3.connect(str(target_db))
    try:
        rows = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        assert rows == 3
        orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        assert orders == 2
    finally:
        conn.close()


def test_restore_native_overwrite_existing_with_force(tmp_path: Path) -> None:
    """已有库有数据，加 --force 应成功覆盖."""
    archive, _ = _make_backup_archive(tmp_path)
    # 目标是另一个已存在且有数据的库
    target = tmp_path / "exists.db"
    conn = sqlite3.connect(str(target))
    conn.execute("CREATE TABLE dummy (a TEXT)")
    conn.execute("INSERT INTO dummy VALUES ('old data')")
    conn.commit()
    conn.close()

    restore_backup(
        archive,
        force=True,
        database_url=f"sqlite:///{target}",
        upload_dir=tmp_path / "uploads_target",
    )

    # 旧表应被删除（native 直接覆盖文件），新表生效
    conn = sqlite3.connect(str(target))
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        assert "customers" in tables
        assert "orders" in tables
        assert "dummy" not in tables
    finally:
        conn.close()


def test_restore_native_rejects_without_force(tmp_path: Path) -> None:
    """已有库有数据，不加 --force → RestoreError."""
    archive, _ = _make_backup_archive(tmp_path)
    target = tmp_path / "exists.db"
    conn = sqlite3.connect(str(target))
    conn.execute("CREATE TABLE dummy (a TEXT)")
    conn.execute("INSERT INTO dummy VALUES ('x')")
    conn.commit()
    conn.close()

    with pytest.raises(RestoreError, match=r"已有 .* 行数据"):
        restore_backup(
            archive,
            force=False,
            database_url=f"sqlite:///{target}",
        )


def test_restore_uploads_recovery(tmp_path: Path) -> None:
    """备份含 uploads 时恢复后应有相同文件."""
    archive, _ = _make_backup_archive(tmp_path)
    target_db = tmp_path / "target.db"
    target_uploads = tmp_path / "target_uploads"

    restore_backup(
        archive,
        force=False,
        database_url=f"sqlite:///{target_db}",
        upload_dir=target_uploads,
    )

    assert (target_uploads / "1" / "hello.txt").is_file()
    assert (target_uploads / "1" / "hello.txt").read_text() == "hello"


def test_restore_uploads_cleans_old_files(tmp_path: Path) -> None:
    """目标 uploads 目录已有旧文件 → 恢复后应被清空并替换."""
    archive, _ = _make_backup_archive(tmp_path)
    target_db = tmp_path / "target.db"
    target_uploads = tmp_path / "target_uploads"
    target_uploads.mkdir(parents=True)
    (target_uploads / "old.txt").write_text("old", encoding="utf-8")
    (target_uploads / "1").mkdir()
    (target_uploads / "1" / "old2.txt").write_text("old2", encoding="utf-8")

    restore_backup(
        archive,
        force=False,
        database_url=f"sqlite:///{target_db}",
        upload_dir=target_uploads,
    )

    # 旧文件应被清除
    assert not (target_uploads / "old.txt").exists()
    assert not (target_uploads / "1" / "old2.txt").exists()
    # 新文件应存在
    assert (target_uploads / "1" / "hello.txt").is_file()


def test_restore_missing_archive(tmp_path: Path) -> None:
    with pytest.raises(RestoreError, match="备份归档不存在"):
        restore_backup(tmp_path / "no.tar.gz")


# ── restore_command CLI 包装 ───────────────────────────


def test_restore_command_accepts_archive_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import argparse

    from cndb.restore import restore_command

    archive, target = _make_backup_archive(tmp_path)
    monkeypatch.chdir(tmp_path)

    # monkey 掉 settings 以便测试使用临时路径
    import cndb.core.config as cfg_mod

    original_db = cfg_mod.settings.DATABASE_URL
    original_up = cfg_mod.settings.UPLOAD_DIR
    try:
        cfg_mod.settings.DATABASE_URL = f"sqlite:///{target}"
        cfg_mod.settings.UPLOAD_DIR = tmp_path / "uploads_target"
        args = argparse.Namespace(archive=str(archive), force=False, dry_run=False)
        restore_command(args)
    finally:
        cfg_mod.settings.DATABASE_URL = original_db
        cfg_mod.settings.UPLOAD_DIR = original_up

    assert target.is_file()


def test_restore_command_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import argparse

    from cndb.restore import restore_command

    archive, _ = _make_backup_archive(tmp_path)
    # dry-run 不应创建目标库
    target = tmp_path / "dry.db"
    monkeypatch.chdir(tmp_path)

    import cndb.core.config as cfg_mod

    original_db = cfg_mod.settings.DATABASE_URL
    try:
        cfg_mod.settings.DATABASE_URL = f"sqlite:///{target}"
        args = argparse.Namespace(archive=str(archive), force=False, dry_run=True)
        restore_command(args)
    finally:
        cfg_mod.settings.DATABASE_URL = original_db

    # dry-run 不应该创建文件
    assert not target.exists()


def test_restore_command_exit_on_error(tmp_path: Path) -> None:
    from cndb.restore import restore_command

    args = argparse.Namespace(archive=str(tmp_path / "no.tar.gz"), force=False, dry_run=False)
    with pytest.raises(SystemExit) as excinfo:
        restore_command(args)
    assert excinfo.value.code == 1


# ── BackupInspection.summary 附件未包含 ───────────────


def test_summary_uploads_not_included() -> None:
    """manifest 中 uploads.included=False → summary 应显示 '附件: 未包含'."""
    inspection = BackupInspection(
        manifest={
            "app_version": "1.0",
            "created_at": "2024-01-01T00:00:00",
            "database": {"db_type": "sqlite", "backup_mode": "native", "tables": ["a"], "row_counts": {"a": 5}},
            "uploads": {"included": False, "file_count": 0, "total_size": 0},
        },
        archive_size=1024,
    )
    assert "附件: 未包含" in inspection.summary


# ── _check_target_safe 非 SQLite 分支 ────────────────


def test_check_target_safe_non_sqlite_url(tmp_path: Path) -> None:
    """非 SQLite DATABASE_URL 直接 return，不抛错."""
    _check_target_safe("postgresql://user:pass@localhost/db", force=False)
    _check_target_safe("mysql://localhost/db", force=True)


# ── _restore_sqlite_native 缺失 db 文件 ───────────────


def test_restore_sqlite_native_missing_src_db(tmp_path: Path) -> None:
    """native 备份目录中缺 cndb.db → RestoreError."""
    extracted = tmp_path / "extracted"
    (extracted / "database").mkdir(parents=True)
    target = tmp_path / "target.db"
    with pytest.raises(RestoreError, match=r"缺失 cndb.db"):
        _restore_sqlite_native(extracted, target)


# ── _from_json_safe 全分支 ────────────────────────────


def test_from_json_safe_none() -> None:
    assert _from_json_safe(None) is None


def test_from_json_safe_base64_dict() -> None:
    raw = b"hello bytes"
    encoded = {"__base64__": base64.b64encode(raw).decode("ascii")}
    assert _from_json_safe(encoded) == raw


def test_from_json_safe_iso_string() -> None:
    dt_str = "2024-06-15T10:30:00"
    result = _from_json_safe(dt_str)
    assert isinstance(result, dt.datetime)
    assert result.year == 2024 and result.month == 6 and result.day == 15


def test_from_json_safe_short_string() -> None:
    """长度 < 10 的字符串不会尝试解析 datetime."""
    assert _from_json_safe("short") == "short"


def test_from_json_safe_non_iso_string() -> None:
    """长度 >= 10 但不是合法 ISO → 原样返回."""
    assert _from_json_safe("not-a-datetime!!") == "not-a-datetime!!"


def test_from_json_safe_other_types() -> None:
    assert _from_json_safe(42) == 42
    assert _from_json_safe(3.14) == 3.14
    assert _from_json_safe([1, 2]) == [1, 2]


# ── _restore_uploads 分支 ─────────────────────────────


def test_restore_uploads_not_included(tmp_path: Path) -> None:
    """included=False → 直接返回 0，不碰文件系统."""
    extracted = tmp_path / "extracted"
    target = tmp_path / "target_uploads"
    count = _restore_uploads(extracted, target, included=False)
    assert count == 0
    assert not target.exists()


def test_restore_uploads_src_missing(tmp_path: Path) -> None:
    """备份中无 uploads 目录 → 返回 0."""
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    target = tmp_path / "target_uploads"
    count = _restore_uploads(extracted, target, included=True)
    assert count == 0
    assert not target.exists()


# ── restore_backup 跳过 uploads 恢复 ──────────────────


def test_restore_backup_no_uploads_in_backup(tmp_path: Path) -> None:
    """备份 manifest 中 uploads.included=False → 恢复时跳过 uploads."""
    import tarfile

    archive = tmp_path / "no_uploads.tar.gz"
    target_db = tmp_path / "target.db"

    manifest = {
        "version": "1",
        "app_version": "0.1.0",
        "created_at": "2024-01-01T00:00:00",
        "database": {"db_type": "sqlite", "backup_mode": "native", "tables": [], "row_counts": {}},
        "uploads": {"included": False, "file_count": 0, "total_size": 0},
    }

    # 手工构造一个空的 native 备份（空库）
    src_db = tmp_path / "empty.db"
    sqlite3.connect(str(src_db)).close()

    with tarfile.open(archive, "w:gz") as tar:
        # 添加 manifest
        manifest_bytes = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo(name="backup/manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))
        # 添加空 cndb.db
        db_bytes = src_db.read_bytes()
        info2 = tarfile.TarInfo(name="backup/database/cndb.db")
        info2.size = len(db_bytes)
        tar.addfile(info2, io.BytesIO(db_bytes))

    # upload_dir 不应该被创建
    target_up = tmp_path / "should_not_exist"
    restore_backup(archive, force=False, database_url=f"sqlite:///{target_db}", upload_dir=target_up)
    assert not target_up.exists()


# ── restore_command 兜底异常 ──────────────────────────


def test_restore_command_catch_unexpected_exception(tmp_path: Path) -> None:
    """restore_command 捕获 RestoreError 之外的异常 → sys.exit(1)."""
    from cndb import restore as restore_mod
    from cndb.restore import restore_command

    archive = tmp_path / "no.tar.gz"
    args = argparse.Namespace(archive=str(archive), force=False, dry_run=False)

    # monkeypatch inspect_backup 抛一个非 RestoreError 的异常
    with (
        patch.object(restore_mod, "inspect_backup", side_effect=RuntimeError("boom")),
        pytest.raises(SystemExit) as excinfo,
    ):
        restore_command(args)
    assert excinfo.value.code == 1


# ── 版本协商（SUPPORTED_MANIFEST_VERSIONS）────────────


def test_ensure_manifest_compatible_error_lists_supported() -> None:
    """未知版本的错误信息应列出当前支持的全部版本."""
    with pytest.raises(RestoreError, match=r"当前支持: 1"):
        _ensure_manifest_compatible({"version": "9"})


# ── BackupInspection.summary schema 版本展示 ──────────


def _make_inspection(
    backup_mode: str = "native", schema_version: str = "", fallback_mode: str = ""
) -> BackupInspection:
    """构造带 schema 信息的 BackupInspection."""
    return BackupInspection(
        manifest={
            "app_version": "1.0",
            "created_at": "2024-01-01T00:00:00",
            "database": {
                "db_type": "sqlite",
                "backup_mode": backup_mode,
                "schema_version": schema_version,
                "fallback_mode": fallback_mode,
                "tables": ["a"],
                "row_counts": {"a": 5},
            },
            "uploads": {"included": False, "file_count": 0, "total_size": 0},
        },
        archive_size=1024,
    )


def test_summary_shows_schema_version_and_migration_hint() -> None:
    """native 备份带 schema 版本时，摘要应显示版本并提示自动迁移."""
    summary = _make_inspection(backup_mode="native", schema_version="6399e5f0f61f").summary
    assert "Schema 版本: 6399e5f0f61f" in summary
    assert "自动迁移" in summary


def test_summary_unknown_schema_version() -> None:
    """旧版备份无 schema 版本 → 显示未知，且不提示迁移."""
    summary = _make_inspection(backup_mode="native", schema_version="").summary
    assert "Schema 版本: 未知（旧版备份）" in summary
    assert "自动迁移" not in summary


def test_summary_shows_fallback_export() -> None:
    """摘要按 manifest 的 fallback_mode 显示兜底导出有无."""
    with_fallback = _make_inspection(fallback_mode="sqlalchemy").summary
    assert "内嵌兜底导出: 有（fallback_mode=sqlalchemy" in with_fallback
    without_fallback = _make_inspection().summary
    assert "内嵌兜底导出: 无" in without_fallback


# ── 恢复后 schema 迁移（向前兼容核心场景）─────────────


def _alembic_head() -> str:
    """获取当前包内迁移链的 head revision."""
    import alembic.script

    from cndb.core.migrations import _build_config

    cfg = _build_config("sqlite:///:memory:")
    return str(alembic.script.ScriptDirectory.from_config(cfg).get_current_head())


def test_restore_native_old_schema_auto_migrates(tmp_path: Path) -> None:
    """旧 schema 备份（alembic_version 停在 initial）恢复后自动迁移到当前 head."""
    import alembic.command

    from cndb.core.migrations import _build_config

    # 构造"旧版本程序"的库：从零迁移到 initial revision 为止
    src_db = tmp_path / "old_schema.db"
    cfg = _build_config(f"sqlite:///{src_db}")
    alembic.command.upgrade(cfg, "6399e5f0f61f")

    archive = tmp_path / "old.tar.gz"
    create_backup(output=archive, mode="native", database_url=f"sqlite:///{src_db}")

    # manifest 应记录备份时的 schema 版本
    inspection = inspect_backup(archive)
    assert inspection.manifest["database"]["schema_version"] == "6399e5f0f61f"

    target_db = tmp_path / "target.db"
    restore_backup(archive, force=False, database_url=f"sqlite:///{target_db}")

    # 恢复后 alembic_version 应为当前 head
    conn = sqlite3.connect(str(target_db))
    try:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        conn.close()
    assert version == _alembic_head()


def test_migrate_after_restore_wraps_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """迁移失败应包装为 RestoreError 并提示升级程序."""
    from sqlalchemy.exc import SQLAlchemyError

    import cndb.core.migrations as migrations_mod

    def _boom(url: str) -> None:
        raise SQLAlchemyError("boom")

    monkeypatch.setattr(migrations_mod, "upgrade_to_head", _boom)
    with pytest.raises(RestoreError, match="schema 迁移失败"):
        _migrate_after_restore(f"sqlite:///{tmp_path / 'x.db'}", "oldrev")


# ── sqlalchemy 恢复后补写 alembic 版本 ────────────────


def test_restore_sqlalchemy_stamps_alembic_version(tmp_path: Path) -> None:
    """sqlalchemy 模式恢复（drop_all + create_all）后应补写 alembic_version."""
    from sqlalchemy import create_engine

    from cndb.core.plugin_registry import plugin_registry
    from cndb.models.base import Base

    src_db = tmp_path / "src.db"
    plugin_registry.discover_and_load()
    engine = create_engine(f"sqlite:///{src_db}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    archive = tmp_path / "sa.tar.gz"
    create_backup(output=archive, mode="sqlalchemy", database_url=f"sqlite:///{src_db}")

    target_db = tmp_path / "target.db"
    restore_backup(archive, force=False, database_url=f"sqlite:///{target_db}")

    conn = sqlite3.connect(str(target_db))
    try:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        conn.close()
    assert version == _alembic_head()


# ── 降级恢复：native 归档以 sqlalchemy 模式恢复 ───────


def test_restore_native_backup_via_sqlalchemy_mode(tmp_path: Path) -> None:
    """native 归档内嵌兜底导出时，可显式用 sqlalchemy 模式降级恢复."""
    from sqlalchemy import create_engine
    from sqlalchemy import text as sa_text

    from cndb.core.plugin_registry import plugin_registry
    from cndb.models.base import Base
    from cndb.plugins.workspaces.models import Workspace

    # 源库：当前 schema + 一行业务数据
    src_db = tmp_path / "src.db"
    plugin_registry.discover_and_load()
    engine = create_engine(f"sqlite:///{src_db}")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(Workspace.__table__.insert().values(name="降级恢复测试"))
    finally:
        engine.dispose()

    archive = tmp_path / "mixed.tar.gz"
    create_backup(output=archive, mode="native", database_url=f"sqlite:///{src_db}")
    inspection = inspect_backup(archive)
    assert inspection.manifest["database"]["fallback_mode"] == "sqlalchemy"
    assert "内嵌兜底导出: 有" in inspection.summary

    target_db = tmp_path / "target.db"
    restore_backup(archive, force=False, database_url=f"sqlite:///{target_db}", mode="sqlalchemy")

    # 降级恢复成功：业务数据存在，alembic_version 为当前 head
    check = create_engine(f"sqlite:///{target_db}")
    try:
        with check.connect() as conn:
            name = conn.execute(sa_text("SELECT name FROM workspaces_workspace")).scalar()
            version = conn.execute(sa_text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        check.dispose()
    assert name == "降级恢复测试"
    assert version == _alembic_head()


def test_restore_backup_invalid_mode(tmp_path: Path) -> None:
    """非法 mode 参数在恢复开始前报 RestoreError."""
    archive, target_db = _make_backup_archive(tmp_path)
    with pytest.raises(RestoreError, match="无效的恢复模式"):
        restore_backup(archive, force=True, database_url=f"sqlite:///{target_db}", mode="auto")
