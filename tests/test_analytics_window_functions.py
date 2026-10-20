"""analytics M4：公式引擎窗口函数（分区 + 排序）单测.

覆盖：白名单与参数校验、四类窗口语义（前后行 / 累计 / 滚动 / 名次）、
分区与排序（含降序、原始行序、空值排在最后）、越界与不满窗返回 None。
"""

from __future__ import annotations

import pytest

from cndb.plugins.analytics.services.formula import (
    FormulaError,
    evaluate_column,
    parse,
    partition_rows,
    referenced_fields,
    uses_window,
    uses_window_expr,
    window_functions,
)

FIELDS = ["symbol", "day", "x"]
ROWS = [
    {"symbol": "A", "day": "2024-01-01", "x": 10},
    {"symbol": "A", "day": "2024-01-02", "x": 20},
    {"symbol": "A", "day": "2024-01-03", "x": 30},
    {"symbol": "B", "day": "2024-01-01", "x": 5},
    {"symbol": "B", "day": "2024-01-02", "x": 5},
    {"symbol": "B", "day": "2024-01-03", "x": 15},
]


def _col(expr: str, **kwargs: object) -> list[float | None]:
    return evaluate_column(expr, ROWS, FIELDS, **kwargs)  # type: ignore[arg-type]


class TestWhitelist:
    def test_window_functions_registered(self):
        assert set(window_functions()) == {
            "prev",
            "lag",
            "lead",
            "diff",
            "pct_change",
            "cumsum",
            "ma",
            "rolling_sum",
            "rolling_std",
            "rank",
        }

    def test_first_arg_must_be_field(self):
        with pytest.raises(FormulaError, match="第一个参数必须是字段引用"):
            parse("lag(1)")

    def test_unknown_function_rejected(self):
        with pytest.raises(FormulaError, match="未知函数"):
            parse("ewma([x], 3)")

    def test_too_many_args_rejected(self):
        with pytest.raises(FormulaError, match="参数个数不合法"):
            parse("prev([x], 1, 2)")

    def test_uses_window(self):
        assert uses_window_expr("ma([x], 3)") is True
        assert uses_window_expr("round([x] / 2, 1)") is False
        assert uses_window(parse("sum([x]) + ma([x], 2)")) is True

    def test_referenced_fields_include_window_arg(self):
        assert referenced_fields(parse("ma([x], 3)")) == {"x"}


class TestPartition:
    def test_groups_keep_first_seen_order(self):
        assert partition_rows(ROWS, partition_by="symbol") == [[0, 1, 2], [3, 4, 5]]

    def test_order_within_group(self):
        shuffled = [ROWS[2], ROWS[0], ROWS[1]]
        assert partition_rows(shuffled, partition_by="symbol", order_by="day") == [[1, 2, 0]]

    def test_order_desc(self):
        assert partition_rows(ROWS, partition_by="symbol", order_by="day", order_desc=True) == [
            [2, 1, 0],
            [5, 4, 3],
        ]

    def test_no_partition_is_single_group(self):
        assert partition_rows(ROWS, order_by="x") == [[3, 4, 0, 5, 1, 2]]

    def test_unknown_field_rejected(self):
        with pytest.raises(FormulaError, match="未知分区字段"):
            partition_rows(ROWS, partition_by="nope", field_names=set(FIELDS))
        with pytest.raises(FormulaError, match="未知排序字段"):
            partition_rows(ROWS, order_by="nope", field_names=set(FIELDS))

    def test_none_grouped_separately(self):
        rows = [{"g": None, "x": 1}, {"g": "a", "x": 2}, {"g": None, "x": 3}]
        assert partition_rows(rows, partition_by="g") == [[0, 2], [1]]


