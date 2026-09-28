"""迁移 schema 自愈回归测试.

复现线上问题：旧库 reports_template 由 create_all 兜底建表（当时模型 schema
尚无 extra_table_ids/theme/workspace_id），alembic_version 被 stamp 到当时的
head（d8e9f0a1b2c3），版本标记越过了加列迁移（b3c4d5e6f7a8/d4e5f6a7b8c9/
e5f6a7b8c9d0）。新版启动 upgrade head 对已越过区间的迁移永不重放，创建模板时
INSERT 报 "table reports_template has no column named extra_table_ids"。

修复契约（core/migrations.py）：ensure_db_migrated 任一路径（fresh / upgrade
成功 / 兜底）结束后执行 schema 自愈，对照 ORM 元数据纯增量补建缺列与缺索引。
"""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

# 注册全部插件模型，保证 Base.metadata 与生产一致（自愈遍历的比对基准）
import cndb.plugins.accounts.models
import cndb.plugins.reports.models
import cndb.plugins.tables.models
import cndb.plugins.wechat_auth.models
import cndb.plugins.workspaces.models  # noqa: F401
from cndb.core import database as db_mod
from cndb.core import migrations as mig_mod
from cndb.core.config import settings
from cndb.models.base import Base
from cndb.plugins.reports.models import ReportTemplate

HEAD = "e5f6a7b8c9d0"


