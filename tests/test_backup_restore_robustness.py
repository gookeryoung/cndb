"""备份与恢复健壮性测试套件.

按用户验收要求分四组：

1. 备份完整性 / 一致性 / 稳定性（TestBackupIntegrity）：
   行数对账、重复备份结果一致、归档 gzip CRC 校验、备份期间并发写入的
   快照一致性、并行双产物有效性；
2. 跨版本恢复准确性（TestRestoreCrossVersion）：
   不同 schema 版本备份恢复到当前版本、边界值数据逐字段 roundtrip、空库；
3. 恢复冲突处理（TestRestoreConflict）：
   目标冲突的错误明细、force 完整覆盖、sqlalchemy 模式清空冲突旧表；
4. 极端场景（TestExtremeScenarios）：
   数据库不可达（网络中断等价形态）、磁盘空间不足、数据文件损坏、
   归档内容损坏、解压中断。

每个用例按 前置条件 → 执行步骤 → 预期结果 组织，均使用 tmp_path 隔离，
可重复、相互独立。
"""

from __future__ import annotations

import io
import json
import sqlite3
import tarfile
import threading
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError

from cndb.cli.backup import create_backup
from cndb.cli.restore import inspect_backup, restore_backup

REVISION_INITIAL = "6399e5f0f61f"
REVISION_020 = "e5f6a7b8c9d0"


def _alembic_head() -> str:
    import alembic.script

    from cndb.core.migrations import _build_config

    cfg = _build_config("sqlite:///:memory:")
    return str(alembic.script.ScriptDirectory.from_config(cfg).get_current_head())


