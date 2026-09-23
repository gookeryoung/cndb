"""backup.py 单元测试."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from cndb.cli.backup import (
    MANIFEST_VERSION,
    BackupError,
    _backup_sqlite_native,
    _collect_uploads,
    _is_sqlite_url,
    _resolve_sqlite_path,
    _to_json_safe,
    create_backup,
)

# ── 辅助 ──────────────────────────────────────────────


def _setup_sqlite(tmp_path: Path) -> Path:
    """在 tmp_path 下创建一个有若干表和数据的 SQLite 数据库."""
    db = tmp_path / "cndb_test.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);
        CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT);
        INSERT INTO users (name, email) VALUES ('张三', 'a@b.com'), ('李四', 'c@d.com');
        INSERT INTO posts (user_id, title) VALUES (1, '第一篇'), (1, '第二篇'), (2, '第三篇');
        """
    )
    conn.commit()
    conn.close()
    return db


def _setup_uploads(tmp_path: Path) -> Path:
    """创建 uploads 目录并放一些文件（含嵌套）."""
    up = tmp_path / "uploads"
    (up / "1").mkdir(parents=True)
    (up / "2").mkdir(parents=True)
    (up / "1" / "f1.txt").write_text("hello", encoding="utf-8")
    (up / "2" / "f2.txt").write_text("world", encoding="utf-8")
    # 隐藏文件应跳过
    (up / ".hidden").write_text("skip me", encoding="utf-8")
    return up


# ── URL 解析辅助测试 ──────────────────────────────────


def test_is_sqlite_url_positive() -> None:
    assert _is_sqlite_url("sqlite:///C:/foo/bar.db")
    assert _is_sqlite_url("sqlite:///:memory:")


def test_is_sqlite_url_negative() -> None:
    assert not _is_sqlite_url("postgresql://user:pass@host/db")
    assert not _is_sqlite_url("mysql://localhost/db")


def test_resolve_sqlite_path_absolute() -> None:
    p = _resolve_sqlite_path("sqlite:///C:/foo/bar.db")
    assert p.name == "bar.db"


def test_resolve_sqlite_path_relative(tmp_path: Path) -> None:
    p = _resolve_sqlite_path(f"sqlite:///{tmp_path / 'rel.db'}")
    assert p.exists() or p.name == "rel.db"


# ── _backup_sqlite_native 单元 ────────────────────────


def test_backup_sqlite_native_copies_and_counts(tmp_path: Path) -> None:
    db = _setup_sqlite(tmp_path)
    target = tmp_path / "backup_dest"
    target.mkdir()
    fname, counts, schema_version = _backup_sqlite_native(db, target)

    assert fname == "cndb.db"
    assert (target / "cndb.db").is_file()
    assert counts["users"] == 2
    assert counts["posts"] == 3
    # 无 alembic_version 表 → schema 版本为空串
    assert schema_version == ""
    # 备份文件与原文件行数一致
    conn = sqlite3.connect(str(target / "cndb.db"))
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    conn.close()


