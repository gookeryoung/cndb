"""seed 重建库对残留表/悬空外键的健壮性回归测试.

背景（线上 bug）：seed 的 drop_all 只删 ORM metadata 内的表，历史遗留表
（迁移建的 wechat_accounts、旧版本残留表、动态物理表 table_*/link_*）
不在 metadata 内而残留；在 PRAGMA foreign_keys=ON 下 DROP TABLE 触发
隐式 DELETE，级联到带"指向已删表外键"的残留表时 SQLite 报
"no such table: main.tables_datatable"（DROP TABLE accounts_user 时炸）。

本文件模拟用户库真实状态（含孤儿表 + 双外键残留表 + 业务数据行），
跑完整 seed()，断言重建不中断且残留表被清理。
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def legacy_db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """构造带残留表的"用户库"，并把 seed 的全局依赖指向它.

    库状态（复刻线上触发条件）：
    - 标准 metadata 表 + 业务数据行（users / workspace / table 有数据，
      使 DROP TABLE accounts_user 的隐式 DELETE 触发外键级联代码）
    - wechat_accounts 孤儿表：迁移 c7e8f9a0b1c2 建过、模型已下线，
      带 FK → accounts_user ON DELETE CASCADE 且有行
    - legacy_share 残留表：旧版本遗留，同时带
      FK → accounts_user（CASCADE，有行引用）与 FK → tables_datatable，
      是"级联 DELETE 解析悬空外键"的直接触发者
    - 连接行为与生产一致：register_sqlite_pragmas（foreign_keys=ON）
    """
    from cndb.core.database import register_sqlite_pragmas
    from cndb.models.base import Base

    db_path = tmp_path / "legacy.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "isolation_level": None},
    )
    register_sqlite_pragmas(engine)

    # 标准表 + 业务数据（ORM 写入，Python 端默认值自动生效）
    Base.metadata.create_all(engine)
    from cndb.plugins.accounts.models import User
    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember

    with sessionmaker(bind=engine)() as session:
        old_admin = User(username="old_admin", email="a@b.c", nickname="旧管理员")
        old_admin.set_password("x-old-admin")
        session.add(old_admin)
        session.flush()
        ws = Workspace(name="旧工作区", description="", created_by_id=old_admin.id)
        session.add(ws)
        session.flush()
        session.add(WorkspaceMember(workspace_id=ws.id, user_id=old_admin.id, role="owner"))
        tbl = DataTable(workspace_id=ws.id, owner_id=old_admin.id, name="旧表", description="", order=0)
        tbl.ensure_db_name()
        session.add(tbl)
        session.commit()

    # 孤儿表 wechat_accounts（迁移建过、模型已删除）
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE wechat_accounts (id INTEGER PRIMARY KEY, openid TEXT NOT NULL, "
                "user_id INTEGER NOT NULL REFERENCES accounts_user(id) ON DELETE CASCADE)"
            )
        )
        conn.execute(text("INSERT INTO wechat_accounts VALUES (1, 'openid-x', 1)"))

    # 旧版本残留表：同时引用 accounts_user（CASCADE）与 tables_datatable
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE legacy_share (id INTEGER PRIMARY KEY, "
                "user_id INTEGER NOT NULL REFERENCES accounts_user(id) ON DELETE CASCADE, "
                "table_id INTEGER NOT NULL REFERENCES tables_datatable(id) ON DELETE CASCADE)"
            )
        )
        conn.execute(text("INSERT INTO legacy_share VALUES (1, 1, 1)"))

    # 最小 datasets 目录：1 个工作区 + 1 个 CSV，避免全量数据集与外部 API
    datasets_dir = tmp_path / "datasets"
    ws_dir = datasets_dir / "工作区-演示"
    ws_dir.mkdir(parents=True)
    (ws_dir / "城市清单.csv").write_text("城市,人口\n北京,2189\n上海,2487\n", encoding="utf-8")

    # seed() 函数内 from cndb.core.database import SessionLocal, engine —— patch 模块属性
    import cndb.core.database as db_module
    from cndb.core.config import settings

    test_session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", test_session)
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr("cndb.cli.seed._get_datasets_dir", lambda: datasets_dir)

    yield db_path
    engine.dispose()


def _table_names(db_path: Path) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        return {name for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


class TestSeedRebuildOrphanTables:
    """seed 重建库必须扛住残留表与悬空外键，并顺带清理它们."""

    def test_seed_survives_and_cleans_orphan_fk_tables(self, legacy_db_env: Path):
        """带 wechat_accounts/legacy_share 残留表的库上跑 seed：不炸、残留表被清、演示数据就绪."""
        from cndb.cli.seed import seed

        # 修复前：drop_all 在 DROP TABLE accounts_user 处抛
        # OperationalError: no such table: main.tables_datatable
        seed(argparse.Namespace())

        tables = _table_names(legacy_db_env)
        # 残留表已被清理（seed 语义是清空重建演示库）
        assert "wechat_accounts" not in tables
        assert "legacy_share" not in tables
        # 标准表重建
        assert "accounts_user" in tables
        assert "tables_datatable" in tables
        assert "alembic_version" in tables

        con = sqlite3.connect(legacy_db_env)
        try:
            usernames = {row[0] for row in con.execute("SELECT username FROM accounts_user")}
            assert "admin" in usernames
        finally:
            con.close()
