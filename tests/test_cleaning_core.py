"""清洗纯函数共享层测试（plan 步骤 8）：从导入 cleaning.py 抽取的值变换."""

from __future__ import annotations

import pytest

from cndb.plugins.tables.services.cleaning_core import (
    apply_coerce,
    apply_drop_outliers,
    apply_fill_null,
    apply_trim,
)


class TestApplyTrim:
    def test_trims_strings_and_counts(self) -> None:
        rows = [{"name": " 张三 "}, {"name": "李四"}, {"name": None}, {"name": 5}]
        cleaned, affected = apply_trim(rows, "name")
        assert affected == 1
        assert cleaned[0]["name"] == "张三"
        assert cleaned[1]["name"] == "李四"

    def test_noop_when_no_change(self) -> None:
        rows = [{"name": "张三"}]
        _, affected = apply_trim(rows, "name")
        assert affected == 0


class TestApplyFillNull:
    def test_mean_strategy(self) -> None:
        rows = [{"age": None}, {"age": 10}, {"age": 20}]
        profile = {"mean": 15}
        cleaned, affected = apply_fill_null(rows, "age", "mean", profile)
        assert affected == 1
        assert cleaned[0]["age"] == 15

    def test_median_from_profile(self) -> None:
        rows = [{"age": None}, {"age": 1}, {"age": 100}]
        cleaned, affected = apply_fill_null(rows, "age", "median", {"median": 1})
        assert affected == 1
        assert cleaned[0]["age"] == 1

    def test_default_fill_value(self) -> None:
        rows = [{"name": None}, {"name": "张三"}, {"name": "   "}]
        cleaned, affected = apply_fill_null(rows, "name", "default", {"fill_value": "未知"})
        assert affected == 2
        assert cleaned[0]["name"] == "未知"
        assert cleaned[2]["name"] == "未知"

    def test_empty_strategy_noop(self) -> None:
        rows = [{"name": None}]
        _, affected = apply_fill_null(rows, "name", "empty", {})
        assert affected == 0

    def test_missing_stats_noop(self) -> None:
        rows = [{"age": None}]
        _, affected = apply_fill_null(rows, "age", "mean", {})
        assert affected == 0


class TestApplyCoerce:
    @pytest.mark.parametrize(
        ("raw", "target", "expected"),
        [
            ("12.5", "number", 12.5),
            ("13.0", "number", 13),
            ("true", "boolean", True),
            ("否", "boolean", False),
        ],
    )
    def test_coerce_success(self, raw, target, expected) -> None:
        rows = [{"v": raw}]
        cleaned, affected = apply_coerce(rows, "v", target, "nullify")
        assert affected == 1
        assert cleaned[0]["v"] == expected

    @pytest.mark.parametrize(
        ("raw", "target"),
        [
            ("2026-01-02", "date"),
            ("文本", "text"),
        ],
    )
    def test_coerce_valid_unchanged(self, raw, target) -> None:
        """合法但无需变更的值：转换成功（非法会被置空），不计受影响行."""
        rows = [{"v": raw}]
        cleaned, affected = apply_coerce(rows, "v", target, "nullify")
        assert affected == 0
        assert cleaned[0]["v"] == raw

    def test_nullify_on_fail(self) -> None:
        rows = [{"v": "abc"}, {"v": 12}]
        cleaned, affected = apply_coerce(rows, "v", "number", "nullify")
        assert affected == 1
        assert cleaned[0]["v"] is None
        assert cleaned[1]["v"] == 12

    def test_reject_on_fail_drops_row(self) -> None:
        rows = [{"v": "abc"}, {"v": 12}]
        cleaned, _affected = apply_coerce(rows, "v", "number", "reject")
        assert len(cleaned) == 1
        assert cleaned[0]["v"] == 12

    def test_none_value_stays_none(self) -> None:
        rows = [{"v": None}]
        cleaned, _ = apply_coerce(rows, "v", "number", "nullify")
        assert cleaned[0]["v"] is None


class TestApplyDropOutliers:
    def test_nullifies_outlier_values(self) -> None:
        rows = [{"v": 5.0}, {"v": 10.0}, {"v": 5.0}]
        profile = {"outliers": [{"value": 5.0, "type": "numeric"}]}
        cleaned, affected = apply_drop_outliers(rows, "v", profile)
        assert affected == 2
        assert cleaned[0]["v"] is None
        assert cleaned[1]["v"] == 10.0

    def test_no_outliers_noop(self) -> None:
        rows = [{"v": 5.0}]
        _, affected = apply_drop_outliers(rows, "v", {})
        assert affected == 0

    def test_rounded_outlier_value_matched_with_tolerance(self) -> None:
        """画像异常值经 round(6) 截断后仍能容差匹配高精度原始值."""
        raw = 0.123456789123
        profile = {"outliers": [{"value": round(raw, 6), "type": "numeric"}]}
        rows = [{"v": raw}, {"v": 1.0}]
        cleaned, affected = apply_drop_outliers(rows, "v", profile)
        assert affected == 1
        assert cleaned[0]["v"] is None
        assert cleaned[1]["v"] == 1.0

    def test_bool_and_non_numeric_skipped(self) -> None:
        """布尔与不可转数值的值跳过，不误置空."""
        profile = {"outliers": [{"value": 1.0, "type": "numeric"}]}
        rows = [{"v": True}, {"v": "abc"}, {"v": None}]
        cleaned, affected = apply_drop_outliers(rows, "v", profile)
        assert affected == 0
        assert cleaned[0]["v"] is True
        assert cleaned[2]["v"] is None