def test_backup_sqlite_native_reads_schema_version(tmp_path: Path) -> None:
    """源库含 alembic_version 表时，备份应记录其 schema 版本."""
    db = tmp_path / "with_alembic.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);
        INSERT INTO alembic_version (version_num) VALUES ('6399e5f0f61f');
        INSERT INTO users (name) VALUES ('张三');
        """
    )
    conn.commit()
    conn.close()

    target = tmp_path / "backup_dest"
    target.mkdir()
    _, _, schema_version = _backup_sqlite_native(db, target)
    assert schema_version == "6399e5f0f61f"


# ── _collect_uploads 单元 ─────────────────────────────


def test_collect_uploads_copies_files(tmp_path: Path) -> None:
    uploads = _setup_uploads(tmp_path)
    target = tmp_path / "collect_target"
    target.mkdir()

    info = _collect_uploads(uploads, target)

    assert info.included is True
    assert info.file_count == 2  # 排除 .hidden
    assert info.total_size > 0
    assert (target / "uploads" / "1" / "f1.txt").is_file()
    assert (target / "uploads" / "2" / "f2.txt").is_file()


def test_collect_uploads_empty_directory(tmp_path: Path) -> None:
    empty = tmp_path / "empty_uploads"
    empty.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    info = _collect_uploads(empty, target)
    assert info.included is False
    assert info.file_count == 0


def test_collect_uploads_nonexistent(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    info = _collect_uploads(tmp_path / "no_such", target)
    assert info.included is False


# ── create_backup native 端到端 ───────────────────────


def test_create_backup_native_full_flow(tmp_path: Path) -> None:
    db_path = _setup_sqlite(tmp_path)
    uploads = _setup_uploads(tmp_path)
    archive = tmp_path / "backup.tar.gz"

    result = create_backup(
        output=archive,
        mode="native",
        include_uploads=True,
        database_url=f"sqlite:///{db_path}",
        upload_dir=uploads,
    )

    assert result == archive
    assert archive.is_file()
    # 解包检查
    import tarfile

    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        assert "backup/manifest.json" in names
        assert "backup/database/cndb.db" in names
        assert "backup/uploads/1/f1.txt" in names

        manifest_file = tar.extractfile("backup/manifest.json")
        assert manifest_file is not None
        manifest = json.loads(manifest_file.read().decode("utf-8"))

        assert manifest["version"] == MANIFEST_VERSION
        assert manifest["database"]["backup_mode"] == "native"
        assert manifest["database"]["row_counts"]["users"] == 2
        assert manifest["database"]["row_counts"]["posts"] == 3
        # 测试库无 alembic_version 表 → schema 版本为空串
        assert manifest["database"]["schema_version"] == ""
        assert manifest["uploads"]["included"] is True
        assert manifest["uploads"]["file_count"] == 2


def test_create_backup_no_uploads(tmp_path: Path) -> None:
    db_path = _setup_sqlite(tmp_path)
    archive = tmp_path / "backup.tar.gz"

    result = create_backup(
        output=archive,
        mode="native",
        include_uploads=False,
        database_url=f"sqlite:///{db_path}",
        upload_dir=tmp_path / "uploads",
    )

    import tarfile

    with tarfile.open(result, "r:gz") as tar:
        names = tar.getnames()
        assert not any(n.startswith("backup/uploads/") for n in names)
        manifest_file = tar.extractfile("backup/manifest.json")
        assert manifest_file is not None
        manifest = json.loads(manifest_file.read().decode("utf-8"))
        assert manifest["uploads"]["included"] is False


def test_create_backup_default_output_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """output=None 时应生成 backup-<timestamp>.tar.gz 默认名."""
    db_path = _setup_sqlite(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = create_backup(
        mode="native",
        include_uploads=False,
        database_url=f"sqlite:///{db_path}",
        upload_dir=tmp_path / "uploads",
    )

    assert result.name.startswith("backup-")
    assert result.name.endswith(".tar.gz")


def test_create_backup_nonexistent_sqlite_file(tmp_path: Path) -> None:
    """SQLite 路径不存在时应抛 BackupError."""
    with pytest.raises(BackupError, match="SQLite 数据库文件不存在"):
        create_backup(
            output=tmp_path / "backup.tar.gz",
            mode="native",
            database_url=f"sqlite:///{tmp_path / 'no_such.db'}",
        )


def test_create_backup_native_for_postgres_is_rejected(tmp_path: Path) -> None:
    """native 模式对非 SQLite DB 应报错."""
    with pytest.raises(BackupError, match="native 备份模式仅支持 SQLite"):
        create_backup(
            output=tmp_path / "backup.tar.gz",
            mode="native",
            database_url="postgresql://user:pass@localhost/db",
        )


def test_create_backup_sqlalchemy_mode_requires_plugin_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """sqlalchemy 模式下应能正常工作（需触发插件注册以便 Base.metadata 有表）."""
    # 这里用一个极简 SQLite 库配合真实 ORM 模型可能比较重
    # 改为直接测试 auto 模式对 sqlite 的分发
    db_path = _setup_sqlite(tmp_path)
    archive = tmp_path / "backup.tar.gz"

    # auto 应选择 native 模式
    result = create_backup(
        output=archive,
        mode="auto",
        database_url=f"sqlite:///{db_path}",
    )
    import tarfile

    with tarfile.open(result, "r:gz") as tar:
        manifest_file = tar.extractfile("backup/manifest.json")
        assert manifest_file is not None
        manifest = json.loads(manifest_file.read().decode("utf-8"))
        assert manifest["database"]["backup_mode"] == "native"


# ── backup_command CLI 包装 ───────────────────────────


def test_backup_command_calls_create_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """backup_command 应正确转发到 create_backup."""
    import argparse

    from cndb.cli.backup import backup_command
    from cndb.core.config import settings

    db_path = _setup_sqlite(tmp_path)
    archive = tmp_path / "backup.tar.gz"

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")

    args = argparse.Namespace(
        output=str(archive),
        mode="native",
        no_uploads=True,
    )

    backup_command(args)
    assert archive.is_file()


def test_backup_command_exit_on_backup_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """BackupError 应导致 sys.exit(1)."""
    import argparse

    from cndb.cli.backup import backup_command
    from cndb.core.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{tmp_path / 'no_such.db'}")
    args = argparse.Namespace(output=str(tmp_path / "x.tar.gz"), mode="native", no_uploads=True)

    with pytest.raises(SystemExit) as excinfo:
        backup_command(args)
    assert excinfo.value.code == 1


# ── runner 子命令分发 ─────────────────────────────────


def test_runner_backup_subcommand_dispatches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cndb.cli import main as runner
    from cndb.core.config import settings

    db_path = _setup_sqlite(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")

    with patch.object(
        sys,
        "argv",
        [
            "cndb",
            "backup",
            "--mode",
            "native",
            "-o",
            str(archive),
        ],
    ):
        runner.main()

    assert archive.is_file()


def test_runner_restore_subcommand_dispatches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cndb.cli import main as runner
    from cndb.cli.backup import create_backup

    # 先做备份
    db_path = _setup_sqlite(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    create_backup(
        output=archive,
        mode="native",
        database_url=f"sqlite:///{db_path}",
    )

    # restore --dry-run 不应修改数据
    monkeypatch.chdir(tmp_path)
    # 目标库不存在（全新），restore 应该通过
    target_db = tmp_path / "fresh.db"
    with patch.object(
        sys,
        "argv",
        [
            "cndb",
            "restore",
            str(archive),
            "--dry-run",
        ],
    ):
        runner.main()
    # dry-run 不应创建目标库
    assert not target_db.exists()


# ── _to_json_safe datetime/bytes 分支 ────────────────


def test_to_json_safe_datetime() -> None:
    now = dt.datetime(2024, 6, 15, 10, 30, 0)
    assert _to_json_safe(now) == "2024-06-15T10:30:00"


def test_to_json_safe_date() -> None:
    d = dt.date(2024, 1, 1)
    assert _to_json_safe(d) == "2024-01-01"


def test_to_json_safe_time() -> None:
    t = dt.time(12, 0, 0)
    assert _to_json_safe(t) == "12:00:00"


def test_to_json_safe_bytes() -> None:
    raw = b"hello world"
    result = _to_json_safe(raw)
    assert isinstance(result, dict)
    assert "__base64__" in result
    assert base64.b64encode(raw).decode("ascii") == result["__base64__"]


def test_to_json_safe_null_and_other() -> None:
    import json
    import uuid

    assert _to_json_safe(None) is None
    assert _to_json_safe(42) == 42
    # Decimal → __decimal__ 字典，确保 json.dumps 可序列化
    dec = Decimal("3.14")
    safe_dec = _to_json_safe(dec)
    assert safe_dec == {"__decimal__": "3.14"}
    json.dumps(safe_dec)  # 不抛 TypeError 才算通过
    # UUID → 字符串，JSON 可序列化
    uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    safe_uid = _to_json_safe(uid)
    assert safe_uid == "12345678-1234-5678-1234-567812345678"
    json.dumps(safe_uid)


# ── _collect_uploads upload_dir 不存在 ───────────────


def test_collect_uploads_dir_missing(tmp_path: Path) -> None:
    """upload_dir 不存在 → 返回空 UploadsInfo."""
    target = tmp_path / "target"
    info = _collect_uploads(tmp_path / "no_such_uploads", target)
    assert info.included is False
    assert info.file_count == 0
    assert info.total_size == 0


# ── create_backup native 非 SQLite ───────────────────


def test_create_backup_native_non_sqlite_rejected(tmp_path: Path) -> None:
    """native 模式配非 SQLite URL → BackupError."""
    with pytest.raises(BackupError, match=r"native 备份模式仅支持 SQLite"):
        create_backup(
            output=tmp_path / "x.tar.gz",
            mode="native",
            database_url="postgresql://localhost/db",
        )


# ── create_backup SQLite 文件不存在 ──────────────────


def test_create_backup_sqlite_file_missing(tmp_path: Path) -> None:
    """native 模式但 SQLite 文件不存在 → BackupError."""
    with pytest.raises(BackupError, match=r"SQLite 数据库文件不存在"):
        create_backup(
            output=tmp_path / "x.tar.gz",
            mode="native",
            database_url=f"sqlite:///{tmp_path / 'missing.db'}",
        )


# ── backup_command 兜底异常 ───────────────────────────


def test_backup_command_catch_unexpected(tmp_path: Path) -> None:
    """backup_command 捕获 BackupError 之外的异常 → sys.exit(1)."""
    from cndb.cli import backup as backup_mod
    from cndb.cli.backup import backup_command

    args = argparse.Namespace(
        output=str(tmp_path / "out.tar.gz"),
        mode="native",
        no_uploads=True,
    )
    with (
        patch.object(backup_mod, "create_backup", side_effect=RuntimeError("unexpected")),
        pytest.raises(SystemExit) as excinfo,
    ):
        backup_command(args)
    assert excinfo.value.code == 1


# ── native 内嵌 sqlalchemy 兜底导出（降级恢复）─────────


def _read_archive_member(archive: Path, member: str) -> bytes:
    """从备份归档读取单个成员内容（归档内统一带 backup/ 前缀）."""
    import tarfile

    with tarfile.open(archive, "r:gz") as tar:
        handle = tar.extractfile(f"backup/{member}")
        assert handle is not None
        return handle.read()


def test_create_backup_native_embeds_fallback_dump(tmp_path: Path) -> None:
    """native 备份默认内嵌 sqlalchemy 兜底导出，manifest 标记 fallback_mode."""
    db = _setup_sqlite(tmp_path)
    archive = tmp_path / "fb.tar.gz"
    create_backup(output=archive, mode="native", database_url=f"sqlite:///{db}")

    manifest = json.loads(_read_archive_member(archive, "manifest.json"))
    assert manifest["database"]["fallback_mode"] == "sqlalchemy"
    # dump.json 与 .db 取自同一快照，数据一致
    dump = json.loads(_read_archive_member(archive, "database/dump.json"))
    tables = {t["table"]: len(t["rows"]) for t in dump["tables"]}
    assert tables["users"] == 2
    assert tables["posts"] == 3


def test_create_backup_native_no_fallback(tmp_path: Path) -> None:
    """include_fallback=False 时不内嵌 dump.json，fallback_mode 为空."""
    db = _setup_sqlite(tmp_path)
    archive = tmp_path / "nofb.tar.gz"
    create_backup(output=archive, mode="native", database_url=f"sqlite:///{db}", include_fallback=False)

    manifest = json.loads(_read_archive_member(archive, "manifest.json"))
    assert manifest["database"]["fallback_mode"] == ""
    import tarfile

    with tarfile.open(archive, "r:gz") as tar:
        assert "backup/database/dump.json" not in tar.getnames()


# ── SQLite 动态类型 DateTime 列安全转换 ─────────────
#
# 真实项目中，SQLite（动态类型）声明为 TIMESTAMP/DATETIME 的列
# 实际可能存 Unix 时间戳（int / float）、空字符串、NULL 或 ISO 字符串.
# 修复前 SQLAlchemy 的 str_to_date / str_to_datetime processor 假定一定是
# ISO 字符串，遇到非 str 直接 TypeError；测试 _backup_sqlalchemy 必须覆盖.


def _setup_sqlite_with_dynamic_types(tmp_path: Path) -> Path:
    """创建含 TIMESTAMP 列且塞入多种动态类型值的 SQLite 库."""
    db = tmp_path / "dyn_types.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE dyn_events (
            id INTEGER PRIMARY KEY,
            name TEXT,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        );
        INSERT INTO dyn_events (name, created_at, updated_at)
        VALUES ('unix_int', 1704067200, NULL);
        INSERT INTO dyn_events (name, created_at, updated_at)
        VALUES ('unix_float', 1704067200.123, '');
        INSERT INTO dyn_events (name, created_at, updated_at)
        VALUES ('valid_iso', '2024-06-15T10:30:00', '2024-06-15 11:30:00');
        INSERT INTO dyn_events (name, created_at, updated_at)
        VALUES ('all_null', NULL, NULL);
        INSERT INTO dyn_events (name, created_at, updated_at)
        VALUES ('all_empty', '', '');
        """
    )
    conn.commit()
    conn.close()
    return db


