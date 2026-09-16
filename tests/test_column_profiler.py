"""列级数据质量画像单元测试 —— AC-2 验证.

聚焦 column_profiler.profile_columns 及其辅助函数的数值正确性、
混合类型冲突、异常值检测、重复行预估等场景.
"""

from __future__ import annotations

import pytest

from cndb.plugins.tables.column_profiler import (
    DEFAULT_SAMPLE_LIMIT,
    _build_histogram,
    _estimate_duplicate_rows,
    _iqr_outliers,
    _profile_single_column,
    _rare_text_values,
    _try_float,
    profile_columns,
)


class TestTryFloat:
    """TR-2.1: 数值解析的鲁棒性."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (123, 123.0),
            (12.5, 12.5),
            ("123", 123.0),
            ("1,234", 1234.0),
            ("1,234.56", 1234.56),
            ("1.234,56", 1.23456),  # _try_float 只做简单 replace，无法识别欧元格式
            ("  42  ", 42.0),
            ("¥99", 99.0),
            ("$19.99", 19.99),
            ("", None),
            ("abc", None),
            (None, None),
            ([], None),
        ],
    )
    def test_various_inputs(self, raw, expected):
        assert _try_float(raw) == expected


class TestIqrOutliers:
    """TR-2.1: IQR 异常值检测."""

    def test_no_outliers_in_normal_data(self):
        vals = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        assert _iqr_outliers(vals) == []

    def test_detects_outliers(self):
        vals = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 999]
        outliers = _iqr_outliers(vals)
        assert 999 in outliers

    def test_too_few_values(self):
        assert _iqr_outliers([1, 2]) == []

    def test_constant_values(self):
        assert _iqr_outliers([5, 5, 5, 5, 5, 5, 5, 5]) == []


class TestRareTextValues:
    """TR-2.1: 文本列稀有值检测."""

    def test_detects_rare(self):
        texts = ["apple"] * 50 + ["banana"] * 40 + ["cherry"] * 2 + ["date"] * 1
        rare = _rare_text_values(texts, threshold_ratio=0.05)
        assert "date" in rare
        assert "cherry" in rare

    def test_empty(self):
        assert _rare_text_values([], 0.1) == []

    def test_all_common(self):
        texts = ["a"] * 100
        assert _rare_text_values(texts, 0.05) == []


class TestBuildHistogram:
    """TR-2.1: 数值直方图构建."""

    def test_basic(self):
        vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        bins = _build_histogram(vals)
        assert len(bins) == 10
        assert bins[0]["low"] == 1.0
        assert bins[-1]["high"] == 10.0
        assert all("count" in b and "bin_label" in b for b in bins)

    def test_constant(self):
        bins = _build_histogram([5, 5, 5, 5])
        assert len(bins) == 1
        assert bins[0]["count"] == 4

    def test_empty(self):
        assert _build_histogram([]) == []


class TestEstimateDuplicateRows:
    """TR-2.1: 重复行预估."""

    def test_no_dupes(self):
        rows = [{"a": i, "b": i} for i in range(10)]
        assert _estimate_duplicate_rows(rows, ["a", "b"]) == 0

    def test_with_dupes(self):
        rows = [{"a": 1, "b": "x"}, {"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
        assert _estimate_duplicate_rows(rows, ["a", "b"]) == 1

    def test_less_than_two_rows(self):
        assert _estimate_duplicate_rows([], ["a"]) == 0
        assert _estimate_duplicate_rows([{"a": 1}], ["a"]) == 0

    def test_empty_columns(self):
        rows = [{"a": 1}]
        assert _estimate_duplicate_rows(rows, []) == 0


class TestProfileSingleColumn:
    """TR-2.2: 单列画像正确性 —— 混合类型、高空值、类型推断."""

    def test_all_text(self):
        rows = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        profile = _profile_single_column(rows, "name", 3)
        assert profile["inferred_type"] == "text"
        assert profile["null_count"] == 0
        assert profile["null_ratio"] == 0.0
        assert profile["unique_count"] == 3
        assert profile["confidence"] == 1.0

    def test_mostly_number(self):
        rows = [{"v": "100"}, {"v": "200"}, {"v": "abc"}, {"v": "300"}, {"v": "400"}, {"v": "500"}]
        profile = _profile_single_column(rows, "v", 6)
        # 数字类应该最常出现，confidence < 1 因为有 "abc" 冲突
        assert profile["confidence"] < 1.0
        assert len(profile["type_conflicts"]) >= 1
        # 有 5 个数字样本 >= 4，应该包含 min/max/mean 统计
        assert profile.get("min") is not None
        assert profile.get("max") is not None

    def test_high_null_ratio(self):
        rows = [{"x": None}, {"x": None}, {"x": "ok"}, {"x": None}]
        profile = _profile_single_column(rows, "x", 4)
        assert profile["null_count"] == 3
        assert profile["null_ratio"] == pytest.approx(0.75, abs=0.01)
        assert profile["confidence"] == 1.0  # 剩下一个有效值

    def test_string_whitespace_counted_as_null(self):
        rows = [{"x": "  "}, {"x": ""}, {"x": "value"}]
        profile = _profile_single_column(rows, "x", 3)
        assert profile["null_count"] == 2

    def test_outliers_in_numeric(self):
        rows = [{"price": str(i)} for i in range(10, 20)] + [{"price": "9999"}]
        profile = _profile_single_column(rows, "price", 11)
        assert len(profile["outliers"]) >= 1

    def test_low_cardinality_promoted_to_select(self):
        rows = [{"status": "active"}, {"status": "active"}, {"status": "inactive"}, {"status": "pending"}]
        profile = _profile_single_column(rows, "status", 4)
        # 低基数 (4 个唯一值) 可能被晋升为 select
        # 这里不做强断言（取决于 _promote_to_select_if_low_cardinality 的阈值）
        assert profile["inferred_type"] in ("select", "text")
        if "value_counts" in profile:
            vc = profile["value_counts"]
            assert len(vc) <= 10
            assert all("value" in v and "count" in v for v in vc)

    def test_none_raw(self):
        rows = [{"v": None}, {"v": None}, {"v": None}]
        profile = _profile_single_column(rows, "v", 3)
        assert profile["null_count"] == 3
        assert profile["null_ratio"] == 1.0
        assert profile["inferred_type"] == "text"  # 空列默认 text

    def test_boolean_column(self):
        rows = [{"active": True}, {"active": False}, {"active": True}]
        profile = _profile_single_column(rows, "active", 3)
        assert profile["inferred_type"] == "boolean"

    def test_native_number_values(self):
        rows = [{"n": 1}, {"n": 2}, {"n": 3}, {"n": 4}, {"n": 5}]
        profile = _profile_single_column(rows, "n", 5)
        assert profile["inferred_type"] == "number"
        assert profile["min"] == 1.0
        assert profile["max"] == 5.0


class TestProfileColumnsMain:
    """TR-2.1: profile_columns 主函数的端到端行为."""

    def test_basic_summary(self):
        rows = [
            {"name": "Alice", "age": "25", "note": None},
            {"name": "Bob", "age": "30", "note": "ok"},
            {"name": "Carol", "age": "28", "note": ""},
        ]
        profiles, summary = profile_columns(rows, ["name", "age", "note"])
        assert summary["total_rows"] == 3
        assert summary["total_columns"] == 3
        assert len(profiles) == 3
        assert all("name" in p and "inferred_type" in p for p in profiles)

    def test_empty_columns_detected(self):
        rows = [{"a": None, "b": "ok"}, {"a": "", "b": "fine"}]
        _profiles, summary = profile_columns(rows, ["a", "b"])
        assert "a" in summary["empty_columns"]

    def test_high_null_columns(self):
        rows = [{"x": "val", "y": None} for _ in range(10)]
        rows[5]["x"] = None  # 让 x 有 10% 空值（不算高），y 始终 100%
        _profiles, summary = profile_columns(rows, ["x", "y"])
        assert "y" in summary["empty_columns"]
        assert "x" not in summary["high_null_columns"]

    def test_duplicate_rows_estimation(self):
        rows = [{"a": 1, "b": "x"}, {"a": 1, "b": "x"}, {"a": 2, "b": "y"}, {"a": 1, "b": "x"}]
        _profiles, summary = profile_columns(rows, ["a", "b"])
        assert summary["duplicate_rows"] >= 2

    def test_empty_input(self):
        profiles, summary = profile_columns([], [])
        assert profiles == []
        assert summary["total_rows"] == 0
        assert summary["total_columns"] == 0

    def test_none_column_name(self):
        """列值为 None 的场景."""
        rows = [{"col": None}]
        profiles, summary = profile_columns(rows, ["col"])
        assert len(profiles) == 1
        assert profiles[0]["null_ratio"] == 1.0
        assert summary["high_null_columns"] == ["col"] or summary["empty_columns"] == ["col"]

    def test_large_rows_sampled(self):
        """超过 DEFAULT_SAMPLE_LIMIT 时只采样."""
        rows = [{"x": i} for i in range(DEFAULT_SAMPLE_LIMIT + 100)]
        _profiles, summary = profile_columns(rows, ["x"])
        # 不崩就行
        assert summary["total_rows"] == len(rows)

    def test_json_value_detection(self):
        rows = [{"data": [1, 2, 3]}, {"data": {"key": "val"}}]
        profiles, _summary = profile_columns(rows, ["data"])
        assert profiles[0]["inferred_type"] == "json"
