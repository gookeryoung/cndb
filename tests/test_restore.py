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

from cndb.cli.backup import create_backup
from cndb.cli.restore import (
    BackupInspection,
    RestoreError,
    _check_target_safe,
    _ensure_manifest_compatible,
    _from_json_safe,
    _migrate_after_restore,
    _restore_sqlite_native,
    _restore_uploads,
    classify_table_groups,
    inspect_backup,
    restore_backup,
)


def test_classify_table_groups_splits_system_and_user() -> None:
    """用户表按 table_/trash_/link_ 前缀归组，其余归系统表，组内保持入参顺序."""
    tables = [
        "accounts_user",
        "table_ab12cd34ef56",
        "workspaces_workspace",
        "trash_ab12cd34ef56",
        "alembic_version",
        "link_11aa22bb33cc",
    ]
    groups = classify_table_groups(tables)

    assert groups["system"] == ["accounts_user", "workspaces_workspace", "alembic_version"]
    assert groups["user"] == ["table_ab12cd34ef56", "trash_ab12cd34ef56", "link_11aa22bb33cc"]


def test_classify_table_groups_empty() -> None:
    """空表清单返回两个空组，两键恒存在."""
    assert classify_table_groups([]) == {"system": [], "user": []}


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


# ── _restore_sqlite_native（backup API 语义）──────────


def test_restore_sqlite_native_replaces_target_content(tmp_path: Path) -> None:
    """backup API 恢复应整体替换目标库内容（旧表消失、新表生效）."""
    src_db = _setup_src_sqlite(tmp_path)
    extracted = tmp_path / "extracted"
    (extracted / "data").mkdir(parents=True)
    (extracted / "data" / "cndb.db").write_bytes(src_db.read_bytes())

    # 目标库先带一份无关旧数据
    target = tmp_path / "target.db"
    conn = sqlite3.connect(str(target))
    conn.execute("CREATE TABLE dummy (a TEXT)")
    conn.execute("INSERT INTO dummy VALUES ('old')")
    conn.commit()
    conn.close()

    _restore_sqlite_native(extracted, target)

    conn = sqlite3.connect(str(target))
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert {"customers", "orders"} <= tables
        assert "dummy" not in tables
        assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 3
    finally:
        conn.close()