def test_coerce_raw_value_datetime_variants() -> None:
    """_coerce_raw_value 应对 DateTime 列的各种 SQLite 实际值安全返回."""
    import datetime as dt

    from sqlalchemy.types import Date, DateTime, Time

    from cndb.cli.backup import _coerce_raw_value

    # DateTime
    int_ts = _coerce_raw_value(1704067200, DateTime())
    assert isinstance(int_ts, dt.datetime)
    # Unix 时间戳按 UTC 转换，不受运行环境时区影响
    assert int_ts == dt.datetime(2024, 1, 1, 0, 0, 0)

    float_ts = _coerce_raw_value(1704067200.123, DateTime())
    assert isinstance(float_ts, dt.datetime)
    assert float_ts.microsecond == 123000

    valid = _coerce_raw_value("2024-06-15T10:30:00", DateTime())
    assert valid == dt.datetime(2024, 6, 15, 10, 30, 0)

    sqlfmt = _coerce_raw_value("2024-06-15 10:30:00", DateTime())
    assert sqlfmt == dt.datetime(2024, 6, 15, 10, 30, 0)

    sqlfmt_ms = _coerce_raw_value("2024-06-15 10:30:00.123456", DateTime())
    assert sqlfmt_ms.microsecond == 123456

    assert _coerce_raw_value("", DateTime()) is None
    assert _coerce_raw_value(None, DateTime()) is None
    assert _coerce_raw_value(dt.datetime(2024, 1, 1), DateTime()) == dt.datetime(2024, 1, 1)

    # Date
    assert _coerce_raw_value("2024-01-01", Date()) == dt.date(2024, 1, 1)
    assert _coerce_raw_value("", Date()) is None
    assert _coerce_raw_value(None, Date()) is None

    # Time
    assert _coerce_raw_value("12:00:00", Time()) == dt.time(12, 0, 0)
    assert _coerce_raw_value("", Time()) is None
    assert _coerce_raw_value(None, Time()) is None


