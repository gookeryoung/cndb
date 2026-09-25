"""lookups.py 纯函数单元测试：split_lookup_filters / match_lookup_value / match_row_filters / sort_rows_in_memory.

覆盖极端与典型场景：嵌套分组拆分、聚合列表语义匹配、None 恒最后排序、
类型不可比较回退字符串比较、未知操作符按不匹配处理。
"""

from __future__ import annotations

import pytest

from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core.lookups import (
    match_lookup_value,
    match_row_filters,
    sort_rows_in_memory,
    split_lookup_filters,
)


@pytest.fixture
def mixed_table(db):
    """内存构造混合表：物理列 num/name + lookup 列 lnum（仅用于字段名判定，不查库）。"""
    tbl = DataTable(workspace_id=1, name="t_mem_mix")
    tbl.ensure_db_name()
    db.add(tbl)
    db.flush()
    for name, ftype, order in [("num", "number", 0), ("name", "text", 1), ("lnum", "lookup", 2)]:
        f = DataField(table_id=tbl.id, name=name, field_type=ftype, order=order)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    return tbl


# ── split_lookup_filters ──────────────────────────────────────────


class TestSplitLookupFilters:
    def test_none_and_empty_passthrough(self, mixed_table):
        """None / 空列表原样交给 SQL 端，内存端为空。"""
        assert split_lookup_filters(mixed_table, None) == (None, [])
        assert split_lookup_filters(mixed_table, []) == ([], [])

    def test_no_lookup_fields_all_sql(self, db):
        """表无 lookup 字段时全部条件留在 SQL 端。"""
        tbl = DataTable(workspace_id=1, name="t_mem_nolk")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="num", field_type="number", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        filters = [{"field_name": "num", "op": ">", "value": 1}]
        sql_items, lk_items = split_lookup_filters(tbl, filters)
        assert lk_items == []
        assert sql_items == filters

    def test_top_level_lookup_leaf_goes_memory(self, mixed_table):
        """顶层 lookup 叶子条件拆到内存端，物理条件留在 SQL 端。"""
        filters = [
            {"field_name": "num", "op": ">", "value": 1},
            {"field_name": "lnum", "op": "contains", "value": "x"},
        ]
        sql_items, lk_items = split_lookup_filters(mixed_table, filters)
        assert lk_items == [filters[1]]
        assert sql_items == [filters[0]]

    def test_nested_or_group_with_lookup_goes_memory_whole(self, mixed_table):
        """嵌套 __or__ 组内含 lookup 条件时整体留在内存端（含组内物理条件）。"""
        group = {
            "__or__": [{"field_name": "num", "op": ">", "value": 1}, {"field_name": "lnum", "op": "=", "value": 2}]
        }
        sql_items, lk_items = split_lookup_filters(mixed_table, [group])
        assert lk_items == [group]
        assert sql_items == []

    def test_pure_physical_nested_group_stays_sql(self, mixed_table):
        """纯物理条件的嵌套分组仍下推 SQL 端。"""
        group = {
            "__and__": [{"field_name": "num", "op": ">", "value": 1}, {"field_name": "name", "op": "=", "value": "a"}]
        }
        sql_items, lk_items = split_lookup_filters(mixed_table, [group])
        assert lk_items == []
        assert sql_items == [group]

    def test_deep_nested_lookup_detected(self, mixed_table):
        """递归深层嵌套（__and__ 内嵌 __or__ 含 lookup）也整体留内存端。"""
        group = {
            "__and__": [
                {"field_name": "num", "op": ">", "value": 1},
                {"__or__": [{"field_name": "lnum", "op": "is_empty"}]},
            ]
        }
        sql_items, lk_items = split_lookup_filters(mixed_table, [group])
        assert lk_items == [group]
        assert sql_items == []

    def test_non_dict_item_passthrough_sql(self, mixed_table):
        """非法条件项（非 dict）原样留在 SQL 端由调用方归一。"""
        sql_items, lk_items = split_lookup_filters(
            mixed_table, ["garbage", {"field_name": "num", "op": "=", "value": 1}]
        )
        assert lk_items == []
        assert sql_items == ["garbage", {"field_name": "num", "op": "=", "value": 1}]

    def test_dict_form_filters_passthrough(self, mixed_table):
        """dict 形式的 filters 不拆分，原样交给 SQL 端。"""
        filters = {"field_name": "lnum", "op": "=", "value": 1}
        assert split_lookup_filters(mixed_table, filters) == (filters, [])


# ── match_lookup_value ────────────────────────────────────────────