def test_restore_sqlite_native_succeeds_while_target_held_open(tmp_path: Path) -> None:
    """目标文件被其他连接持有（服务运行中）时恢复仍成功（Windows 文件锁回归）.

    旧实现"unlink + copy2"在此场景抛 WinError 32；backup API 页级覆盖不受影响。
    """
    src_db = _setup_src_sqlite(tmp_path)
    extracted = tmp_path / "extracted"
    (extracted / "data").mkdir(parents=True)
    (extracted / "data" / "cndb.db").write_bytes(src_db.read_bytes())

    target = tmp_path / "target.db"
    holder = sqlite3.connect(str(target))  # 模拟服务进程持有的连接
    try:
        holder.execute("CREATE TABLE t (a INTEGER)")
        holder.commit()
        # 未 close holder，直接恢复
        _restore_sqlite_native(extracted, target)
        # 持有连接在下一个事务即可看到新数据（change counter 已推进）
        holder.execute("PRAGMA schema_version").fetchone()
        tables = {
            r[0]
            for r in holder.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert "customers" in tables
    finally:
        holder.close()


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

    from cndb.cli.restore import restore_command

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

    from cndb.cli.restore import restore_command

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
    from cndb.cli.restore import restore_command

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
    (extracted / "data").mkdir(parents=True)
    target = tmp_path / "target.db"
    with pytest.raises(RestoreError, match=r"缺失 cndb.db"):
        _restore_sqlite_native(extracted, target)


def test_restore_sqlite_native_legacy_database_dir(tmp_path: Path) -> None:
    """旧版归档使用 database/ 目录名 → 定位回退后仍可恢复."""
    extracted = tmp_path / "legacy_extracted"
    legacy_dir = extracted / "database"
    legacy_dir.mkdir(parents=True)
    src_db = tmp_path / "src.db"
    sqlite3.connect(str(src_db)).close()
    (legacy_dir / "cndb.db").write_bytes(src_db.read_bytes())
    target = tmp_path / "legacy_target.db"
    _restore_sqlite_native(extracted, target)
    assert target.is_file()


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
        info2 = tarfile.TarInfo(name="backup/data/cndb.db")
        info2.size = len(db_bytes)
        tar.addfile(info2, io.BytesIO(db_bytes))

    # upload_dir 不应该被创建
    target_up = tmp_path / "should_not_exist"
    restore_backup(archive, force=False, database_url=f"sqlite:///{target_db}", upload_dir=target_up)
    assert not target_up.exists()


# ── restore_command 兜底异常 ──────────────────────────


def test_restore_command_catch_unexpected_exception(tmp_path: Path) -> None:
    """restore_command 捕获 RestoreError 之外的异常 → sys.exit(1)."""
    from cndb.cli import restore as restore_mod
    from cndb.cli.restore import restore_command

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
    import sqlite3

    from sqlalchemy.exc import SQLAlchemyError

    import cndb.core.migrations as migrations_mod

    # 前置：目标库已带 alembic_version 表 → 走 upgrade_to_head 分支
    # （无版本表的旧库走 stamp + create_all 兜底，不经 upgrade_to_head）
    url = f"sqlite:///{(tmp_path / 'x.db').as_posix()}"
    conn = sqlite3.connect(tmp_path / "x.db")
    try:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.commit()
    finally:
        conn.close()

    def _boom(url: str) -> None:
        raise SQLAlchemyError("boom")

    monkeypatch.setattr(migrations_mod, "upgrade_to_head", _boom)
    with pytest.raises(RestoreError, match="schema 迁移失败"):
        _migrate_after_restore(url, "oldrev")


def test_migrate_after_restore_legacy_db_without_version_table(tmp_path: Path) -> None:
    """无 alembic_version 记录的旧版备份（0.1.x）恢复走 stamp + create_all 兜底.

    前置：手工建的旧 schema 库（业务表已存在、无 alembic_version 表）；
    步骤：_migrate_after_restore；预期：不重放迁移（不报 already exists），
    alembic_version 标记为 head，缺失表由 create_all 补齐。
    """
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    try:
        # 模拟 0.1.x 旧库：有业务表，无迁移版本记录
        conn.execute("CREATE TABLE workspaces_workspace (id INTEGER PRIMARY KEY, name TEXT)")
        conn.commit()
    finally:
        conn.close()

    _migrate_after_restore(f"sqlite:///{db.as_posix()}", "")

    conn = sqlite3.connect(str(db))
    try:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        # create_all 补齐缺失表（业务表原有结构不动）
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        rows = conn.execute("SELECT id, name FROM workspaces_workspace").fetchall()
    finally:
        conn.close()
    assert version == _alembic_head()
    assert "accounts_user" in tables
    assert rows == []


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


# ── 第 2 期：降级恢复报告与备份领先提示 ───────────────


def test_schema_revision_known() -> None:
    """迁移链判定三态：链上 revision / 未知 revision / 空串."""
    from cndb.cli.restore import _schema_revision_known

    assert _schema_revision_known("6399e5f0f61f") is True
    assert _schema_revision_known("deadbeef0000") is False
    assert _schema_revision_known("") is False


def test_summary_backup_ahead_hint() -> None:
    """备份 schema 领先（revision 不在本地链上）时摘要给出降级恢复指引."""
    ahead = _make_inspection(schema_version="deadbeef0000").summary
    assert "备份 schema 新于当前程序" in ahead
    assert "sqlalchemy" in ahead
    on_chain = _make_inspection(schema_version="6399e5f0f61f").summary
    assert "备份 schema 新于当前程序" not in on_chain


def test_restore_sqlalchemy_loss_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """sqlalchemy 降级恢复：未知表与未知列收集进报告并打印."""
    import json

    from sqlalchemy import create_engine
    from sqlalchemy import text as sa_text

    # 手工构造"来自更新版本"的目录备份：未知表 + 已知表带未知列
    # 刻意沿用旧版 database/ 目录名，兼作旧归档兼容回退的 sqlalchemy 恢复回归
    backup_dir = tmp_path / "future_backup"
    (backup_dir / "database").mkdir(parents=True)
    manifest = {
        "version": "1",
        "app_version": "9.9",
        "created_at": "2026-09-21T00:00:00",
        "database": {
            "db_type": "sqlite",
            "backup_mode": "sqlalchemy",
            "schema_version": "deadbeef0000",
            "fallback_mode": "",
            "tables": ["future_table", "workspaces_workspace"],
            "row_counts": {"future_table": 1, "workspaces_workspace": 1},
        },
        "uploads": {"included": False, "file_count": 0, "total_size": 0},
    }
    (backup_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    dump = {
        "tables": [
            {
                "table": "future_table",
                "columns": ["id", "payload"],
                "rows": [{"id": 1, "payload": "未来版本的数据"}],
            },
            {
                "table": "workspaces_workspace",
                "columns": ["id", "name", "future_col"],
                "rows": [{"id": 1, "name": "降级恢复测试", "future_col": "将丢弃"}],
            },
        ]
    }
    (backup_dir / "database" / "dump.json").write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")

    target_db = tmp_path / "target.db"
    report = restore_backup(backup_dir, force=False, database_url=f"sqlite:///{target_db}")

    assert report is not None
    assert report.has_loss
    assert report.skipped_tables == ["future_table"]
    assert report.dropped_columns == {"workspaces_workspace": ["future_col"]}
    assert "跳过未知表 1 个: future_table" in report.summary()
    # 报告随流程打印
    out = capsys.readouterr().out
    assert "降级恢复数据裁剪报告" in out
    assert "future_col" in out
    # 已知列数据正常导入，未知列数据不落库
    engine = create_engine(f"sqlite:///{target_db}")
    try:
        with engine.connect() as conn:
            name = conn.execute(sa_text("SELECT name FROM workspaces_workspace")).scalar()
    finally:
        engine.dispose()
    assert name == "降级恢复测试"


def test_restore_sqlalchemy_no_loss(tmp_path: Path) -> None:
    """交集完全命中时报告无丢失."""
    import json

    # 目录备份仅含已知表已知列（新版 data/ 目录名）
    backup_dir = tmp_path / "clean_backup"
    (backup_dir / "data").mkdir(parents=True)
    manifest = {
        "version": "1",
        "app_version": "1.0",
        "created_at": "2026-09-21T00:00:00",
        "database": {
            "db_type": "sqlite",
            "backup_mode": "sqlalchemy",
            "schema_version": "",
            "fallback_mode": "",
            "tables": ["workspaces_workspace"],
            "row_counts": {"workspaces_workspace": 1},
        },
        "uploads": {"included": False, "file_count": 0, "total_size": 0},
    }
    (backup_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    dump = {
        "tables": [
            {
                "table": "workspaces_workspace",
                "columns": ["id", "name"],
                "rows": [{"id": 1, "name": "完整表"}],
            }
        ]
    }
    (backup_dir / "data" / "dump.json").write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")

    report = restore_backup(backup_dir, force=False, database_url=f"sqlite:///{tmp_path / 't.db'}")
    assert report is not None
    assert not report.has_loss


def test_restore_native_returns_none_loss_report(tmp_path: Path) -> None:
    """native 模式恢复无交集概念 → 返回 None."""
    archive, target_db = _make_backup_archive(tmp_path)
    report = restore_backup(archive, force=False, database_url=f"sqlite:///{target_db}")
    assert report is None


# ── 0.2.0 备份恢复根因回归（manage_data_role 缺列）────

REVISION_020 = "e5f6a7b8c9d0"  # f7a8b9c0d1e2 之前的 head（0.2.0 时代 schema）


def _make_020_schema_db(tmp_path: Path) -> Path:
    """构造 0.2.0 时代 schema 的库：迁移链建表 + 一行 TablePermission 存量数据."""
    import alembic.command

    from cndb.core.migrations import _build_config

    src_db = tmp_path / "old_020.db"
    cfg = _build_config(f"sqlite:///{src_db}")
    alembic.command.upgrade(cfg, REVISION_020)

    conn = sqlite3.connect(str(src_db))
    try:
        conn.execute(
            "INSERT INTO tables_tablepermission (table_id, read_role, edit_records_role, "
            "edit_views_role, edit_schema_role, comment_role, hidden_fields, row_filters, row_filter_type) "
            "VALUES (7, '', '', '', '', '', '{}', '[]', 'AND')"
        )
        conn.commit()
    finally:
        conn.close()
    return src_db


def test_restore_020_backup_tablepermission_queryable(tmp_path: Path) -> None:
    """恢复 0.2.0 备份后 tables_tablepermission 全列 SELECT 可用（本次故障直接根因回归）.

    故障形态：旧备份 schema 缺 manage_data_role（历史上只加在 ORM 模型上，
    迁移链未覆盖），恢复后 ORM 全列查询报 "no such column"，所有数据表内容
    无法显示。修复后迁移 f7a8b9c0d1e2 在 upgrade head 时补齐该列。
    """
    src_db = _make_020_schema_db(tmp_path)
    # 确认源库确实缺列（模拟 0.2.0 时代 schema）
    conn = sqlite3.connect(str(src_db))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tables_tablepermission)").fetchall()}
    finally:
        conn.close()
    assert "manage_data_role" not in cols

    archive = tmp_path / "old020.tar.gz"
    create_backup(output=archive, mode="native", database_url=f"sqlite:///{src_db}")

    target_db = tmp_path / "target.db"
    restore_backup(archive, force=False, database_url=f"sqlite:///{target_db}")

    conn = sqlite3.connect(str(target_db))
    try:
        # 模拟 ORM 全列 SELECT（含 manage_data_role）不再报 no such column
        rows = conn.execute("SELECT table_id, manage_data_role FROM tables_tablepermission").fetchall()
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        conn.close()
    assert rows == [(7, "")]
    assert version == _alembic_head()


def test_migrate_after_restore_heals_columns_missed_by_chain(tmp_path: Path) -> None:
    """恢复后自愈：迁移链之外的缺列由 heal_schema_drift 兜底补齐.

    构造缺 manage_data_role 但 stamp 已在 head 的库（历史 stamp 掩盖缺列形态）：
    upgrade head 为 no-op，create_all 不修已有表，仅自愈层能补该列。
    """
    src_url = f"sqlite:///{(tmp_path / 'stamped.db').as_posix()}"

    import alembic.command
    import sqlalchemy as sa

    from cndb.core.migrations import _build_config

    cfg = _build_config(src_url)
    alembic.command.upgrade(cfg, REVISION_020)
    engine = sa.create_engine(src_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO tables_tablepermission (table_id, read_role, edit_records_role, "
                    "edit_views_role, edit_schema_role, comment_role, hidden_fields, row_filters, row_filter_type) "
                    "VALUES (3, '', '', '', '', '', '{}', '[]', 'AND')"
                )
            )
        # 模拟历史 stamp：版本标记越过缺列缺口
        from cndb.core.migrations import stamp_head

        stamp_head(src_url)
    finally:
        engine.dispose()

    _migrate_after_restore(src_url, "e5f6a7b8c9d0")

    engine = sa.create_engine(src_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(sa.text("SELECT table_id, manage_data_role FROM tables_tablepermission")).fetchone()
    finally:
        engine.dispose()
    assert row == (3, "")


def test_restore_disposes_global_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """恢复完成后重置全局连接池（同进程恢复读到一致的恢复后数据）."""
    from cndb.core import database as db_mod

    archive, target_db = _make_backup_archive(tmp_path)
    disposed: list[bool] = []

    class _FakeEngine:
        def dispose(self) -> None:
            disposed.append(True)

    monkeypatch.setattr(db_mod, "engine", _FakeEngine())

    restore_backup(archive, force=False, database_url=f"sqlite:///{target_db}")

    assert disposed == [True]


def test_restore_uploads_atomic_copy_failure_preserves_old(tmp_path: Path) -> None:
    """恢复 uploads 时复制中途失败，旧 uploads 必须保持不动（不能先删后复制）.

    触发场景：磁盘空间不足、权限错误等导致 shutil.copy2 抛异常。
    旧实现先 rmtree 再 copy，中途失败会永久丢失旧附件；
    新实现先复制到临时目录，成功后再原子替换，复制失败时旧目录完好。
    """
    src_uploads = tmp_path / "backup" / "uploads"
    src_uploads.mkdir(parents=True)
    (src_uploads / "a.txt").write_text("hello", encoding="utf-8")
    (src_uploads / "b.txt").write_text("world", encoding="utf-8")
    (src_uploads / "1").mkdir()
    (src_uploads / "1" / "c.txt").write_text("nested", encoding="utf-8")

    target = tmp_path / "uploads"
    target.mkdir(parents=True)
    (target / "old.txt").write_text("old", encoding="utf-8")
    (target / "1").mkdir()
    (target / "1" / "old2.txt").write_text("old2", encoding="utf-8")

    call_count: dict[str, int] = {"n": 0}
    _orig_copy = __import__("shutil").copy2

    def _failing_copy(src: Path, dst: Path) -> None:
        call_count["n"] += 1
        if call_count["n"] >= 2:  # 第 2 个文件开始失败
            raise OSError("磁盘空间不足")
        _orig_copy(src, dst)

    with patch("shutil.copy2", side_effect=_failing_copy), pytest.raises(OSError, match="磁盘空间不足"):
        _restore_uploads(src_uploads.parent, target, included=True)

    # 旧 uploads 完好无损 —— 关键断言：不是先删了一半
    assert (target / "old.txt").read_text() == "old"
    assert (target / "1" / "old2.txt").read_text() == "old2"
    assert not (target / "a.txt").exists()  # 新文件未出现
    # 临时目录已清理
    assert not (tmp_path / "uploads.new").exists()
    assert not (tmp_path / "uploads.bak").exists()


def test_restore_uploads_atomic_rename_failure_rolls_back(tmp_path: Path) -> None:
    """rename 替换阶段失败（如目标目录被进程占用）时应回滚到旧 uploads."""
    src_uploads = tmp_path / "backup" / "uploads"
    src_uploads.mkdir(parents=True)
    (src_uploads / "a.txt").write_text("hello", encoding="utf-8")

    target = tmp_path / "uploads"
    target.mkdir(parents=True)
    (target / "old.txt").write_text("old", encoding="utf-8")

    _orig_rename = Path.rename

    def _failing_rename(self: Path, target_path: Path) -> None:
        # 第二次 rename（把 .new 改成正式名）时模拟 Windows 文件占用
        if str(target_path).endswith("uploads") and self.name.endswith(".new"):
            raise OSError("文件被占用")
        _orig_rename(self, target_path)

    with patch.object(Path, "rename", _failing_rename), pytest.raises(OSError, match="文件被占用"):
        _restore_uploads(src_uploads.parent, target, included=True)

    # 旧 uploads 保持不动
    assert (target / "old.txt").read_text() == "old"
    # 残留清理
    assert not (tmp_path / "uploads.bak").exists()
    assert not (tmp_path / "uploads.new").exists()
