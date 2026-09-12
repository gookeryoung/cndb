"""query.py compile_filters 单测 —— 覆盖 dict/list/$query 三种 filters 形状."""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table

from cndb.plugins.tables.models import DataField
from cndb.plugins.tables.query import compile_filters


@pytest.fixture
def sa_table():
    md = MetaData()
    return Table(
        "test_table",
        md,
        Column("id", Integer, primary_key=True),
        Column("field_name", String(80)),
        Column("field_desc", String(400)),
        Column("field_age", Integer),
        Column("field_email", String(120)),
    )


@pytest.fixture
def table_with_fields():
    """构造一个带文本/数字/email 字段的 DataTable-like 对象."""
    from types import SimpleNamespace

    fields = [
        DataField(id=1, name="name", field_type="text", db_column_name="field_name", table_id=1),
        DataField(id=2, name="desc", field_type="long_text", db_column_name="field_desc", table_id=1),
        DataField(id=3, name="age", field_type="number", db_column_name="field_age", table_id=1),
        DataField(id=4, name="email", field_type="email", db_column_name="field_email", table_id=1),
    ]
    return SimpleNamespace(id=1, fields=fields)


class TestCompileFiltersListForm:
    """旧格式 list[dict] 仍然可用."""

    def test_simple_eq(self, sa_table, table_with_fields):
        clause = compile_filters(table_with_fields, sa_table, [{"field_name": "name", "op": "=", "value": "alice"}])
        assert clause is not None
        sql = str(clause)
        assert "field_name" in sql
        assert "=" in sql

    def test_empty_list_returns_none(self, sa_table, table_with_fields):
        assert compile_filters(table_with_fields, sa_table, []) is None

    def test_unknown_field_skipped(self, sa_table, table_with_fields):
        clause = compile_filters(table_with_fields, sa_table, [{"field_name": "nope", "op": "=", "value": "x"}])
        assert clause is None

    def test_mixed_invalid_items_skipped(self, sa_table, table_with_fields):
        clause = compile_filters(
            table_with_fields,
            sa_table,
            ["not_a_dict", {"field_name": "name", "op": "eq", "value": "bob"}],
        )
        assert clause is not None


class TestCompileFiltersDictForm:
    """新增 dict {field: value} 自动转 eq 过滤器."""

    def test_simple_dict_eq(self, sa_table, table_with_fields):
        clause = compile_filters(table_with_fields, sa_table, {"name": "alice", "age": 18})
        assert clause is not None
        sql = str(clause)
        assert "field_name" in sql
        assert "field_age" in sql

    def test_empty_dict_returns_none(self, sa_table, table_with_fields):
        assert compile_filters(table_with_fields, sa_table, {}) is None

    def test_none_filters_returns_none(self, sa_table, table_with_fields):
        assert compile_filters(table_with_fields, sa_table, None) is None

    def test_dict_with_op_value(self, sa_table, table_with_fields):
        """dict 里 {field: {op, value}} 形式也能解析."""
        clause = compile_filters(table_with_fields, sa_table, {"age": {"op": ">", "value": 20}})
        assert clause is not None
        assert "field_age" in str(clause)


class TestCompileFiltersQueryKeyword:
    """新增 $query 特殊 key 做全局关键词模糊搜索."""

    def test_query_alone(self, sa_table, table_with_fields):
        """只有 $query —— 对所有文本字段做 OR contains."""
        clause = compile_filters(table_with_fields, sa_table, {"$query": "hello"})
        assert clause is not None
        sql = str(clause)
        # 应包含 name / desc / email（都是文本类型），不包含 age（数字）
        assert "field_name" in sql
        assert "field_desc" in sql
        assert "field_email" in sql
        assert "LIKE" in sql

    def test_query_with_other_fields(self, sa_table, table_with_fields):
        """$query + 普通字段 —— (OR 组) AND 普通条件."""
        clause = compile_filters(table_with_fields, sa_table, {"$query": "hello", "age": 18})
        assert clause is not None
        sql = str(clause)
        assert "field_age" in sql
        assert "field_name" in sql  # $query 展开的

    def test_query_no_text_fields(self, sa_table):
        """表上没有可搜索文本字段时，$query 应被跳过."""
        from types import SimpleNamespace

        no_text = [
            DataField(id=3, name="age", field_type="number", db_column_name="field_age", table_id=1),
        ]
        t = SimpleNamespace(id=1, fields=no_text)
        # 只有 $query 且无文本字段 → 无有效条件
        assert compile_filters(t, sa_table, {"$query": "hi"}) is None
        # $query + 有效字段 → 只剩有效字段
        clause = compile_filters(t, sa_table, {"$query": "hi", "age": 18})
        assert clause is not None
        assert "field_age" in str(clause)

    def test_query_empty_ignored(self, sa_table, table_with_fields):
        """空字符串 $query 不应产生条件."""
        clause = compile_filters(table_with_fields, sa_table, {"$query": ""})
        assert clause is None

    def test_query_with_trash_text_field(self, sa_table):
        """trashed=True 的文本字段不应参与 $query."""
        from types import SimpleNamespace

        fields = [
            DataField(id=1, name="name", field_type="text", db_column_name="field_name", table_id=1),
            DataField(id=2, name="old", field_type="long_text", db_column_name="field_desc", table_id=1),
        ]
        fields[1].trashed = True  # 第二个字段已删除
        t = SimpleNamespace(id=1, fields=fields)
        clause = compile_filters(t, sa_table, {"$query": "hi"})
        assert clause is not None
        sql = str(clause)
        assert "field_name" in sql
        assert "field_desc" not in sql


class TestCompileFiltersLogic:
    """logic=AND/OR 组合行为."""

    def test_or_logic_with_query(self, sa_table, table_with_fields):
        clause = compile_filters(
            table_with_fields,
            sa_table,
            [{"field_name": "name", "op": "=", "value": "a"}, {"field_name": "age", "op": "=", "value": 1}],
            logic="OR",
        )
        assert clause is not None
        assert " OR " in str(clause).upper() or "OR" in str(clause).upper()