def _setup_sqlite(db: Path) -> Path:
    """前置辅助：创建含多表多行数据的 SQLite 库."""
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);
        CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT);
        INSERT INTO users (name, email) VALUES ('张三', 'a@example.com'), ('李四', 'b@example.com');
        INSERT INTO posts (user_id, title) VALUES (1, '第一篇'), (1, '第二篇'), (2, '第三篇');
        """
    )
    conn.commit()
    conn.close()
    return db


def _make_backup_archive(tmp_path: Path, src_db: Path | None = None, **kwargs: object) -> Path:
    """辅助：对给定源库做 native 备份，返回归档路径."""
    src = src_db or _setup_sqlite(tmp_path / "src.db")
    archive = tmp_path / "backup.tar.gz"
    create_backup(output=archive, mode="native", database_url=f"sqlite:///{src}", **kwargs)  # type: ignore[arg-type]
    return archive


def _read_manifest(archive: Path) -> dict:
    """辅助：从归档读取 manifest.json."""
    with tarfile.open(archive, "r:gz") as tar:
        handle = tar.extractfile("backup/manifest.json")
        assert handle is not None
        return json.loads(handle.read().decode("utf-8"))


def _read_archive_db(archive: Path, member: str = "backup/data/cndb.db") -> Path:
    """辅助：解包归档内数据库文件到临时目录."""
    out = archive.parent / (archive.stem + ".extracted.db")
    with tarfile.open(archive, "r:gz") as tar:
        handle = tar.extractfile(member)
        assert handle is not None
        out.write_bytes(handle.read())
    return out


# ── 1. 备份完整性 / 一致性 / 稳定性 ──────────────────


class TestBackupIntegrity:
    """备份产物完整性、数据一致性与过程稳定性."""

    def test_backup_row_counts_match_source(self, tmp_path: Path) -> None:
        """前置：多表多行源库；步骤：备份并对账；预期：manifest 行数与源库逐表一致."""
        src = _setup_sqlite(tmp_path / "src.db")
        archive = _make_backup_archive(tmp_path, src)

        manifest = _read_manifest(archive)
        conn = sqlite3.connect(str(src))
        try:
            for table, expected in manifest["database"]["row_counts"].items():
                actual = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # nosec B608 - 表名来自 manifest 枚举
                assert actual == expected, f"表 {table} 行数对账失败"
        finally:
            conn.close()

    def test_backup_repeatable_identical_content(self, tmp_path: Path) -> None:
        """前置：同一源库；步骤：连续两次备份；预期：两次产物的行数清单与库内数据一致（可重复）."""
        src = _setup_sqlite(tmp_path / "src.db")
        archive1 = _make_backup_archive(tmp_path, src)
        archive2 = tmp_path / "backup2.tar.gz"
        create_backup(output=archive2, mode="native", database_url=f"sqlite:///{src}")

        m1, m2 = _read_manifest(archive1), _read_manifest(archive2)
        assert m1["database"]["row_counts"] == m2["database"]["row_counts"]

        db1 = _read_archive_db(archive1)
        db2 = _read_archive_db(archive2)
        conn1 = sqlite3.connect(str(db1))
        conn2 = sqlite3.connect(str(db2))
        try:
            for table in m1["database"]["row_counts"]:
                rows1 = conn1.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()  # nosec B608 - 表名来自 manifest 枚举
                rows2 = conn2.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()  # nosec B608 - 同上
                assert rows1 == rows2, f"表 {table} 两次备份数据不一致"
        finally:
            conn1.close()
            conn2.close()

    def test_backup_archive_gzip_crc_valid(self, tmp_path: Path) -> None:
        """前置：正常备份产物；步骤：以 r:gz 全量解包所有成员；预期：无 CRC/结构错误（归档完整）."""
        archive = _make_backup_archive(tmp_path)
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                handle = tar.extractfile(member)
                if handle is not None:
                    handle.read()  # 完整读取触发 gzip CRC 校验

    def test_backup_during_concurrent_writes_snapshot_consistent(self, tmp_path: Path) -> None:
        """前置：源库持续被并发写入；步骤：备份同时另一线程逐行插入；
        预期：备份产物自身一致 —— manifest 行数与库内实际行数相等（快照语义）."""
        src = _setup_sqlite(tmp_path / "src.db")
        archive = tmp_path / "backup.tar.gz"
        errors: list[Exception] = []

        def writer() -> None:
            conn = sqlite3.connect(str(src), timeout=10)
            try:
                for i in range(20):
                    conn.execute("INSERT INTO posts (user_id, title) VALUES (1, ?)", (f"并发行{i}",))
                    conn.commit()
            except Exception as exc:  # pragma: no cover - 仅在意外锁失败时记录
                errors.append(exc)
            finally:
                conn.close()

        t = threading.Thread(target=writer)
        t.start()
        try:
            create_backup(output=archive, mode="native", database_url=f"sqlite:///{src}")
        finally:
            t.join()
        assert errors == []

        # 快照一致性：备份文件行数与 manifest 记录完全相等
        snap = _read_archive_db(archive)
        manifest = _read_manifest(archive)
        conn = sqlite3.connect(str(snap))
        try:
            for table, expected in manifest["database"]["row_counts"].items():
                actual = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # nosec B608 - 表名来自 manifest 枚举
                assert actual == expected, f"表 {table}: 快照 {actual} 行 != manifest {expected} 行"
        finally:
            conn.close()

        # 源库最终行数不少于快照（并发写入全部落库）
        final = sqlite3.connect(str(src))
        try:
            assert (
                final.execute("SELECT COUNT(*) FROM posts").fetchone()[0] >= manifest["database"]["row_counts"]["posts"]
            )
        finally:
            final.close()

    def test_backup_parallel_two_outputs_valid(self, tmp_path: Path) -> None:
        """前置：同一源库；步骤：两线程并行各产出一份备份；预期：两份产物均完整且行数一致."""
        src = _setup_sqlite(tmp_path / "src.db")
        a1, a2 = tmp_path / "p1.tar.gz", tmp_path / "p2.tar.gz"
        errors: list[Exception] = []

        def run(output: Path) -> None:
            try:
                create_backup(output=output, mode="native", database_url=f"sqlite:///{src}")
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        t1, t2 = threading.Thread(target=run, args=(a1,)), threading.Thread(target=run, args=(a2,))
        t1.start(), t2.start()
        t1.join(), t2.join()
        assert errors == []
        assert _read_manifest(a1)["database"]["row_counts"] == _read_manifest(a2)["database"]["row_counts"]


# ── 2. 跨版本恢复准确性 ──────────────────────────────


class TestRestoreCrossVersion:
    """不同 schema 版本备份文件的恢复准确性."""

    @pytest.mark.parametrize("revision", [REVISION_INITIAL, REVISION_020], ids=["initial", "0.2.0"])
    def test_restore_old_version_backup_migrates_and_preserves_rows(self, tmp_path: Path, revision: str) -> None:
        """前置：指定历史 revision 的 schema 库含业务数据；步骤：备份 → 恢复；
        预期：alembic_version 收敛到 head 且业务行数零丢失."""
        import alembic.command

        from cndb.core.migrations import _build_config

        src = tmp_path / "old.db"
        cfg = _build_config(f"sqlite:///{src.as_posix()}")
        alembic.command.upgrade(cfg, revision)
        conn = sqlite3.connect(str(src))
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(workspaces_workspace)")}
            for i in range(3):
                values: dict[str, object] = {"name": f"跨版本{i}", "description": ""}
                if "visibility" in cols:
                    values["visibility"] = "PRIVATE"  # ORM Enum 以成员名存储
                if "tags" in cols:
                    values["tags"] = "[]"
                if "allow_edit" in cols:
                    values["allow_edit"] = 1
                if "created_at" in cols:
                    values["created_at"] = "2026-01-01 00:00:00"
                if "updated_at" in cols:
                    values["updated_at"] = "2026-01-01 00:00:00"
                col_list = ", ".join(values)
                placeholders = ", ".join("?" for _ in values)
                conn.execute(
                    f"INSERT INTO workspaces_workspace ({col_list}) VALUES ({placeholders})",  # nosec B608 - 列名来自 PRAGMA 枚举
                    tuple(values.values()),
                )
            conn.commit()
        finally:
            conn.close()

        archive = _make_backup_archive(tmp_path, src)
        target = tmp_path / "target.db"
        restore_backup(archive, force=False, database_url=f"sqlite:///{target}")

        conn = sqlite3.connect(str(target))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            count = conn.execute("SELECT COUNT(*) FROM workspaces_workspace").fetchone()[0]
        finally:
            conn.close()
        assert version == _alembic_head()
        assert count == 3

    def test_restore_roundtrip_field_level_accuracy(self, tmp_path: Path) -> None:
        """前置：源库含边界值数据（emoji/单引号/换行/超长文本/NULL/负数/中文）；
        步骤：备份 → 恢复；预期：逐字段值完全相等（边界值零失真）."""
        src = tmp_path / "edge.db"
        long_text = "长" * 5000
        conn = sqlite3.connect(str(src))
        conn.executescript(
            """
            CREATE TABLE edges (
                id INTEGER PRIMARY KEY,
                emoji TEXT, quote TEXT, newline TEXT,
                long_text TEXT, nullable TEXT, negative INTEGER
            );
            """
        )
        conn.execute(
            "INSERT INTO edges (emoji, quote, newline, long_text, nullable, negative) VALUES (?, ?, ?, ?, ?, ?)",
            ("🎉🚀中文", "单'引号", "行1\n行2", long_text, None, -42),
        )
        conn.commit()
        conn.close()

        archive = _make_backup_archive(tmp_path, src)
        target = tmp_path / "target.db"
        restore_backup(archive, force=False, database_url=f"sqlite:///{target}")

        r_src = sqlite3.connect(str(src)).execute("SELECT * FROM edges").fetchall()
        r_dst = sqlite3.connect(str(target)).execute("SELECT * FROM edges").fetchall()
        assert r_src == r_dst
        assert r_dst[0][1] == "🎉🚀中文"
        assert r_dst[0][3] == "行1\n行2"
        assert r_dst[0][4] == long_text
        assert r_dst[0][5] is None and r_dst[0][6] == -42

    def test_restore_empty_database(self, tmp_path: Path) -> None:
        """前置：无任何用户表的空库；步骤：备份 → 恢复；预期：流程成功，
        恢复后自动迁移建出当前 schema（空数据零丢失、不报错）."""
        src = tmp_path / "empty.db"
        sqlite3.connect(str(src)).close()
        archive = _make_backup_archive(tmp_path, src)

        target = tmp_path / "target.db"
        restore_backup(archive, force=False, database_url=f"sqlite:///{target}")
        conn = sqlite3.connect(str(target))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            count = conn.execute("SELECT COUNT(*) FROM workspaces_workspace").fetchone()[0]
        finally:
            conn.close()
        assert version == _alembic_head()
        assert count == 0


# ── 3. 恢复冲突处理 ──────────────────────────────────


class TestRestoreConflict:
    """恢复过程中的数据冲突处理机制."""

    def test_restore_conflict_error_details(self, tmp_path: Path) -> None:
        """前置：目标库已含 2 表 4 行数据；步骤：不带 force 恢复；
        预期：RestoreError 且错误信息含精确表数与行数（冲突可诊断）."""
        from cndb.cli.restore import RestoreError

        archive = _make_backup_archive(tmp_path)
        target = tmp_path / "target.db"
        conn = sqlite3.connect(str(target))
        conn.executescript(
            "CREATE TABLE t1 (a INTEGER); CREATE TABLE t2 (b TEXT);"
            "INSERT INTO t1 VALUES (1), (2); INSERT INTO t2 VALUES ('x'), ('y');"
        )
        conn.commit()
        conn.close()

        with pytest.raises(RestoreError, match=r"已有 2 张表、4 行数据"):
            restore_backup(archive, force=False, database_url=f"sqlite:///{target}")

    def test_restore_force_resolves_conflict_completely(self, tmp_path: Path) -> None:
        """前置：目标库含冲突旧数据；步骤：force 恢复；预期：目标内容与备份完全一致，旧表零残留."""
        archive = _make_backup_archive(tmp_path)
        target = tmp_path / "target.db"
        conn = sqlite3.connect(str(target))
        conn.execute("CREATE TABLE legacy_conflict (a TEXT)")
        conn.execute("INSERT INTO legacy_conflict VALUES ('旧数据')")
        conn.commit()
        conn.close()

        restore_backup(archive, force=True, database_url=f"sqlite:///{target}")

        conn = sqlite3.connect(str(target))
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            assert "legacy_conflict" not in tables
            assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
            assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 3
        finally:
            conn.close()

    def test_restore_sqlalchemy_clears_conflicting_tables(self, tmp_path: Path) -> None:
        """前置：当前 schema 源库含业务数据 + 目标库含无关旧表；步骤：sqlalchemy 模式恢复；
        预期：drop_all 重建后无关旧表被清除，备份数据正常导入."""
        from sqlalchemy import create_engine

        from cndb.core.plugin_registry import plugin_registry
        from cndb.models.base import Base

        src = tmp_path / "src.db"
        plugin_registry.discover_and_load()
        engine = create_engine(f"sqlite:///{src}")
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as conn:
                conn.execute(
                    Base.metadata.tables["workspaces_workspace"].insert().values(name="SA恢复", description="")
                )
        finally:
            engine.dispose()
        archive = tmp_path / "sa.tar.gz"
        create_backup(output=archive, mode="sqlalchemy", database_url=f"sqlite:///{src}", include_uploads=False)

        target = tmp_path / "target.db"
        conn = sqlite3.connect(str(target))
        conn.execute("CREATE TABLE conflicting_old (a TEXT)")
        conn.commit()
        conn.close()

        restore_backup(archive, force=True, database_url=f"sqlite:///{target}")

        conn = sqlite3.connect(str(target))
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            assert "conflicting_old" not in tables
            assert conn.execute("SELECT COUNT(*) FROM workspaces_workspace").fetchone()[0] == 1
        finally:
            conn.close()


# ── 4. 极端场景 ──────────────────────────────────────


class TestExtremeScenarios:
    """网络中断 / 磁盘空间不足 / 数据文件损坏 / 解压中断等异常场景."""

    def test_backup_unreachable_database_url(self, tmp_path: Path) -> None:
        """前置：DATABASE_URL 指向不可打开的库文件（父级为文件，等价网络中断的连接失败形态）；
        步骤：sqlalchemy 模式备份；预期：SQLAlchemyError 传播，不产出半成品."""
        blocker = tmp_path / "blocker.txt"
        blocker.write_text("not a dir", encoding="utf-8")
        bad_url = f"sqlite:///{blocker / 'db.db'}"

        with pytest.raises(SQLAlchemyError):
            create_backup(
                output=tmp_path / "out.tar.gz",
                mode="sqlalchemy",
                database_url=bad_url,
                include_uploads=False,
            )
        assert not (tmp_path / "out.tar.gz").exists()

    def test_restore_unreachable_target_url(self, tmp_path: Path) -> None:
        """前置：合法目录备份 + 不可打开的目标库 URL；步骤：sqlalchemy 恢复；
        预期：SQLAlchemyError 传播（连接失败不被吞掉）."""
        import json as json_mod

        from cndb.cli.restore import RestoreError

        backup_dir = tmp_path / "bk"
        (backup_dir / "data").mkdir(parents=True)
        (backup_dir / "manifest.json").write_text(
            json_mod.dumps(
                {
                    "version": "1",
                    "app_version": "1.0",
                    "created_at": "2026-01-01T00:00:00",
                    "database": {
                        "db_type": "sqlite",
                        "backup_mode": "sqlalchemy",
                        "schema_version": "",
                        "fallback_mode": "",
                        "tables": [],
                        "row_counts": {},
                    },
                    "uploads": {"included": False, "file_count": 0, "total_size": 0},
                }
            ),
            encoding="utf-8",
        )
        (backup_dir / "data" / "dump.json").write_text('{"tables": []}', encoding="utf-8")

        blocker = tmp_path / "blocker2.txt"
        blocker.write_text("not a dir", encoding="utf-8")
        # _check_target_safe 对不可打开的文件会因 sqlite3.connect 创建失败抛错（Windows），
        # 或 restore 时 reflect 失败 —— 两者都应向上传播
        with pytest.raises((SQLAlchemyError, RestoreError, sqlite3.OperationalError)):
            restore_backup(backup_dir, force=False, database_url=f"sqlite:///{blocker / 't.db'}")

    def test_backup_disk_full_aborts_without_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """前置：打包阶段磁盘写满（模拟 ENOSPC）；步骤：create_backup；
        预期：OSError 传播且不产出残缺归档."""
        from cndb.cli import backup as backup_mod

        def _enospc(*args: object, **kwargs: object) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(backup_mod.tarfile, "open", _enospc)
        src = _setup_sqlite(tmp_path / "src.db")
        output = tmp_path / "out.tar.gz"
        with pytest.raises(OSError, match="No space left"):
            create_backup(output=output, mode="native", database_url=f"sqlite:///{src}")
        assert not output.exists()

    def test_backup_corrupt_source_db(self, tmp_path: Path) -> None:
        """前置：源 .db 文件内容损坏（非 SQLite 格式字节）；步骤：native 备份；
        预期：sqlite3.DatabaseError 传播，不静默产出无效备份."""
        src = tmp_path / "corrupt.db"
        src.write_bytes(b"this is not a sqlite database at all......")
        with pytest.raises(sqlite3.DatabaseError):
            create_backup(output=tmp_path / "out.tar.gz", mode="native", database_url=f"sqlite:///{src}")

    def _make_archive_with_corrupt_db(self, tmp_path: Path) -> Path:
        """构造 manifest 正常但 data/cndb.db 为乱码的归档."""
        archive = tmp_path / "corrupt_inner.tar.gz"
        manifest = {
            "version": "1",
            "app_version": "1.0",
            "created_at": "2026-01-01T00:00:00",
            "database": {
                "db_type": "sqlite",
                "backup_mode": "native",
                "schema_version": "",
                "fallback_mode": "",
                "tables": [],
                "row_counts": {},
            },
            "uploads": {"included": False, "file_count": 0, "total_size": 0},
        }
        with tarfile.open(archive, "w:gz") as tar:
            data = json.dumps(manifest).encode("utf-8")
            info = tarfile.TarInfo(name="backup/manifest.json")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            junk = b"corrupted database payload" * 10
            info2 = tarfile.TarInfo(name="backup/data/cndb.db")
            info2.size = len(junk)
            tar.addfile(info2, io.BytesIO(junk))
        return archive

    def test_restore_corrupt_db_inside_archive(self, tmp_path: Path) -> None:
        """前置：归档内 cndb.db 损坏；步骤：native 恢复；预期：DatabaseError 传播，
        目标库不被写入半恢复状态."""
        archive = self._make_archive_with_corrupt_db(tmp_path)
        target = tmp_path / "target.db"
        with pytest.raises(sqlite3.DatabaseError):
            restore_backup(archive, force=False, database_url=f"sqlite:///{target}")
        # 目标库未被产出为有效库（backup() 在写入页前即失败）
        if target.exists():
            conn = sqlite3.connect(str(target))
            try:
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            finally:
                conn.close()
            assert tables == []

    def test_restore_truncated_dump_json(self, tmp_path: Path) -> None:
        """前置：目录备份内 dump.json 被截断（非法 JSON）；步骤：sqlalchemy 恢复；
        预期：JSONDecodeError 传播，不静默导入空数据."""
        backup_dir = tmp_path / "bk"
        (backup_dir / "data").mkdir(parents=True)
        (backup_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "version": "1",
                    "app_version": "1.0",
                    "created_at": "2026-01-01T00:00:00",
                    "database": {
                        "db_type": "sqlite",
                        "backup_mode": "sqlalchemy",
                        "schema_version": "",
                        "fallback_mode": "",
                        "tables": [],
                        "row_counts": {},
                    },
                    "uploads": {"included": False, "file_count": 0, "total_size": 0},
                }
            ),
            encoding="utf-8",
        )
        (backup_dir / "data" / "dump.json").write_text('{"tables": [{"table": "users"', encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            restore_backup(backup_dir, force=False, database_url=f"sqlite:///{tmp_path / 't.db'}")

    def test_restore_disk_full_during_extract(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """前置：解压阶段磁盘写满；步骤：native 恢复；
        预期：OSError 传播，目标库未被创建（失败不产生半恢复状态）."""

        def _enospc(*args: object, **kwargs: object) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(tarfile.TarFile, "extractall", _enospc)
        archive = _make_backup_archive(tmp_path)
        target = tmp_path / "target.db"
        with pytest.raises(OSError, match="No space left"):
            restore_backup(archive, force=False, database_url=f"sqlite:///{target}")
        assert not target.exists()

    def test_inspect_detects_truncated_archive(self, tmp_path: Path) -> None:
        """前置：合法备份归档被截断（去掉尾部字节）；步骤：inspect_backup；
        预期：RestoreError（归档损坏可被检出，不会带病恢复）."""
        from cndb.cli.restore import RestoreError

        archive = _make_backup_archive(tmp_path)
        raw = archive.read_bytes()
        truncated = tmp_path / "truncated.tar.gz"
        truncated.write_bytes(raw[: len(raw) // 2])

        with pytest.raises(RestoreError, match=r"归档损坏|无法打开"):
            inspect_backup(truncated)
