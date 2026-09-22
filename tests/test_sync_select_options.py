"""sync_select_options_from_table 单元测试.

覆盖场景：
1. 空 options → 全量补全（select / multiselect）
2. 部分 options → 追加新值，保留已有
3. 重复导入同一值 → 不重复添加
4. multiselect split 逗号 → 多个独立值
5. 表无 select/multiselect 字段 → 直接返回空
6. 字段 config 有其他属性（decimals 等）→ 不破坏
7. 纯 engine 导入（db=None）→ options 不补全
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.fields.field_ops import sync_select_options_from_table
from cndb.plugins.tables.models import Base, DataField, DataTable
from cndb.plugins.tables.transfer import import_rows_from_csv, import_rows_from_json


@pytest.fixture
def test_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sync.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield engine, session
    finally:
        session.close()


def _make_table(session: Session, engine) -> DataTable:
    dt = DataTable(workspace_id=1, name="测试表")
    dt.ensure_db_name()
    session.add(dt)
    session.commit()
    session.refresh(dt)
    return dt


def _add_field(
    session: Session,
    table: DataTable,
    name: str,
    field_type: str,
    *,
    config: dict | None = None,
    order: int = 0,
) -> DataField:
    f = DataField(
        table_id=table.id,
        name=name,
        field_type=field_type,
        config=config or {},
        order=order,
    )
    f.ensure_db_name()
    session.add(f)
    session.flush()
    return f


# ── sync_select_options_from_table 核心逻辑 ────────


class TestSyncSelectOptions:
    """直接调用 sync_select_options_from_table."""

    def test_empty_options_gets_filled(self, test_session):
        """select 字段 options 为空 → 从数据行自动补全."""
        engine, session = test_session
        table = _make_table(session, engine)
        f_select = _add_field(session, table, "status", "select", config={"options": []}, order=0)
        _add_field(session, table, "name", "text", order=1)
        session.commit()
        ddl.create_table(engine, table)

        # 插入行数据
        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"name": "Alice", "status": "active"},
                    {"name": "Bob", "status": "pending"},
                    {"name": "Carol", "status": "active"},
                ]
            ),
            db=session,
        )

        session.refresh(f_select)
        assert f_select.config["options"] is not None
        labels = [o["label"] for o in f_select.config["options"]]
        assert set(labels) == {"active", "pending"}
        # 应有 color
        assert all("color" in o for o in f_select.config["options"])

    def test_preserves_existing_options_appends_new(self, test_session):
        """已有部分 options → 保留已有顺序和 color，新值追加."""
        engine, session = test_session
        table = _make_table(session, engine)
        f_select = _add_field(
            session,
            table,
            "status",
            "select",
            config={
                "options": [
                    {"label": "active", "value": "active", "color": "green"},
                ]
            },
            order=0,
        )
        _add_field(session, table, "name", "text", order=1)
        session.commit()
        ddl.create_table(engine, table)

        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"name": "Alice", "status": "active"},
                    {"name": "Bob", "status": "archived"},
                ]
            ),
            db=session,
        )

        session.refresh(f_select)
        options = f_select.config["options"]
        assert len(options) == 2
        # 已有项保持不变
        assert options[0]["label"] == "active"
        assert options[0]["color"] == "green"
        # 新值追加
        assert options[1]["label"] == "archived"

    def test_no_duplicate_on_repeat_sync(self, test_session):
        """重复导入相同值 → options 不重复."""
        engine, session = test_session
        table = _make_table(session, engine)
        f_select = _add_field(session, table, "city", "select", config={"options": []}, order=0)
        session.commit()
        ddl.create_table(engine, table)

        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"city": "Beijing"},
                    {"city": "Shanghai"},
                    {"city": "Beijing"},
                ]
            ),
            db=session,
        )
        session.refresh(f_select)
        first_count = len(f_select.config["options"])

        # 再导入一轮重复的
        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"city": "Beijing"},
                    {"city": "Guangzhou"},
                ]
            ),
            db=session,
        )
        session.refresh(f_select)
        second_labels = [o["label"] for o in f_select.config["options"]]
        assert len(second_labels) == first_count + 1  # 只追加 Guangzhou
        assert second_labels.count("Beijing") == 1

    def test_multiselect_split_csv(self, test_session):
        """multiselect 字段 list 值 → 拆成独立选项（JSON 导入格式）."""
        engine, session = test_session
        table = _make_table(session, engine)
        f_ms = _add_field(session, table, "tags", "multiselect", config={"options": []}, order=0)
        session.commit()
        ddl.create_table(engine, table)

        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"tags": ["urgent", "backend"]},
                    {"tags": ["backend", "devops"]},
                    {"tags": None},  # 空值跳过
                ]
            ),
            db=session,
        )

        session.refresh(f_ms)
        labels = [o["label"] for o in f_ms.config["options"]]
        assert set(labels) == {"urgent", "backend", "devops"}

    def test_no_select_fields_returns_empty(self, test_session):
        """表没有 select/multiselect 字段 → 返回 []，不报错."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "name", "text", order=0)
        _add_field(session, table, "age", "number", order=1)
        session.commit()
        ddl.create_table(engine, table)

        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"name": "Alice", "age": 25},
                ]
            ),
            db=session,
        )

        changed = sync_select_options_from_table(session, table)
        assert changed == []

    def test_skips_empty_and_none_values(self, test_session):
        """None 值不进入 options（空字符串在 JSON 导入中需上游归一化）."""
        engine, session = test_session
        table = _make_table(session, engine)
        f_select = _add_field(session, table, "status", "select", config={"options": []}, order=0)
        session.commit()
        ddl.create_table(engine, table)

        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"status": "ok"},
                    {"status": None},
                ]
            ),
            db=session,
        )

        session.refresh(f_select)
        labels = [o["label"] for o in f_select.config["options"]]
        assert labels == ["ok"]

    def test_preserves_other_config_keys(self, test_session):
        """select 字段 config 有 auto_fill_colors 等其他 key → 同步后不丢失."""
        engine, session = test_session
        table = _make_table(session, engine)
        f_select = _add_field(
            session,
            table,
            "status",
            "select",
            config={
                "options": [],
                "auto_fill_colors": True,
                "placeholder": "选择状态",
            },
            order=0,
        )
        session.commit()
        ddl.create_table(engine, table)

        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"status": "running"},
                ]
            ),
            db=session,
        )

        session.refresh(f_select)
        cfg = f_select.config
        assert cfg.get("auto_fill_colors") is True
        assert cfg.get("placeholder") == "选择状态"
        assert "options" in cfg

    def test_multiselect_empty_values_split(self, test_session):
        """multiselect list 值 → 直接作为独立选项收集."""
        engine, session = test_session
        table = _make_table(session, engine)
        f_ms = _add_field(session, table, "skills", "multiselect", config={"options": []}, order=0)
        session.commit()
        ddl.create_table(engine, table)

        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"skills": ["Python", "Java", "Go"]},
                ]
            ),
            db=session,
        )

        session.refresh(f_ms)
        labels = [o["label"] for o in f_ms.config["options"]]
        assert set(labels) == {"Python", "Java", "Go"}


