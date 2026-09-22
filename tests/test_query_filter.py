"""query.py compile_filters 单测 —— 覆盖 dict/list/$query 三种 filters 形状."""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table

from cndb.plugins.tables.models import DataField
from cndb.plugins.tables.services.core.query import compile_filters, compile_sorts


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


# ── 新增操作符覆盖（第一轮增强） ──────────────────────────────


class TestNewOperators:
    """is_null / is_not_null / contains_any / contains_all / between."""

    def test_is_null(self, sa_table, table_with_fields):
        clause = compile_filters(table_with_fields, sa_table, [{"field_name": "name", "op": "is_null"}])
        assert clause is not None
        assert "IS NULL" in str(clause).upper()

    def test_is_not_null(self, sa_table, table_with_fields):
        clause = compile_filters(table_with_fields, sa_table, [{"field_name": "name", "op": "is_not_null"}])
        assert clause is not None
        assert "IS NOT NULL" in str(clause).upper()

    def test_contains_any(self, sa_table, table_with_fields):
        """multiselect 专用：值中包含任一."""
        clause = compile_filters(
            table_with_fields,
            sa_table,
            [{"field_name": "desc", "op": "contains_any", "value": ["hello", "world"]}],
        )
        assert clause is not None
        sql = str(clause)
        assert " OR " in sql.upper()

    def test_contains_any_empty_list(self, sa_table, table_with_fields):
        """空列表应返回 None（无有效条件）."""
        clause = compile_filters(
            table_with_fields,
            sa_table,
            [{"field_name": "desc", "op": "contains_any", "value": []}],
        )
        assert clause is None

    def test_contains_any_not_list(self, sa_table, table_with_fields):
        """非 list 值应抛 ValueError."""
        import pytest

        with pytest.raises(ValueError, match="contains_any"):
            compile_filters(
                table_with_fields,
                sa_table,
                [{"field_name": "desc", "op": "contains_any", "value": "not_a_list"}],
            )

    def test_contains_all(self, sa_table, table_with_fields):
        """multiselect 专用：值中包含全部."""
        clause = compile_filters(
            table_with_fields,
            sa_table,
            [{"field_name": "desc", "op": "contains_all", "value": ["hello", "world"]}],
        )
        assert clause is not None
        sql = str(clause)
        assert " AND " in sql.upper()

    def test_contains_all_empty_list(self, sa_table, table_with_fields):
        clause = compile_filters(
            table_with_fields,
            sa_table,
            [{"field_name": "desc", "op": "contains_all", "value": []}],
        )
        assert clause is None

    def test_between(self, sa_table, table_with_fields):
        """日期范围筛选 [start, end]."""
        clause = compile_filters(
            table_with_fields,
            sa_table,
            [{"field_name": "age", "op": "between", "value": [18, 60]}],
        )
        assert clause is not None

    def test_date_range_alias(self, sa_table, table_with_fields):
        """date_range 是 between 的别名."""
        clause = compile_filters(
            table_with_fields,
            sa_table,
            [{"field_name": "age", "op": "date_range", "value": [18, 60]}],
        )
        assert clause is not None

    def test_between_bad_value(self, sa_table, table_with_fields):
        """between 需要二元组."""
        import pytest

        with pytest.raises(ValueError, match="between"):
            compile_filters(
                table_with_fields,
                sa_table,
                [{"field_name": "age", "op": "between", "value": [1]}],
            )

    def test_unknown_field_warning(self, sa_table, table_with_fields):
        """不存在的字段应返回 None 并记 warning."""
        clause = compile_filters(table_with_fields, sa_table, [{"field_name": "nonexistent", "op": "="}])
        assert clause is None

    def test_unknown_op_raises(self, sa_table, table_with_fields):
        """未知操作符应抛 ValueError."""
        import pytest

        with pytest.raises(ValueError, match="未知操作符"):
            compile_filters(
                table_with_fields,
                sa_table,
                [{"field_name": "name", "op": "no_such_op"}],
            )


class TestQueryUnderscore:
    """`__query__` 键兼容（前端搜索输入框使用）."""

    def test_underscore_query_compiles(self, sa_table, table_with_fields):
        clause = compile_filters(table_with_fields, sa_table, {"__query__": "hello"})
        assert clause is not None
        assert "field_name" in str(clause) or "field_desc" in str(clause)