class TestShiftFamily:
    def test_prev_and_lag_and_lead(self):
        kwargs = {"partition_by": "symbol", "order_by": "day"}
        assert _col("prev([x])", **kwargs) == [None, 10, 20, None, 5, 5]
        assert _col("lag([x], 2)", **kwargs) == [None, None, 10, None, None, 5]
        assert _col("lead([x])", **kwargs) == [20, 30, None, 5, 15, None]
        assert _col("lead([x], 2)", **kwargs) == [30, None, None, 15, None, None]

    def test_diff_and_pct_change(self):
        kwargs = {"partition_by": "symbol", "order_by": "day"}
        assert _col("diff([x])", **kwargs) == [None, 10, 10, None, 0, 10]
        assert _col("pct_change([x])", **kwargs) == [None, 1.0, 0.5, None, 0.0, 2.0]

    def test_pct_change_from_zero_is_none(self):
        rows = [{"g": "A", "x": 0}, {"g": "A", "x": 10}]
        assert evaluate_column("pct_change([x])", rows, ["g", "x"], partition_by="g") == [None, None]

    def test_shift_none_value_stays_none(self):
        rows = [{"g": "A", "x": 10}, {"g": "A", "x": None}, {"g": "A", "x": 30}]
        assert evaluate_column("prev([x])", rows, ["g", "x"], partition_by="g") == [None, None, None]

    def test_without_order_uses_raw_order(self):
        assert _col("prev([x])") == [None, 10, 20, 30, 5, 5]


class TestCumulativeAndRolling:
    def test_cumsum_per_partition(self):
        assert _col("cumsum([x])", partition_by="symbol", order_by="day") == [10, 30, 60, 5, 10, 25]

    def test_cumsum_skips_blanks(self):
        rows = [{"g": "A", "x": 10}, {"g": "A", "x": None}, {"g": "A", "x": 5}]
        assert evaluate_column("cumsum([x])", rows, ["g", "x"], partition_by="g") == [10, 10, 15]

    def test_cumsum_all_blank_is_none(self):
        rows = [{"g": "A", "x": None}, {"g": "A", "x": ""}]
        assert evaluate_column("cumsum([x])", rows, ["g", "x"], partition_by="g") == [None, None]

    def test_ma_needs_full_window(self):
        got = _col("ma([x], 2)", partition_by="symbol", order_by="day")
        assert got == [None, 15.0, 25.0, None, 5.0, 10.0]

    def test_rolling_sum(self):
        got = _col("rolling_sum([x], 2)", partition_by="symbol", order_by="day")
        assert got == [None, 30.0, 50.0, None, 10.0, 20.0]

    def test_rolling_std_population(self):
        got = _col("rolling_std([x], 2)", partition_by="symbol", order_by="day")
        assert got == [None, 5.0, 5.0, None, 0.0, 5.0]

    def test_default_window_is_three(self):
        assert _col("ma([x])", partition_by="symbol", order_by="day") == [None, None, 20.0, None, None, 25 / 3]

    def test_window_with_blank_requires_full_non_null(self):
        rows = [{"g": "A", "x": 10}, {"g": "A", "x": None}, {"g": "A", "x": 30}]
        assert evaluate_column("ma([x], 2)", rows, ["g", "x"], partition_by="g") == [None, None, None]
        assert evaluate_column("rolling_sum([x], 3)", rows, ["g", "x"], partition_by="g") == [None, None, None]