class TestMatchLookupValue:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, True),
            ([], True),
            ([1], False),
        ],
        ids=["none_is_empty", "empty_list_is_empty", "nonempty_not_empty"],
    )
    def test_is_empty_semantics(self, value, expected):
        """is_empty 对聚合列表语义：None 与空列表均为空。"""
        assert match_lookup_value(value, "is_empty", None) is expected

    def test_is_not_empty(self):
        """is_not_empty 与 is_empty 互补。"""
        assert match_lookup_value([], "is_not_empty", None) is False
        assert match_lookup_value([1], "is_not_empty", None) is True

    @pytest.mark.parametrize(
        ("value", "op", "expected", "matched"),
        [
            (5, "=", 5, True),
            ([1, 2], "=", 5, False),
            (None, "!=", 5, True),
            (5, "in", [1, 5], True),
            (5, "not_in", [1, 5], False),
        ],
        ids=["eq_scalar", "eq_list_not_matched", "neq_none", "in", "not_in"],
    )
    def test_comparison_ops(self, value, op, expected, matched):
        """标量与聚合列表的等值类操作符。"""
        assert match_lookup_value(value, op, expected) is matched

    @pytest.mark.parametrize(
        ("op", "expected", "matched"),
        [
            ("contains", "b", True),
            ("contains", "z", False),
            ("starts_with", "a", True),
            ("starts_with", "b", True),
            ("ends_with", "c", True),
            ("ends_with", "a", False),
        ],
    )
    def test_string_ops_over_list(self, op, expected, matched):
        """字符串类操作符对聚合列表逐项匹配。"""
        assert match_lookup_value(["abc", "bbc"], op, expected) is matched

    def test_contains_any_and_all(self):
        """contains_any 任一命中即真；contains_all 全部存在才真。"""
        assert match_lookup_value([1, 2], "contains_any", [2, 9]) is True
        assert match_lookup_value([1, 2], "contains_all", [2, 9]) is False
        assert match_lookup_value([1, 2], "contains_all", [1, 2]) is True

    @pytest.mark.parametrize(
        ("value", "op", "expected", "matched"),
        [
            ([1, None, 3], ">", 2, True),
            ([1, None, 3], "<", 2, True),
            ([1, None], ">=", 1, True),
            ([None, None], ">", 0, False),
        ],
        ids=["gt_skips_none", "lt_skips_none", "gte_min", "all_none_no_match"],
    )
    def test_ordering_ops_skip_none_members(self, value, op, expected, matched):
        """比较类操作符跳过列表中的 None 成员。"""
        assert match_lookup_value(value, op, expected) is matched

    def test_unknown_op_no_match(self):
        """未知操作符按不匹配处理且不抛错。"""
        assert match_lookup_value(1, "between", [1, 2]) is False


# ── match_row_filters ─────────────────────────────────────────────


class TestMatchRowFilters:
    def test_mixed_lookup_and_physical_and_logic(self, mixed_table):
        """顶层 AND 下 lookup 与物理列条件混合求值。"""
        row = {"id": 1, "num": 5, "name": "abc", "lnum": 9}
        assert match_row_filters(
            mixed_table,
            row,
            [{"field_name": "num", "op": ">", "value": 1}, {"field_name": "lnum", "op": "=", "value": 9}],
        )
        assert not match_row_filters(
            mixed_table,
            row,
            [{"field_name": "num", "op": ">", "value": 1}, {"field_name": "lnum", "op": "=", "value": 8}],
        )

    def test_or_group_and_query_or_group(self, mixed_table):
        """__or__ 与 __query_or__ 嵌套分组按 OR 语义求值。"""
        row = {"id": 1, "num": 5, "lnum": None}
        assert match_row_filters(
            mixed_table,
            row,
            [{"__or__": [{"field_name": "lnum", "op": "is_empty"}, {"field_name": "num", "op": "<", "value": 1}]}],
        )
        assert match_row_filters(
            mixed_table,
            row,
            [
                {
                    "__query_or__": [
                        {"field_name": "num", "op": "=", "value": 5},
                        {"field_name": "num", "op": "=", "value": 9},
                    ]
                }
            ],
        )
        assert not match_row_filters(
            mixed_table,
            row,
            [{"__or__": [{"field_name": "num", "op": "=", "value": 9}, {"field_name": "lnum", "op": "is_not_empty"}]}],
        )

    def test_dict_shorthand_filters_evaluated(self, mixed_table):
        """dict 形式的 {字段名: 值} 简写条件按等值匹配求值。"""
        row = {"id": 1, "num": 5, "lnum": 2}
        assert match_row_filters(mixed_table, row, {"lnum": 2})
        assert not match_row_filters(mixed_table, row, {"lnum": 3})
        assert match_row_filters(mixed_table, row, {"num": 5, "lnum": 2})

    def test_link_summary_value_via_physical_branch_fallback(self, mixed_table):
        """混合表无 link 字段：摘要结构走物理分支按不匹配处理，不崩溃。"""
        row = {"id": 1, "num": 1, "lnum": None}
        link_row = {"id": 1, "num": 1, "lnum": [{"id": 3, "value": "x"}]}
        assert {f.name for f in mixed_table.active_fields() if f.field_type == "link"} == set()
        assert not match_row_filters(mixed_table, link_row, [{"field_name": "name", "op": "has_any", "value": [3]}])
        assert match_row_filters(mixed_table, row, [{"field_name": "lnum", "op": "is_empty"}])

    def test_physical_between_and_type_fallback(self, mixed_table):
        """物理列 between 语义与类型不可比较时的字符串回退。"""
        row = {"id": 1, "num": 5, "name": "abc", "lnum": None}
        assert match_row_filters(mixed_table, row, [{"field_name": "num", "op": "between", "value": [1, 10]}])
        assert not match_row_filters(mixed_table, row, [{"field_name": "num", "op": "between", "value": [6, 10]}])
        # 字符串与数字直接比较失败时回退字符串比较
        assert match_row_filters(
            mixed_table, {"id": 2, "num": "b", "lnum": None}, [{"field_name": "num", "op": ">", "value": "a"}]
        )

    def test_empty_items_and_non_dict_items(self, mixed_table):
        """空条件与非 dict 项按恒真处理（不崩溃）。"""
        row = {"id": 1, "num": 5, "lnum": None}
        assert match_row_filters(mixed_table, row, [])
        assert match_row_filters(mixed_table, row, ["garbage"])