class TestNormalizeFieldType:
    """field_types.normalize_field_type 别名归一化."""

    def test_registry_auto_normalize(self):
        from cndb.plugins.tables.field_types import default_registry

        # decimal → float
        ft = default_registry.get("decimal")
        assert ft is not None
        assert ft.name == "float"

        # multi_select → multiselect
        ft2 = default_registry.get("multi_select")
        assert ft2 is not None
        assert ft2.name == "multiselect"

    def test_normalize_direct(self):
        from cndb.plugins.tables.field_types import normalize_field_type

        assert normalize_field_type("decimal") == "float"
        assert normalize_field_type("multi_select") == "multiselect"
        assert normalize_field_type("long_text") == "longtext"
        assert normalize_field_type("integer") == "number"

    def test_normalize_case_insensitive(self):
        from cndb.plugins.tables.field_types import normalize_field_type

        assert normalize_field_type("MultiSelect") == "multiselect"

    def test_normalize_non_string(self):
        from cndb.plugins.tables.field_types import normalize_field_type

        assert normalize_field_type(None) == "None"
        assert normalize_field_type(123) == "123"

    def test_normalize_unknown_passthrough(self):
        from cndb.plugins.tables.field_types import normalize_field_type

        assert normalize_field_type("no_such_type") == "no_such_type"


class TestOrAndGrouping:
    """compile_filters 的 __or__ / __and__ 嵌套组."""

    def test_or_group_dict(self, db):
        """传入 dict 形式的 __or__ 组 → 生成合法 where clause."""
        from sqlalchemy import Column, Integer, MetaData, String, Table

        from cndb.plugins.tables.services.core import query
        from cndb.plugins.tables.models import DataField, DataTable

        tbl = DataTable(workspace_id=1, name="t_or1")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="name", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)

        sa_t = Table(
            tbl.db_table_name,
            MetaData(),
            Column("id", Integer, primary_key=True),
            Column(f.db_column_name, String(255)),
        )
        where = query.compile_filters(
            tbl,
            sa_t,
            {
                "__or__": [
                    {"field_name": "name", "op": "=", "value": "foo"},
                    {"field_name": "name", "op": "=", "value": "bar"},
                ]
            },
        )
        assert where is not None
        sql = str(where.compile(compile_kwargs={"literal_binds": True}))
        assert "OR" in sql.upper()

    def test_or_group_list(self, db):
        """list 顶层含 __or__ dict."""
        from sqlalchemy import Column, Integer, MetaData, String, Table

        from cndb.plugins.tables.services.core import query
        from cndb.plugins.tables.models import DataField, DataTable

        tbl = DataTable(workspace_id=1, name="t_or2")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="name", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)

        sa_t = Table(
            tbl.db_table_name,
            MetaData(),
            Column("id", Integer, primary_key=True),
            Column(f.db_column_name, String(255)),
        )
        where = query.compile_filters(
            tbl,
            sa_t,
            [
                {"field_name": "name", "op": "=", "value": "foo"},
                {
                    "__or__": [
                        {"field_name": "name", "op": "contains", "value": "a"},
                        {"field_name": "name", "op": "contains", "value": "b"},
                    ]
                },
            ],
        )
        assert where is not None
        sql = str(where.compile(compile_kwargs={"literal_binds": True}))
        assert "AND" in sql.upper()
        assert "OR" in sql.upper()

    def test_and_group_explicit(self, db):
        from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table

        from cndb.plugins.tables.services.core import query
        from cndb.plugins.tables.models import DataField, DataTable

        tbl = DataTable(workspace_id=1, name="t_and1")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f1 = DataField(table_id=tbl.id, name="name", field_type="text", order=0)
        f1.ensure_db_name()
        f2 = DataField(table_id=tbl.id, name="active", field_type="boolean", order=1)
        f2.ensure_db_name()
        db.add_all([f1, f2])
        db.commit()
        db.refresh(tbl)

        sa_t = Table(
            tbl.db_table_name,
            MetaData(),
            Column("id", Integer, primary_key=True),
            Column(f1.db_column_name, String(255)),
            Column(f2.db_column_name, Boolean),
        )
        where = query.compile_filters(
            tbl,
            sa_t,
            {
                "__and__": [
                    {"field_name": "name", "op": "=", "value": "x"},
                    {"field_name": "active", "op": "=", "value": True},
                ]
            },
        )
        assert where is not None
        sql = str(where.compile(compile_kwargs={"literal_binds": True}))
        assert "AND" in sql.upper()

    def test_empty_or_group_returns_none(self, db):
        from sqlalchemy import Column, Integer, MetaData, String, Table

        from cndb.plugins.tables.services.core import query
        from cndb.plugins.tables.models import DataField, DataTable

        tbl = DataTable(workspace_id=1, name="t_empty")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="name", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        sa_t = Table(
            tbl.db_table_name,
            MetaData(),
            Column("id", Integer, primary_key=True),
            Column(f.db_column_name, String(255)),
        )

        assert query.compile_filters(tbl, sa_t, {"__or__": []}) is None

    def test_non_dict_items_in_group_skipped(self, db):
        from sqlalchemy import Column, Integer, MetaData, String, Table

        from cndb.plugins.tables.services.core import query
        from cndb.plugins.tables.models import DataField, DataTable

        tbl = DataTable(workspace_id=1, name="t_skip")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="name", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        sa_t = Table(
            tbl.db_table_name,
            MetaData(),
            Column("id", Integer, primary_key=True),
            Column(f.db_column_name, String(255)),
        )

        where = query.compile_filters(
            tbl,
            sa_t,
            {"__or__": [{"field_name": "name", "op": "=", "value": "x"}, "bad", None]},
        )
        assert where is not None