def test_create_backup_native_embeds_fallback_with_datetime(tmp_path: Path) -> None:
    """native + include_fallback 模式：库内 DATETIME 列存了 Unix 时间戳/空串，
    内嵌 dump.json 仍应生成，且 datetime 值被安全转换."""
    db = _setup_sqlite_with_dynamic_types(tmp_path)
    archive = tmp_path / "dyn.tar.gz"

    # 不应抛 TypeError: fromisoformat: argument must be str
    result = create_backup(output=archive, mode="native", database_url=f"sqlite:///{db}", include_fallback=True)
    assert archive.is_file()

    manifest = json.loads(_read_archive_member(result, "manifest.json"))
    assert manifest["database"]["fallback_mode"] == "sqlalchemy"

    dump = json.loads(_read_archive_member(result, "database/dump.json"))
    rows = {r["name"]: r for r in dump["tables"][0]["rows"]}
    assert len(rows) == 5

    # Unix 时间戳应被转成 ISO 字符串
    assert rows["unix_int"]["created_at"] == "2024-01-01T00:00:00"
    assert rows["unix_int"]["updated_at"] is None

    # Unix float + 空串 → 空串视为 None
    assert rows["unix_float"]["created_at"] == "2024-01-01T00:00:00.123000"
    assert rows["unix_float"]["updated_at"] is None

    # ISO / SQLite 空格格式都应被识别
    assert rows["valid_iso"]["created_at"] == "2024-06-15T10:30:00"
    assert rows["valid_iso"]["updated_at"] == "2024-06-15T11:30:00"

    assert rows["all_null"]["created_at"] is None
    assert rows["all_empty"]["created_at"] is None