class TestRank:
    def test_rank_with_ties(self):
        assert _col("rank([x])", partition_by="symbol", order_by="day") == [1.0, 2.0, 3.0, 1.0, 1.0, 3.0]

    def test_rank_ignores_blank(self):
        rows = [{"g": "A", "x": 5}, {"g": "A", "x": None}, {"g": "A", "x": 1}]
        assert evaluate_column("rank([x])", rows, ["g", "x"], partition_by="g") == [2.0, None, 1.0]

    def test_rank_is_competition_style(self):
        rows = [{"g": "A", "x": 1}, {"g": "A", "x": 1}, {"g": "A", "x": 2}]
        assert evaluate_column("rank([x])", rows, ["g", "x"], partition_by="g") == [1.0, 1.0, 3.0]

    def test_rank_all_blank(self):
        rows = [{"g": "A", "x": None}]
        assert evaluate_column("rank([x])", rows, ["g", "x"], partition_by="g") == [None]

    def test_rank_on_time_column(self):
        """时间列以前全为 None（数值化为空），现在按时间先后给名次."""
        rows = [
            {"g": "A", "day": "2024-01-03"},
            {"g": "A", "day": "2024-01-01"},
            {"g": "A", "day": "2024-01-02"},
        ]
        assert evaluate_column("rank([day])", rows, ["g", "day"], partition_by="g") == [3.0, 1.0, 2.0]

    def test_rank_time_with_datetime_text(self):
        """带时分秒的定宽时间串同样是字典序 = 时间序."""
        rows = [
            {"g": "A", "ts": "2024-01-01 10:00:00"},
            {"g": "A", "ts": "2024-01-01 09:30:00"},
        ]
        assert evaluate_column("rank([ts])", rows, ["g", "ts"], partition_by="g") == [2.0, 1.0]

    def test_rank_on_text_column(self):
        """文本列按字面序（Unicode 码点）给名次，不再整列为 None."""
        rows = [{"g": "A", "level": "beta"}, {"g": "A", "level": "alpha"}]
        got = evaluate_column("rank([level])", rows, ["g", "level"], partition_by="g")
        assert got == [2.0, 1.0]

    def test_rank_text_ties_and_blank(self):
        rows = [
            {"g": "A", "level": "beta"},
            {"g": "A", "level": "beta"},
            {"g": "A", "level": "  "},
            {"g": "A", "level": "alpha"},
        ]
        assert evaluate_column("rank([level])", rows, ["g", "level"], partition_by="g") == [2.0, 2.0, None, 1.0]

    def test_rank_numeric_strings_still_numeric(self):
        """形如数字的文本列按数值排（"10" 不能排到 "2" 前面）."""
        rows = [{"g": "A", "code": "10"}, {"g": "A", "code": "2"}]
        assert evaluate_column("rank([code])", rows, ["g", "code"], partition_by="g") == [2.0, 1.0]

    def test_rank_is_per_partition_on_time(self):
        rows = [
            {"g": "A", "day": "2024-01-02"},
            {"g": "B", "day": "2024-01-05"},
            {"g": "A", "day": "2024-01-01"},
            {"g": "B", "day": "2024-01-04"},
        ]
        assert evaluate_column("rank([day])", rows, ["g", "day"], partition_by="g") == [2.0, 2.0, 1.0, 1.0]


class TestComposition:
    def test_window_inside_scalar_function(self):
        got = _col("round(ma([x], 2), 1)", partition_by="symbol", order_by="day")
        assert got == [None, 15.0, 25.0, None, 5.0, 10.0]

    def test_window_combined_with_aggregate(self):
        # 聚合口径仍是「整列」（全表 85），窗口只改变逐行位置语义
        got = _col("round([x] / sum([x]) * 100, 2)", partition_by="symbol", order_by="day")
        assert got == [11.76, 23.53, 35.29, 5.88, 5.88, 17.65]

    def test_window_minus_lag_equals_diff(self):
        kwargs = {"partition_by": "symbol", "order_by": "day"}
        assert _col("[x] - prev([x])", **kwargs) == _col("diff([x])", **kwargs)

    def test_plain_formula_unchanged_without_window(self):
        assert _col("round([x] * 2, 0)", partition_by="symbol", order_by="day") == [
            20.0,
            40.0,
            60.0,
            10.0,
            10.0,
            30.0,
        ]

    def test_division_by_zero_is_none(self):
        rows = [{"g": "A", "x": 10, "y": 0}]
        assert evaluate_column("[x] / [y]", rows, ["g", "x", "y"]) == [None]

    def test_empty_rows(self):
        assert evaluate_column("ma([x], 2)", [], FIELDS) == []