# ── compile_sorts 完整覆盖 ──────────────────────────────────


class TestCompileSorts:
    """compile_sorts 函数 — 多字段 / 方向 / 别名 / 未知字段跳过."""

    def test_empty_list_returns_empty(self, sa_table, table_with_fields):
        assert compile_sorts(table_with_fields, sa_table, []) == []

    def test_single_field_asc_default(self, sa_table, table_with_fields):
        """direction 省略时默认 asc."""
        result = compile_sorts(table_with_fields, sa_table, [{"field_name": "name"}])
        assert len(result) == 1
        sql = str(result[0])
        # asc 是默认排序，SQLAlchemy asc() 生成的 SQL 不含 DESC
        assert "field_name" in sql

    def test_single_field_desc(self, sa_table, table_with_fields):
        result = compile_sorts(
            table_with_fields,
            sa_table,
            [{"field_name": "age", "direction": "desc"}],
        )
        assert len(result) == 1
        sql = str(result[0]).upper()
        assert "DESC" in sql

    def test_direction_alias_dir(self, sa_table, table_with_fields):
        """`dir` 是 `direction` 的别名."""
        result = compile_sorts(
            table_with_fields,
            sa_table,
            [{"field_name": "age", "dir": "asc"}],
        )
        assert len(result) == 1

    def test_field_alias_field(self, sa_table, table_with_fields):
        """`field` 是 `field_name` 的别名."""
        result = compile_sorts(
            table_with_fields,
            sa_table,
            [{"field": "age", "direction": "desc"}],
        )
        assert len(result) == 1
        sql = str(result[0]).upper()
        assert "DESC" in sql

    def test_multiple_fields(self, sa_table, table_with_fields):
        """多字段排序 — 返回顺序与输入一致."""
        result = compile_sorts(
            table_with_fields,
            sa_table,
            [
                {"field_name": "age", "direction": "desc"},
                {"field_name": "name", "direction": "asc"},
            ],
        )
        assert len(result) == 2
        sql_descs = [str(c).upper() for c in result]
        assert "DESC" in sql_descs[0]
        assert "DESC" not in sql_descs[1]  # asc 默认不显式写

    def test_unknown_field_skipped(self, sa_table, table_with_fields):
        """不存在的字段名被跳过，不报错."""
        result = compile_sorts(
            table_with_fields,
            sa_table,
            [
                {"field_name": "nonexistent", "direction": "desc"},
                {"field_name": "age", "direction": "asc"},
            ],
        )
        assert len(result) == 1

    def test_all_unknown_fields_returns_empty(self, sa_table, table_with_fields):
        result = compile_sorts(
            table_with_fields,
            sa_table,
            [
                {"field_name": "xxx"},
                {"field_name": "yyy", "direction": "desc"},
            ],
        )
        assert result == []

    def test_direction_case_insensitive(self, sa_table, table_with_fields):
        result = compile_sorts(
            table_with_fields,
            sa_table,
            [{"field_name": "age", "direction": "DESC"}],
        )
        assert len(result) == 1
        assert "DESC" in str(result[0]).upper()

    def test_item_missing_field_name_skipped(self, sa_table, table_with_fields):
        result = compile_sorts(
            table_with_fields,
            sa_table,
            [
                {"direction": "asc"},  # 没有 field_name
                {"field_name": "age"},
            ],
        )
        assert len(result) == 1

    def test_non_dict_items_skipped(self, sa_table, table_with_fields):
        result = compile_sorts(
            table_with_fields,
            sa_table,
            ["not_a_dict", None, {"field_name": "age"}],
        )
        assert len(result) == 1
