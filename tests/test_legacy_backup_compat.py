"""examples 历史版本备份向前兼容回归测试.

针对 examples/backups/ 下随仓库保存的历史版本备份归档（文件名
``backup-<软件版本>-v<数据库格式版本>-<时间戳>.tar.gz``），逐个验证新版程序：

1. inspect_backup 读取 manifest 元信息（协议版本、软件版本可解析）；
2. restore_backup 恢复并把 schema 自动迁移到当前 alembic head；
3. 恢复后的各表行数与 manifest 记录一致（旧数据零丢失）；
4. 在升级后的库上立即执行完整 seed 重新生成演示数据并保存落库
   （旧库升级后新程序可继续写入，seed 重新建表 + 注入全部演示数据）。

新增历史备份文件无需修改测试：参数化自动纳入下一个 ``backup-*.tar.gz``。
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.cli.backup import MANIFEST_VERSION
from cndb.cli.restore import inspect_backup, restore_backup

# 仓库根 examples/backups（本文件位于 tests/ 下，向上一级即仓库根）
BACKUP_DIR = Path(__file__).resolve().parents[1] / "examples" / "backups"

_ARCHIVES = sorted(BACKUP_DIR.glob("backup-*.tar.gz"))

pytestmark = pytest.mark.skipif(not _ARCHIVES, reason="examples/backups 下无历史备份归档")


@pytest.fixture(params=_ARCHIVES, ids=[p.name for p in _ARCHIVES])
def legacy_archive(request: pytest.FixtureRequest) -> Path:
    """参数化逐个历史备份归档."""
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


def test_restore_legacy_backup_migrates_to_head(legacy_archive: Path, tmp_path: Path) -> None:
    """恢复历史备份：schema 自动迁移到当前 head，且各表行数与 manifest 一致."""
    manifest = inspect_backup(legacy_archive).manifest
    row_counts = manifest["database"]["row_counts"]

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
        for table, count in row_counts.items():
            actual = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # nosec B608 - 表名来自 manifest 枚举
            assert actual == count, f"表 {table}: 恢复后 {actual} 行 != manifest 记录 {count} 行"
    finally:
        conn.close()


def test_seed_after_restore_regenerates_demo_data(
    legacy_archive: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """升级后的库上立即执行完整 seed：演示数据重新生成并保存落库.

    seed() 通过 cndb.core.database 的模块级 engine/SessionLocal 取库，
    测试中 monkeypatch 指向恢复出的临时库；settings.DATABASE_URL 同步
    指向（stamp_head 无参调用走 settings）。示例报告落盘属仓库目录副作用，
    与数据库兼容性无关，测试中跳过。
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
    # 示例报告落盘属仓库目录副作用，与本测试目标无关，跳过
    monkeypatch.setattr("cndb.cli.seed._generate_sample_reports", lambda *args, **kwargs: None)

    try:
        seed_command(argparse.Namespace())

        # seed 数据已保存：演示账号、工作区、数据表均落在升级后的库中
        with seed_session_factory() as db:
            assert db.query(User).filter(User.username == "admin").one_or_none() is not None
            assert db.query(Workspace).count() > 0
            assert db.query(DataTable).count() > 0
    finally:
        seed_engine.dispose()