# ── 通过 transfer 导入入口自动触发 ───────────────


class TestTransferImportTriggersSync:
    """transfer.import_rows_from_json/csv/xlsx + db=db → 自动补全 options."""

    def test_json_import_fills_select_options(self, test_session):
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "role", "select", config={"options": []}, order=0)
        _add_field(session, table, "user", "text", order=1)
        session.commit()
        ddl.create_table(engine, table)

        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"user": "alice", "role": "admin"},
                    {"user": "bob", "role": "editor"},
                ]
            ),
            db=session,
        )

        session.refresh(table.active_fields()[0])
        f_role = next(f for f in table.active_fields() if f.name == "role")
        labels = [o["label"] for o in f_role.config["options"]]
        assert set(labels) == {"admin", "editor"}

    def test_csv_import_fills_select_options(self, test_session):
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "dept", "select", config={"options": []}, order=0)
        _add_field(session, table, "emp", "text", order=1)
        session.commit()
        ddl.create_table(engine, table)

        csv_text = "emp,dept\nAlice,Engineering\nBob,Sales\nCarol,Engineering\n"
        import_rows_from_csv(engine, table, csv_text, db=session)

        f_dept = next(f for f in table.active_fields() if f.name == "dept")
        labels = [o["label"] for o in f_dept.config["options"]]
        assert set(labels) == {"Engineering", "Sales"}

    def test_import_without_db_param_skips_sync(self, test_session):
        """不传 db（纯 engine）→ 不触发 options 补全，不报错."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "role", "select", config={"options": []}, order=0)
        _add_field(session, table, "user", "text", order=1)
        session.commit()
        ddl.create_table(engine, table)

        # 不传 db
        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"user": "alice", "role": "admin"},
                ]
            ),
        )

        # 刷新元数据（session 里 field.config 是 commit 时的快照）
        session.refresh(table.active_fields()[0])
        f_role = next(f for f in table.active_fields() if f.name == "role")
        # options 应该还是空的，因为没传 db
        assert f_role.config.get("options") == []

    def test_import_to_table_with_existing_options_preserves_order(self, test_session):
        """已有 options 带自定义 color → 保持不变，新值追加."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(
            session,
            table,
            "status",
            "select",
            config={
                "options": [
                    {"label": "done", "value": "done", "color": "blue"},
                    {"label": "todo", "value": "todo", "color": "gold"},
                ]
            },
            order=0,
        )
        session.commit()
        ddl.create_table(engine, table)

        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"status": "done"},
                    {"status": "in_progress"},
                    {"status": "done"},
                ]
            ),
            db=session,
        )

        f_status = table.active_fields()[0]
        options = f_status.config["options"]
        assert len(options) == 3
        assert options[0]["label"] == "done"
        assert options[0]["color"] == "blue"
        assert options[1]["label"] == "todo"
        assert options[1]["color"] == "gold"
        assert options[2]["label"] == "in_progress"