# 旧 schema 的 reports_template 列工厂（截至 d8e9f0a1b2c3 时代的模型，仅基础列）；
# 每次调用构造新 Column 实例，避免跨测试复用同一对象绑定到不同 Table
def _legacy_cols(include_name: bool = True) -> list[sa.Column]:
    cols = [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("output_format", sa.String(16), nullable=False, server_default="docx"),
        sa.Column("template_content", sa.Text(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("table_id", sa.Integer(), nullable=True),
    ]
    return [c for c in cols if include_name or c.name != "name"]


def _create_legacy_template_table(engine, *, include_name: bool = True) -> None:
    """按旧 schema 建 reports_template（include_name=False 模拟缺不可补列）."""
    metadata = sa.MetaData()
    sa.Table("reports_template", metadata, *_legacy_cols(include_name))
    metadata.create_all(engine)


def _stamp_version(engine, revision: str) -> None:
    """手工写入 alembic_version（模拟历史流程盖的版本戳）."""
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("DELETE FROM alembic_version"))
        conn.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": revision})


def _make_legacy_db(tmp_path, monkeypatch, *, revision: str = HEAD, include_name: bool = True):
    """构造带存量数据的旧 schema 库，并把 ensure_db_migrated 全链路指向它.

    patch 三件套：
    - settings.DATABASE_URL → tmp 库（upgrade 的 env.py 取 cfg 注入值）
    - cndb.core.database.engine → tmp engine（fresh 探测/兜底 create_all/自愈）
    - mig_mod._db_is_fresh → False（tmp 库有业务表，非全新）
    """
    url = f"sqlite:///{(tmp_path / 'heal.db').as_posix()}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    engine = create_engine(url)
    _create_legacy_template_table(engine, include_name=include_name)
    with engine.begin() as conn:
        if include_name:
            conn.execute(
                text("INSERT INTO reports_template (name, template_content, parameters) VALUES ('旧模板', 'tpl', '[]')")
            )
        else:
            # 缺 name 列（不可安全补建的 NOT NULL 列）时仅插非空列
            conn.execute(text("INSERT INTO reports_template (template_content, parameters) VALUES ('tpl', '[]')"))
    _stamp_version(engine, revision)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(mig_mod, "_db_is_fresh", lambda: False)
    return engine


def _template_cols(engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("reports_template")}


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    """版本已 stamp 到 head 但表缺三列的库（线上故障形态）."""
    engine = _make_legacy_db(tmp_path, monkeypatch)
    yield engine
    engine.dispose()


class TestSchemaHeal:
    def test_heals_missing_columns_and_indexes(self, legacy_db):
        """版本越过加列迁移 → 自愈补齐 extra_table_ids/theme/workspace_id 与索引."""
        assert "extra_table_ids" not in _template_cols(legacy_db)

        mig_mod.ensure_db_migrated()

        cols = _template_cols(legacy_db)
        assert {"extra_table_ids", "theme", "workspace_id"} <= cols
        idx_names = {i["name"] for i in inspect(legacy_db).get_indexes("reports_template")}
        assert "ix_reports_template_workspace_id" in idx_names

        # 存量数据保留，新列取迁移约定的默认值
        with legacy_db.connect() as conn:
            row = conn.execute(
                text("SELECT name, extra_table_ids, theme, workspace_id FROM reports_template")
            ).fetchone()
        assert row[0] == "旧模板"
        assert json.loads(row[1]) == []
        assert row[2] == "minimal"
        assert row[3] is None

    def test_create_template_after_heal(self, legacy_db):
        """自愈后通过 ORM 创建模板成功（复现用户报错操作不再触发 no column）."""
        mig_mod.ensure_db_migrated()

        with Session(legacy_db) as session:
            tpl = ReportTemplate(name="T1", template_content="hello", parameters=[])
            session.add(tpl)
            session.commit()
            assert tpl.id is not None
            assert tpl.extra_table_ids == []
            assert tpl.theme == "minimal"

    def test_heal_is_idempotent(self, legacy_db):
        """自愈幂等：重复启动不重复补建、不改数据."""
        mig_mod.ensure_db_migrated()
        cols_before = _template_cols(legacy_db)
        with legacy_db.connect() as conn:
            rows_before = conn.execute(
                text("SELECT id, name, extra_table_ids, theme, workspace_id FROM reports_template")
            ).fetchall()

        mig_mod.ensure_db_migrated()

        assert _template_cols(legacy_db) == cols_before
        with legacy_db.connect() as conn:
            rows_after = conn.execute(
                text("SELECT id, name, extra_table_ids, theme, workspace_id FROM reports_template")
            ).fetchall()
        assert rows_before == rows_after

    def test_heal_after_upgrade_failure_fallback(self, tmp_path, monkeypatch):
        """upgrade 失败走兜底 create_all + stamp 后，自愈仍补齐已存在表的缺列.

        create_all 只建缺失的表、不修已存在的表 —— 兜底路径历史上正是靠
        stamp 掩盖了 reports_template 的缺列，自愈层必须兜住这条路。
        """
        engine = _make_legacy_db(tmp_path, monkeypatch)
        monkeypatch.setattr(
            mig_mod,
            "_run_upgrade",
            lambda cfg: (_ for _ in ()).throw(Exception("模拟 upgrade 中断")),
        )
        try:
            mig_mod.ensure_db_migrated()

            cols = _template_cols(engine)
            assert {"extra_table_ids", "theme", "workspace_id"} <= cols
        finally:
            engine.dispose()

    def test_normal_upgrade_path_not_duplicated_by_heal(self, tmp_path, monkeypatch):
        """版本落后的库走正常 upgrade 补列后，自愈不重复补建、版本到 head."""
        engine = _make_legacy_db(tmp_path, monkeypatch, revision="a2b3c4d5e6f7")
        try:
            mig_mod.ensure_db_migrated()

            cols = _template_cols(engine)
            assert {"extra_table_ids", "theme", "workspace_id"} <= cols
            idx_names = {i["name"] for i in inspect(engine).get_indexes("reports_template")}
            assert "ix_reports_template_workspace_id" in idx_names

            from alembic.script import ScriptDirectory

            head = ScriptDirectory(str(mig_mod._alembic_dir())).get_current_head()
            with engine.connect() as conn:
                version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert version == head
        finally:
            engine.dispose()

    def test_unsafe_not_null_column_skipped(self, tmp_path, monkeypatch):
        """NOT NULL 且无 server_default 的缺失列跳过不崩，其余列照常补齐."""
        engine = _make_legacy_db(tmp_path, monkeypatch, include_name=False)
        try:
            mig_mod.ensure_db_migrated()  # 不抛异常

            cols = _template_cols(engine)
            assert "name" not in cols  # 无法安全补建，跳过
            assert "extra_table_ids" in cols  # 其余列照常补齐
        finally:
            engine.dispose()

    def test_heal_covers_all_metadata_tables(self, legacy_db):
        """自愈以 Base.metadata 全表为基准（非仅 reports_template）.

        先 create_all 补齐其余业务表（reports_template 保持旧 schema），
        再摘掉 accounts_user 的 created_at（TimestampMixin 列，无 FK 且带
        server_default），验证同样被补回。
        """
        Base.metadata.create_all(legacy_db)
        with legacy_db.begin() as conn:
            conn.execute(text("ALTER TABLE accounts_user DROP COLUMN created_at"))

        mig_mod.ensure_db_migrated()

        cols = {c["name"] for c in inspect(legacy_db).get_columns("accounts_user")}
        assert "created_at" in cols