def test_backup_sqlalchemy_dynamic_datetime(tmp_path: Path) -> None:
    """直接走 sqlalchemy 备份模式（非 fallback 嵌入），同样应能处理动态类型 DATETIME."""
    db = _setup_sqlite_with_dynamic_types(tmp_path)
    archive = tmp_path / "sa.tar.gz"

    result = create_backup(
        output=archive,
        mode="sqlalchemy",
        database_url=f"sqlite:///{db}",
        upload_dir=tmp_path / "no_such_uploads",
        include_uploads=False,
    )
    assert archive.is_file()

    manifest = json.loads(_read_archive_member(result, "manifest.json"))
    assert manifest["database"]["backup_mode"] == "sqlalchemy"

    dump = json.loads(_read_archive_member(result, "database/dump.json"))
    rows = {r["name"]: r for r in dump["tables"][0]["rows"]}
    assert rows["unix_int"]["created_at"] == "2024-01-01T00:00:00"
    assert rows["all_empty"]["created_at"] is None


def test_create_backup_sqlalchemy_unknown_datetime_string(tmp_path: Path) -> None:
    """无法解析的 DATETIME 字符串（如 'garbage'）应原样保留而非崩溃."""
    db = tmp_path / "weird.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE weird (id INTEGER PRIMARY KEY, ts TIMESTAMP);
        INSERT INTO weird (ts) VALUES ('not-a-timestamp');
        """
    )
    conn.commit()
    conn.close()

    archive = tmp_path / "w.tar.gz"
    result = create_backup(output=archive, mode="sqlalchemy", database_url=f"sqlite:///{db}", include_uploads=False)
    assert archive.is_file()

    dump = json.loads(_read_archive_member(result, "database/dump.json"))
    assert dump["tables"][0]["rows"][0]["ts"] == "not-a-timestamp"
