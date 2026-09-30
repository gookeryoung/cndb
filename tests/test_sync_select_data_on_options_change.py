"""选项变更 → 存量数据同步单元测试.

覆盖 diff_select_options 与 sync_select_data_on_options_change：

1. diff：就地改名（1:1 / 相邻等长替换段）、删除、新增、纯重排、重复值、不等长替换段
2. sync：select 改名整格改写 / 删除整格置 NULL / 未引用行不动
3. sync：multiselect 多值改名 / 删除摘除 / 拆空置 NULL / 改名删除组合
4. sync：无迁移动作（含纯重排）短路返回 0
5. sync：物理表缺失 / 物理列缺失 → 返回 0 且不报错
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import MetaData, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from cndb.plugins.tables.models import Base, DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.fields.field_ops import (
    diff_select_options,
    sync_select_data_on_options_change,
)


@pytest.fixture
def test_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sync_data.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield engine, session
    finally:
        session.close()


def _make_table(session: Session) -> DataTable:
    dt = DataTable(workspace_id=1, name="选项同步测试表")
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
    config: dict[str, Any] | None = None,
) -> DataField:
    f = DataField(table_id=table.id, name=name, field_type=field_type, config=config or {}, order=0)
    f.ensure_db_name()
    session.add(f)
    session.flush()
    return f


def _opts(*values: str) -> list[dict[str, str]]:
    """构造 [{label, value, color}] 选项列表（value == label，与前端一致）."""
    return [{"label": v, "value": v, "color": ""} for v in values]


def _reflect(engine, table: DataTable):
    meta = MetaData()
    meta.reflect(bind=engine, only=[table.db_table_name])
    return meta.tables[table.db_table_name]


# ── diff_select_options 纯逻辑 ───────────────────────


class TestDiffSelectOptions:
    def test_rename_in_place(self):
        """就地改名：1:1 replace 段配对为改名，无删除."""
        rename, removed = diff_select_options(_opts("A", "B", "C"), _opts("A", "B2", "C"))
        assert rename == {"B": "B2"}
        assert removed == []

    def test_rename_two_adjacent(self):
        """相邻两项同时改名：等长 replace 段按顺序一一配对."""
        rename, removed = diff_select_options(_opts("A", "B", "C"), _opts("A2", "B2", "C"))
        assert rename == {"A": "A2", "B": "B2"}
        assert removed == []

    def test_delete_only(self):
        """删除中间选项：无改名，进入 removed."""
        rename, removed = diff_select_options(_opts("A", "B", "C"), _opts("A", "C"))
        assert rename == {}
        assert removed == ["B"]

    def test_add_only(self):
        """纯新增：不产生任何迁移动作."""
        rename, removed = diff_select_options(_opts("A", "B"), _opts("A", "B", "D"))
        assert rename == {}
        assert removed == []

    def test_pure_reorder_noop(self):
        """纯重排：值集合不变 → 不改名也不删除."""
        rename, removed = diff_select_options(_opts("A", "B", "C"), _opts("C", "A", "B"))
        assert rename == {}
        assert removed == []

    def test_duplicate_values_noop(self):
        """重复值选项：值集合不变 → 不误判为删除/改名."""
        rename, removed = diff_select_options(_opts("A", "A", "B"), _opts("A", "B"))
        assert rename == {}
        assert removed == []

    def test_unequal_replace_block_pairs_in_order(self):
        """不等长替换段（2→1，如改名+删除相邻项）：按顺序配对 1 个改名，多余旧值落删除."""
        rename, removed = diff_select_options(_opts("A", "B"), _opts("X"))
        assert rename == {"A": "X"}
        assert removed == ["B"]

    def test_mixed_forms_by_value(self):
        """旧纯字符串形态 vs 新 dict 形态：按 value 语义对比."""
        rename, removed = diff_select_options(["A", "B"], [{"label": "A2", "value": "A2"}])
        assert rename == {"A": "A2"}
        assert removed == ["B"]

    def test_identical_options_noop(self):
        """新旧完全一致 → 直接短路."""
        old = _opts("A", "B")
        assert diff_select_options(old, old) == ({}, [])


# ── sync_select_data_on_options_change（select） ─────


class TestSyncSelectDataSelect:
    def test_rename_rewrites_rows(self, test_session):
        """select 改名：引用旧值的行整格改写为新值，其余行不动."""
        engine, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "dept", "select", config={"options": _opts("技术部", "市场部")})
        session.commit()
        ddl.create_table(engine, table)

        sa = _reflect(engine, table)
        session.execute(sa.insert(), [{f.db_column_name: v} for v in ["技术部", "市场部", "技术部"]])
        session.commit()

        old_config = dict(f.config or {})
        f.config = {"options": _opts("研发部", "市场部")}
        affected = sync_select_data_on_options_change(session, table, f, old_config)
        session.commit()

        assert affected == 2
        values = session.execute(select(sa.c[f.db_column_name])).scalars().all()
        assert values == ["研发部", "市场部", "研发部"]

    def test_delete_clears_rows_to_null(self, test_session):
        """select 删除选项：引用被删值的行整格置 NULL."""
        engine, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "dept", "select", config={"options": _opts("技术部", "市场部")})
        session.commit()
        ddl.create_table(engine, table)

        sa = _reflect(engine, table)
        session.execute(sa.insert(), [{f.db_column_name: v} for v in ["技术部", "市场部"]])
        session.commit()

        old_config = dict(f.config or {})
        f.config = {"options": _opts("技术部")}
        affected = sync_select_data_on_options_change(session, table, f, old_config)
        session.commit()

        assert affected == 1
        values = session.execute(select(sa.c[f.db_column_name])).scalars().all()
        assert values == ["技术部", None]

    def test_noop_when_options_unchanged(self, test_session):
        """无迁移动作（纯重排/仅颜色）→ 返回 0，数据不动."""
        engine, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "dept", "select", config={"options": _opts("A", "B")})
        session.commit()
        ddl.create_table(engine, table)

        sa = _reflect(engine, table)
        session.execute(sa.insert(), [{f.db_column_name: "A"}])
        session.commit()

        old_config = dict(f.config or {})
        # 仅重排 + 改颜色
        f.config = {
            "options": [
                {"label": "B", "value": "B", "color": "red"},
                {"label": "A", "value": "A", "color": "blue"},
            ]
        }
        affected = sync_select_data_on_options_change(session, table, f, old_config)
        session.commit()

        assert affected == 0
        values = session.execute(select(sa.c[f.db_column_name])).scalars().all()
        assert values == ["A"]

    def test_missing_physical_table_returns_zero(self, test_session):
        """物理表不存在（DDL 未执行）→ 返回 0 且不报错."""
        _, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "dept", "select", config={"options": _opts("A")})
        session.commit()

        old_config = dict(f.config or {})
        f.config = {"options": _opts("B")}
        assert sync_select_data_on_options_change(session, table, f, old_config) == 0

    def test_missing_physical_column_returns_zero(self, test_session):
        """物理列缺失（metadata 有字段但物理表未加列）→ 返回 0 且不报错."""
        engine, session = test_session
        table = _make_table(session)
        session.commit()
        ddl.create_table(engine, table)

        # 物理建表后才加字段（未调用 add_column）→ 物理表缺列
        f = _add_field(session, table, "dept", "select", config={"options": _opts("A")})
        session.commit()

        old_config = dict(f.config or {})
        f.config = {"options": _opts("B")}
        assert sync_select_data_on_options_change(session, table, f, old_config) == 0


# ── sync_select_data_on_options_change（multiselect） ─


class TestSyncSelectDataMultiSelect:
    def test_rename_inside_joined_string(self, test_session):
        """multiselect 改名：逗号串中的旧值改写，其余项不动."""
        engine, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "tags", "multiselect", config={"options": _opts("red", "blue")})
        session.commit()
        ddl.create_table(engine, table)

        sa = _reflect(engine, table)
        session.execute(
            sa.insert(),
            [{f.db_column_name: "red,blue"}, {f.db_column_name: "blue"}, {f.db_column_name: "red"}],
        )
        session.commit()

        old_config = dict(f.config or {})
        f.config = {"options": _opts("crimson", "blue")}
        affected = sync_select_data_on_options_change(session, table, f, old_config)
        session.commit()

        assert affected == 2
        values = session.execute(select(sa.c[f.db_column_name])).scalars().all()
        assert values == ["crimson,blue", "blue", "crimson"]

    def test_delete_removes_item_and_empties_cell(self, test_session):
        """multiselect 删除选项：从多值串中摘除；全部被摘空的行置 NULL."""
        engine, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "tags", "multiselect", config={"options": _opts("a", "b", "c")})
        session.commit()
        ddl.create_table(engine, table)

        sa = _reflect(engine, table)
        session.execute(
            sa.insert(),
            [{f.db_column_name: v} for v in ["a,b", "b,c", "c", "a"]],
        )
        session.commit()

        old_config = dict(f.config or {})
        f.config = {"options": _opts("c")}
        affected = sync_select_data_on_options_change(session, table, f, old_config)
        session.commit()

        assert affected == 3
        values = session.execute(select(sa.c[f.db_column_name])).scalars().all()
        assert values == [None, "c", "c", None]

    def test_rename_and_delete_combined(self, test_session):
        """multiselect 改名 + 删除同时发生：同一行内先改名再摘除."""
        engine, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "tags", "multiselect", config={"options": _opts("a", "b", "c")})
        session.commit()
        ddl.create_table(engine, table)

        sa = _reflect(engine, table)
        session.execute(
            sa.insert(),
            [{f.db_column_name: v} for v in ["a,b", "a,c", "c"]],
        )
        session.commit()

        old_config = dict(f.config or {})
        # a → a2 改名，b 删除
        f.config = {"options": _opts("a2", "c")}
        affected = sync_select_data_on_options_change(session, table, f, old_config)
        session.commit()

        assert affected == 2
        values = session.execute(select(sa.c[f.db_column_name])).scalars().all()
        assert values == ["a2", "a2,c", "c"]

    def test_rows_not_referencing_changed_options_untouched(self, test_session):
        """未引用被改名/被删除选项的行不写回（含全角分隔符等历史值）."""
        engine, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "tags", "multiselect", config={"options": _opts("a", "b", "c")})
        session.commit()
        ddl.create_table(engine, table)

        sa = _reflect(engine, table)
        session.execute(
            sa.insert(),
            [{f.db_column_name: v} for v in ["c", "c，b"]],  # 第二行用全角顿号分隔，不引用 a
        )
        session.commit()

        old_config = dict(f.config or {})
        f.config = {"options": _opts("a2", "b", "c")}
        affected = sync_select_data_on_options_change(session, table, f, old_config)
        session.commit()

        assert affected == 0
        values = session.execute(select(sa.c[f.db_column_name])).scalars().all()
        assert values == ["c", "c，b"]