# ── sort_rows_in_memory ───────────────────────────────────────────


class TestSortRowsInMemory:
    def test_multi_key_asc_desc(self, mixed_table):
        """多级排序按列表顺序依次比较，方向独立。"""
        rows = [
            {"id": 1, "num": 2, "name": "b"},
            {"id": 2, "num": 1, "name": "c"},
            {"id": 3, "num": 1, "name": "a"},
        ]
        sorts = [
            {"field_name": "num", "direction": "asc"},
            {"field_name": "name", "direction": "desc"},
        ]
        result = sort_rows_in_memory(rows, sorts)
        assert [r["id"] for r in result] == [2, 3, 1]

    def test_none_always_last_regardless_of_direction(self, mixed_table):
        """None 值恒排最后，不随 asc/desc 反转。"""
        rows = [{"id": 1, "num": None}, {"id": 2, "num": 5}, {"id": 3, "num": 1}]
        asc = sort_rows_in_memory(rows, [{"field_name": "num", "direction": "asc"}])
        desc = sort_rows_in_memory(rows, [{"field_name": "num", "direction": "desc"}])
        assert [r["id"] for r in asc] == [3, 2, 1]
        assert [r["id"] for r in desc] == [2, 3, 1]

    def test_list_value_extreme_by_direction(self, mixed_table):
        """聚合列表按方向取极值：asc 取最小、desc 取最大。"""
        rows = [{"id": 1, "num": ["a", "c"]}, {"id": 2, "num": ["b", "x"]}]
        asc = sort_rows_in_memory(rows, [{"field_name": "num", "direction": "asc"}])
        desc = sort_rows_in_memory(rows, [{"field_name": "num", "direction": "desc"}])
        assert [r["id"] for r in asc] == [1, 2]  # min("a") < min("b")
        assert [r["id"] for r in desc] == [2, 1]  # max("x") > max("c")

    def test_mixed_types_fallback_to_str(self, mixed_table):
        """类型不可直接比较时回退字符串比较，不崩溃。"""
        rows = [{"id": 1, "num": 10}, {"id": 2, "num": "9"}]
        result = sort_rows_in_memory(rows, [{"field_name": "num", "direction": "asc"}])
        assert [r["id"] for r in result] == [1, 2]  # "10" < "9"（字符串比较）

    def test_invalid_and_empty_sorts_noop(self, mixed_table):
        """空/非法 sorts 原样返回，不排序不报错。"""
        rows = [{"id": 1, "num": 2}, {"id": 2, "num": 1}]
        assert sort_rows_in_memory(rows, []) == rows
        assert sort_rows_in_memory(rows, None) == rows
        assert sort_rows_in_memory(rows, ["bad"]) == rows
        assert sort_rows_in_memory(rows, [{"direction": "asc"}]) == rows
