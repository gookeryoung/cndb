"""历史版本数据库直接使用场景测试.

覆盖"不经 restore、直接把旧版本 schema 的 .db 文件交给新版程序"的场景：

1. 版本比较：旧库 alembic_version 与当前迁移链 head 的关系判定
   （在链上 / 领先于程序 / 旧于 head），以及升级后版本收敛到 head；
2. 正常查询：升级 + 自愈后 ORM / 原生 SQL 全列 SELECT 可用；
3. 数据过滤：升级后的库上 WHERE / ORDER BY / LIMIT / ORM filter 正常命中；
4. 自愈回归：迁移链历史缺口列（如 manage_data_role）在直接使用路径下
   也会被补齐（与 restore 路径同源的 heal_schema_drift）。

每个用例按 前置条件 → 执行步骤 → 预期结果 组织，均使用 tmp_path 隔离，
可重复、相互独立。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from cndb.core.migrations import _build_config, heal_schema_drift, upgrade_to_head

# 迁移链关键 revision：initial → ... → e5f6a7b8c9d0(0.2.0 时代 head) → f7a8b9c0d1e2(当前 head)
REVISION_INITIAL = "6399e5f0f61f"
REVISION_020 = "e5f6a7b8c9d0"


def _alembic_head() -> str:
    """获取当前包内迁移链的 head revision."""
    import alembic.script

    cfg = _build_config("sqlite:///:memory:")
    return str(alembic.script.ScriptDirectory.from_config(cfg).get_current_head())


def _make_legacy_db(db_path: Path, revision: str, workspace_count: int = 3) -> Path:
    """前置：构造指定 revision 的历史 schema 库并注入演示数据.

    通过真实 alembic 迁移链建表（保证与历史版本程序产物一致），
    再用原生 SQL 插入 workspaces_workspace 行。
    """
    import alembic.command

    cfg = _build_config(f"sqlite:///{db_path.as_posix()}")
    alembic.command.upgrade(cfg, revision)

    conn = sqlite3.connect(str(db_path))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(workspaces_workspace)")}
        for i in range(workspace_count):
            # 按历史版本实际存在的列动态构造 INSERT（initial 无 visibility/tags 等列）
            values: dict[str, object] = {"name": f"历史工作区{i}", "description": f"描述{i}"}
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
    return db_path


def _read_alembic_version(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        return str(conn.execute("SELECT version_num FROM alembic_version").fetchone()[0])
    finally:
        conn.close()


# ── 版本比较 ─────────────────────────────────────────


class TestVersionComparison:
    """历史库 / 备份 schema 版本与当前程序迁移链的比较判定."""

    def test_legacy_db_version_is_behind_head(self, tmp_path: Path) -> None:
        """前置：0.2.0 schema 库；步骤：读取 alembic_version 并比较；预期：在链上但旧于 head."""
        from cndb.cli.restore import _schema_revision_known

        db = _make_legacy_db(tmp_path / "legacy.db", REVISION_020)
        version = _read_alembic_version(db)
        assert version == REVISION_020
        assert version != _alembic_head()
        # 0.2.0 revision 在当前链上 → 不属于"备份 schema 领先"情形
        assert _schema_revision_known(version) is True

    def test_unknown_revision_treated_as_ahead(self) -> None:
        """前置：无；步骤：比较未知 revision 与链；预期：判定不在链上（领先于当前程序）."""
        from cndb.cli.restore import _schema_revision_known

        assert _schema_revision_known("deadbeef0000") is False
        assert _schema_revision_known("") is False
        assert _schema_revision_known(_alembic_head()) is True

    def test_direct_upgrade_converges_to_head(self, tmp_path: Path) -> None:
        """前置：0.2.0 库；步骤：upgrade_to_head；预期：版本收敛到当前 head."""
        db = _make_legacy_db(tmp_path / "legacy.db", REVISION_020)
        upgrade_to_head(f"sqlite:///{db.as_posix()}")
        assert _read_alembic_version(db) == _alembic_head()

    def test_initial_db_also_converges(self, tmp_path: Path) -> None:
        """前置：initial revision 库；步骤：upgrade_to_head；预期：收敛到 head（跨多版本升级）."""
        db = _make_legacy_db(tmp_path / "legacy.db", REVISION_INITIAL, workspace_count=1)
        upgrade_to_head(f"sqlite:///{db.as_posix()}")
        assert _read_alembic_version(db) == _alembic_head()


# ── 正常查询 ─────────────────────────────────────────


class TestNormalQueryOnLegacyDb:
    """直接使用历史库：升级 + 自愈前后查询可用性对比."""

    def test_unupgraded_legacy_db_full_column_select_fails(self, tmp_path: Path) -> None:
        """前置：未升级的 0.2.0 库（缺 manage_data_role）；步骤：全列 SELECT 含新列；
        预期：OperationalError no such column（直接使用旧库的真实故障形态）."""
        db = _make_legacy_db(tmp_path / "legacy.db", REVISION_020)
        engine = create_engine(f"sqlite:///{db.as_posix()}")
        try:
            with engine.connect() as conn, pytest.raises(OperationalError, match="manage_data_role"):
                conn.execute(text("SELECT table_id, manage_data_role FROM tables_tablepermission"))
        finally:
            engine.dispose()

    def test_upgrade_and_heal_enables_full_column_select(self, tmp_path: Path) -> None:
        """前置：0.2.0 库；步骤：upgrade_to_head + heal_schema_drift 后同查询；
        预期：全列 SELECT 成功（历史缺口列已补齐）."""
        db = _make_legacy_db(tmp_path / "legacy.db", REVISION_020)
        url = f"sqlite:///{db.as_posix()}"
        upgrade_to_head(url)
        heal_schema_drift(url)

        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                rows = conn.execute(text("SELECT manage_data_role FROM tables_tablepermission")).fetchall()
        finally:
            engine.dispose()
        assert rows == []  # 空表可查即证明缺列已补

    def test_orm_query_on_upgraded_legacy_db(self, tmp_path: Path) -> None:
        """前置：0.2.0 库注入 3 行 workspace；步骤：升级 + 自愈后用 ORM Session 查询；
        预期：实体正常加载、字段值与注入一致（新版程序可直接读写升级后的历史库）."""
        from cndb.plugins.workspaces.models import Workspace

        db = _make_legacy_db(tmp_path / "legacy.db", REVISION_020, workspace_count=3)
        url = f"sqlite:///{db.as_posix()}"
        upgrade_to_head(url)
        heal_schema_drift(url)

        engine = create_engine(url)
        try:
            session_factory = sessionmaker(bind=engine)
            with session_factory() as session:
                workspaces = session.query(Workspace).order_by(Workspace.id).all()
                assert [w.name for w in workspaces] == ["历史工作区0", "历史工作区1", "历史工作区2"]
                # 新版程序可继续写入（历史库升级后可用的关键保证）
                session.add(Workspace(name="新写入", description=""))
                session.commit()
                assert session.query(Workspace).count() == 4
        finally:
            engine.dispose()


# ── 数据过滤 ─────────────────────────────────────────


class TestFilteringOnLegacyDb:
    """升级后的历史库上执行数据过滤."""

    def test_sql_where_order_limit(self, tmp_path: Path) -> None:
        """前置：升级后的 0.2.0 库含 3 行数据；步骤：WHERE + ORDER BY + LIMIT 过滤；
        预期：命中行、排序与截断均正确."""
        db = _make_legacy_db(tmp_path / "legacy.db", REVISION_020, workspace_count=3)
        url = f"sqlite:///{db.as_posix()}"
        upgrade_to_head(url)
        heal_schema_drift(url)

        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT name FROM workspaces_workspace WHERE name LIKE :pat ORDER BY name DESC LIMIT 2"),
                    {"pat": "%历史工作区%"},
                ).fetchall()
        finally:
            engine.dispose()
        assert [r[0] for r in rows] == ["历史工作区2", "历史工作区1"]

    def test_orm_filter_on_upgraded_legacy_db(self, tmp_path: Path) -> None:
        """前置：升级后的 0.2.0 库；步骤：ORM filter/filter_by 条件查询；
        预期：精确匹配与不匹配两种结果均正确."""
        from cndb.plugins.workspaces.models import Workspace

        db = _make_legacy_db(tmp_path / "legacy.db", REVISION_020, workspace_count=3)
        url = f"sqlite:///{db.as_posix()}"
        upgrade_to_head(url)
        heal_schema_drift(url)

        engine = create_engine(url)
        try:
            session_factory = sessionmaker(bind=engine)
            with session_factory() as session:
                hit = session.query(Workspace).filter_by(name="历史工作区1").one_or_none()
                assert hit is not None and hit.description == "描述1"
                miss = session.query(Workspace).filter(Workspace.name == "不存在").all()
                assert miss == []
        finally:
            engine.dispose()


# ── 自愈幂等 / 可重复性 ──────────────────────────────


class TestHealIdempotency:
    """直接使用路径下 heal_schema_drift 的幂等性."""

    def test_heal_on_fresh_head_db_is_noop(self, tmp_path: Path) -> None:
        """前置：已 upgrade head 且自愈过的库；步骤：再次 heal；预期：无补建项、不报错（可重复）."""
        db = _make_legacy_db(tmp_path / "legacy.db", REVISION_020)
        url = f"sqlite:///{db.as_posix()}"
        upgrade_to_head(url)
        heal_schema_drift(url)
        second = heal_schema_drift(url)
        # 第一次允许有补建（缺索引等），第二次必须为空 —— 幂等
        assert second == []

    def test_heal_preserves_existing_data(self, tmp_path: Path) -> None:
        """前置：0.2.0 库含数据；步骤：heal；预期：既有行数与内容不受自愈影响."""
        db = _make_legacy_db(tmp_path / "legacy.db", REVISION_020, workspace_count=2)
        url = f"sqlite:///{db.as_posix()}"
        upgrade_to_head(url)
        heal_schema_drift(url)

        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                names = [
                    r[0] for r in conn.execute(text("SELECT name FROM workspaces_workspace ORDER BY id")).fetchall()
                ]
        finally:
            engine.dispose()
        assert names == ["历史工作区0", "历史工作区1"]
