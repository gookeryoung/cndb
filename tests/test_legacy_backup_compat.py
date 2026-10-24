"""examples 历史版本备份向前兼容回归测试.

针对 examples/backups/ 下随仓库保存的历史版本备份归档（文件名
``cndb-backup-<软件版本>-v<数据库格式版本>-<时间戳>.tar.gz``），逐个验证新版程序：

1. inspect_backup 读取 manifest 元信息（协议版本、软件版本、归档布局可解析）；
2. manifest 与归档内容自洽（表清单/兜底导出/附件统计），且 schema 版本不领先；
3. restore_backup 恢复并把 schema 自动迁移到当前 alembic head；
4. 恢复后的各表行数与 manifest 记录一致（旧数据零丢失）；
5. 恢复后 schema 覆盖当前 ORM 模型全列（缺列自愈无残留）；
6. 业务身份数据（工作区名/用户名/数据表名）与备份源库完全一致；
7. 内嵌兜底导出（fallback_mode=sqlalchemy）的备份可用 sqlalchemy 模式降级恢复，
   且裁剪报告（跳过表/丢弃列）与当前模型口径一致；无兜底的旧备份显式报错；
8. 在升级后的库上立即执行完整 seed 重新生成演示数据并保存落库。

新增历史备份文件无需修改测试：参数化自动纳入下一个 ``cndb-backup-*.tar.gz``。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import tarfile
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.cli.backup import MANIFEST_VERSION
from cndb.cli.restore import RestoreError, _schema_revision_known, inspect_backup, restore_backup

# 仓库根 examples/backups（本文件位于 tests/ 下，向上一级即仓库根）
BACKUP_DIR = Path(__file__).resolve().parents[1] / "examples" / "backups"

_ARCHIVES = sorted(BACKUP_DIR.glob("cndb-backup-*.tar.gz"))

# 已被迁移删除的表：历史备份 manifest 仍记录其行数，但恢复到当前 head 时
# 该表按迁移链被丢弃（reports_template 于 c2d3e4f5a6b7 删除；
# documents_permission / accounts_notification 于 2c3d4e5f6a70 删除），
# 因此行数一致性校验只覆盖当前 schema 仍存在的表。
_DROPPED_TABLES = {"reports_template", "documents_permission", "accounts_notification"}
pytestmark = pytest.mark.skipif(not _ARCHIVES, reason="examples/backups 下无历史备份归档")


@pytest.fixture(params=_ARCHIVES, ids=[p.name for p in _ARCHIVES])
def legacy_archive(request: pytest.FixtureRequest) -> Path:
    """参数化逐个历史备份归档."""
    return request.param


def _read_manifest(archive: Path) -> dict[str, Any]:
    """读取归档内的 manifest.json."""
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.extractfile("backup/manifest.json")
        assert member is not None, f"归档缺少 manifest.json: {archive.name}"
        return json.loads(member.read().decode("utf-8"))


def _extract_backup_dir(archive: Path, dest: Path) -> Path:
    """解压归档并返回内部的 backup 目录（源数据仅供比对，不参与恢复）."""
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(dest, filter="data")
    return dest / "backup"


# 业务身份列：迁移不改写这些值，恢复后应与源库完全一致
_IDENTITY_COLUMNS = {
    "accounts_user": "username",
    "tables_datatable": "name",
    "workspaces_workspace": "name",
}


def _read_db_identity(db_path: Path) -> dict[str, set[Any]]:
    """读取关键业务表的身份列集合（用户名/数据表名/工作区名）."""
    conn = sqlite3.connect(str(db_path))
    try:
        return {
            table: {row[0] for row in conn.execute(f'SELECT "{column}" FROM "{table}"')}  # nosec B608 - 表/列名为内部常量
            for table, column in _IDENTITY_COLUMNS.items()
        }
    finally:
        conn.close()


_MANIFESTS = {path: _read_manifest(path) for path in _ARCHIVES}
_FALLBACK_ARCHIVES = [p for p in _ARCHIVES if _MANIFESTS[p]["database"].get("fallback_mode") == "sqlalchemy"]
_NON_FALLBACK_ARCHIVES = [p for p in _ARCHIVES if p not in _FALLBACK_ARCHIVES]


@pytest.fixture(params=_FALLBACK_ARCHIVES, ids=[p.name for p in _FALLBACK_ARCHIVES])
def fallback_archive(request: pytest.FixtureRequest) -> Path:
    """仅带内嵌兜底导出的历史备份."""
    return request.param


@pytest.fixture(params=_NON_FALLBACK_ARCHIVES, ids=[p.name for p in _NON_FALLBACK_ARCHIVES])
def no_fallback_archive(request: pytest.FixtureRequest) -> Path:
    """无内嵌兜底导出的历史备份（0.1.x 时代）."""
    return request.param


def _alembic_head() -> str:
    """获取当前包内迁移链的 head revision."""
    import alembic.script

    from cndb.core.migrations import _build_config

    cfg = _build_config("sqlite:///:memory:")
    return str(alembic.script.ScriptDirectory.from_config(cfg).get_current_head())


def test_inspect_legacy_backup(legacy_archive: Path) -> None:
    """历史归档可被新版程序 inspect：协议版本、软件版本、数据行数均可解析."""
    inspection = inspect_backup(legacy_archive)
    manifest = inspection.manifest
    assert manifest["version"] == MANIFEST_VERSION
    assert manifest["app_version"], "manifest 应记录备份时的软件版本"
    row_counts = manifest["database"]["row_counts"]
    assert sum(row_counts.values()) > 0, "历史备份应包含业务数据"


def test_manifest_metadata_and_archive_layout(legacy_archive: Path) -> None:
    """manifest 与归档内容自洽，且备份 schema 不领先于当前程序.

    新增历史备份时若 manifest 字段缺失、表清单与行数不一致、兜底导出声明
    与归档实际内容不符，或备份由更高版本程序生成（revision 不在当前链上），
    都在这里暴露——而不是等到恢复中途失败。
    """
    manifest = _MANIFESTS[legacy_archive]
    db = manifest["database"]

    # 元信息基本契约
    created_at = dt.datetime.fromisoformat(manifest["created_at"])
    assert created_at.tzinfo is not None, "created_at 应带时区（历史用 UTC）"
    assert len(manifest["app_version"].split(".")) == 3, "app_version 应为语义化版本"
    assert db["db_type"] == "sqlite"
    assert db["backup_mode"] in {"native", "sqlalchemy"}

    # 表清单与行数统计必须同源同集合
    assert set(db["row_counts"]) == set(db["tables"]), "row_counts 与 tables 应一一对应"
    assert len(set(db["tables"])) == len(db["tables"]), "表清单不应重复"
    assert all(isinstance(count, int) and count >= 0 for count in db["row_counts"].values())

    # 附件统计与 included 标记不矛盾
    uploads = manifest["uploads"]
    if not uploads["included"]:
        assert uploads["file_count"] == 0
        assert uploads["total_size"] == 0

    # 归档布局：数据库文件必存在；兜底导出与 fallback_mode 声明必须一致
    with tarfile.open(legacy_archive, "r:gz") as tar:
        names = set(tar.getnames())
    assert "backup/manifest.json" in names
    data_dirs = {name.split("/")[1] for name in names if name.startswith("backup/") and name.count("/") >= 2}
    assert {"data", "database"} & data_dirs, "归档内应有 data/ 或 database/ 数据目录"
    assert any(name.endswith("/cndb.db") for name in names), "归档内应有数据库文件"
    has_dump = any(name.endswith("/dump.json") for name in names)
    assert has_dump == (db.get("fallback_mode") == "sqlalchemy"), "兜底导出声明与归档实际内容不符"

    # 历史归档必须能被当前程序 native 恢复：schema 不领先
    schema_version = db.get("schema_version", "")
    if schema_version:
        assert _schema_revision_known(schema_version), f"备份 schema {schema_version} 不在当前迁移链上（备份领先程序）"

    # summary 口径与 manifest 一致
    summary = inspect_backup(legacy_archive).summary
    assert ("内嵌兜底导出: 有" in summary) == bool(db.get("fallback_mode"))
    assert "备份 schema 新于当前程序" not in summary


def test_restore_legacy_backup_migrates_to_head(legacy_archive: Path, tmp_path: Path) -> None:
    """恢复历史备份：schema 自动迁移到当前 head，且各表行数与 manifest 一致.

    迁移中显式删除的表（见 ``_DROPPED_TABLES``）不参与行数比对；
    对带 schema_version 的备份还要求该表确已删除，避免"漏删"被静默放过。
    无 schema_version 的 0.1.x 备份走 stamp + create_all 兜底、不重放迁移，
    已删除的历史表可能以孤儿表形式残留（无代码引用，不影响使用）。
    """
    manifest = inspect_backup(legacy_archive).manifest
    row_counts = manifest["database"]["row_counts"]
    has_schema_version = bool(manifest["database"].get("schema_version"))

    target_db = tmp_path / "restored.db"
    restore_backup(
        legacy_archive,
        force=False,
        database_url=f"sqlite:///{target_db}",
        upload_dir=tmp_path / "uploads",
    )

    conn = sqlite3.connect(str(target_db))
    try:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert version == _alembic_head(), "恢复后 schema 应回到当前迁移链 head"
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, count in row_counts.items():
            if table in _DROPPED_TABLES:
                if has_schema_version:
                    assert table not in existing, f"表 {table} 应已被迁移删除"
                continue
            actual = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # nosec B608 - 表名来自 manifest 枚举
            assert actual == count, f"表 {table}: 恢复后 {actual} 行 != manifest 记录 {count} 行"
    finally:
        conn.close()


@pytest.mark.timeout(180)
def test_seed_after_restore_regenerates_demo_data(
    legacy_archive: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """升级后的库上立即执行完整 seed：演示数据重新生成并保存落库.

    seed() 通过 cndb.core.database 的模块级 engine/SessionLocal 取库，
    测试中 monkeypatch 指向恢复出的临时库；settings.DATABASE_URL 同步
    指向（stamp_head 无参调用走 settings）。

    超时放宽到 180s：这是「恢复历史备份 + 全量 seed」的集成路径，seed 侧要写入
    示例工作区的数据表与 CSV 行，本地 0.1.x 归档已逼近 30s，CI runner 上必然超时。
    """
    import cndb.core.database as database_mod
    from cndb.cli.seed import seed as seed_command
    from cndb.core.config import settings
    from cndb.plugins.accounts.models import User
    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.workspaces.models import Workspace

    target_db = tmp_path / "restored.db"
    restore_backup(
        legacy_archive,
        force=False,
        database_url=f"sqlite:///{target_db}",
        upload_dir=tmp_path / "uploads",
    )

    # 与生产 engine 同款连接参数（isolation_level=None 交由事务显式控制）
    seed_engine = create_engine(
        f"sqlite:///{target_db}",
        connect_args={"check_same_thread": False, "isolation_level": None},
    )
    seed_session_factory = sessionmaker(bind=seed_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(database_mod, "engine", seed_engine)
    monkeypatch.setattr(database_mod, "SessionLocal", seed_session_factory)
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{target_db}")

    try:
        seed_command(argparse.Namespace())

        # seed 数据已保存：演示账号、工作区、数据表均落在升级后的库中
        with seed_session_factory() as db:
            assert db.query(User).filter(User.username == "admin").one_or_none() is not None
            assert db.query(Workspace).count() > 0
            assert db.query(DataTable).count() > 0
    finally:
        seed_engine.dispose()


def test_restore_legacy_backup_schema_covers_orm_models(legacy_archive: Path, tmp_path: Path) -> None:
    """恢复后的库 schema 覆盖当前 ORM 模型全列，且自愈已幂等收敛.

    迁移链存在历史缺口（部分列只加在 ORM 上），恢复流程靠 create_all +
    heal_schema_drift 兜底；这里用 ORM 模型列构造 SELECT，任何缺列都会让
    查询报 no such column（用户看到的“数据表打不开”直接形态）。
    """
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import select

    from cndb.core.migrations import heal_schema_drift
    from cndb.core.plugin_registry import plugin_registry
    from cndb.models.base import Base

    plugin_registry.discover_and_load()

    target_db = tmp_path / "restored.db"
    restore_backup(
        legacy_archive,
        force=False,
        database_url=f"sqlite:///{target_db}",
        upload_dir=tmp_path / "uploads",
    )

    engine = create_engine(f"sqlite:///{target_db}")
    try:
        existing = set(sa_inspect(engine).get_table_names())
        missing_tables = {table.name for table in Base.metadata.sorted_tables} - existing
        assert not missing_tables, f"恢复后缺少 ORM 声明的表: {sorted(missing_tables)}"

        failures: list[str] = []
        with engine.connect() as conn:
            for table in Base.metadata.sorted_tables:
                try:
                    conn.execute(select(table).limit(1)).fetchall()
                except Exception as exc:
                    failures.append(f"{table.name}: {exc}")
        assert not failures, "恢复库列结构落后于 ORM 模型:\n" + "\n".join(failures)
    finally:
        engine.dispose()

    # 恢复流程已完成 schema 自愈，再跑一次不应再有缺口（幂等收敛）
    assert heal_schema_drift(f"sqlite:///{target_db}") == []
    # 备份未包含附件 → 不应在目标创建 uploads 目录
    assert not (tmp_path / "uploads").exists()


def test_restore_legacy_backup_preserves_business_identity(legacy_archive: Path, tmp_path: Path) -> None:
    """业务身份数据零丢失：工作区名/用户名/数据表名集合与备份源库完全一致."""
    backup_dir = _extract_backup_dir(legacy_archive, tmp_path / "src")
    src_db = next(backup_dir.glob("*/cndb.db"))

    target_db = tmp_path / "restored.db"
    restore_backup(
        legacy_archive,
        force=False,
        database_url=f"sqlite:///{target_db}",
        upload_dir=tmp_path / "uploads",
    )

    assert _read_db_identity(src_db) == _read_db_identity(target_db)


def test_restore_legacy_backup_via_sqlalchemy_fallback(fallback_archive: Path, tmp_path: Path) -> None:
    """带兜底导出的备份可用 sqlalchemy 模式降级恢复，且裁剪报告与当前模型口径一致.

    交集导入只保留当前 ORM 声明的表/列：动态用户表、FTS 影子表与已删除历史表
    会整体跳过，新版本已移除的列会丢弃；报告必须精确反映裁剪面（不静默丢数据）。
    """
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text as sa_text

    from cndb.core.plugin_registry import plugin_registry
    from cndb.models.base import Base

    plugin_registry.discover_and_load()

    manifest = _MANIFESTS[fallback_archive]
    backup_dir = _extract_backup_dir(fallback_archive, tmp_path / "src")
    dump = json.loads(next(backup_dir.glob("*/dump.json")).read_text(encoding="utf-8"))
    dump_tables = {entry["table"]: entry for entry in dump["tables"]}

    target_db = tmp_path / "restored.db"
    report = restore_backup(
        fallback_archive,
        force=False,
        database_url=f"sqlite:///{target_db}",
        upload_dir=tmp_path / "uploads",
        mode="sqlalchemy",
    )
    assert report is not None, "sqlalchemy 模式应返回数据裁剪报告"

    # 跳过表 = dump 中当前 ORM 未声明的表；已删除的历史表必须被显式报告
    unknown_tables = set(dump_tables) - set(Base.metadata.tables)
    assert set(report.skipped_tables) == unknown_tables
    for dropped_table in _DROPPED_TABLES & set(dump_tables):
        assert dropped_table in report.skipped_tables

    # 丢弃列 = dump 列集合与当前 ORM 列集合的差集
    expected_dropped: dict[str, list[str]] = {}
    for name, entry in dump_tables.items():
        table = Base.metadata.tables.get(name)
        if table is None:
            continue
        dropped = sorted(set(entry["columns"]) - {column.name for column in table.columns})
        if dropped:
            expected_dropped[name] = dropped
    assert report.dropped_columns == expected_dropped

    engine = create_engine(f"sqlite:///{target_db}")
    try:
        existing = set(sa_inspect(engine).get_table_names())
        missing_tables = {table.name for table in Base.metadata.sorted_tables} - existing
        assert not missing_tables, f"降级恢复后缺少 ORM 声明的表: {sorted(missing_tables)}"
        with engine.connect() as conn:
            version = conn.execute(sa_text("SELECT version_num FROM alembic_version")).scalar()
            assert version == _alembic_head()
            for name, entry in dump_tables.items():
                if name not in Base.metadata.tables:
                    continue
                actual = conn.execute(sa_text(f'SELECT COUNT(*) FROM "{name}"')).scalar()  # nosec B608 - 表名来自 dump 枚举
                expected = manifest["database"]["row_counts"].get(name, len(entry["rows"]))
                assert actual == len(entry["rows"]) == expected, f"表 {name} 降级导入行数不符"
    finally:
        engine.dispose()

    # 系统业务数据完整：身份列集合与源库一致
    src_db = next(backup_dir.glob("*/cndb.db"))
    assert _read_db_identity(src_db) == _read_db_identity(target_db)


def test_restore_legacy_backup_without_fallback_rejects_sqlalchemy(no_fallback_archive: Path, tmp_path: Path) -> None:
    """无内嵌兜底导出的旧备份：sqlalchemy 模式应在落库前报错，不得静默建空库."""
    target_db = tmp_path / "restored.db"
    with pytest.raises(RestoreError, match=r"dump\.json"):
        restore_backup(
            no_fallback_archive,
            force=False,
            database_url=f"sqlite:///{target_db}",
            upload_dir=tmp_path / "uploads",
            mode="sqlalchemy",
        )
    assert not target_db.exists(), "缺少 dump.json 时不应创建目标数据库"
