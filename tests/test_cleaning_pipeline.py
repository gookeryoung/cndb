"""清洗建议生成 + 执行单元测试 —— AC-4 验证.

覆盖 cleaning.generate_cleaning_suggestions 和 apply_cleaning_actions 的核心路径：
去重、填空、trim、coerce、drop_outliers、ignore_column.
"""

from __future__ import annotations

from cndb.plugins.tables.services.importing.cleaning import (
    apply_cleaning_actions,
    generate_cleaning_suggestions,
)

# ── 辅助：构造 column_profiles fixture ─────────


def _mk_profile(
    name: str,
    inferred_type: str = "text",
    *,
    confidence: float = 1.0,
    null_count: int = 0,
    null_ratio: float = 0.0,
    outliers: list | None = None,
    conflicts: list | None = None,
    sample_values: list | None = None,
    mean: float | None = None,
    distribution_bins: list | None = None,
) -> dict:
    p: dict = {
        "name": name,
        "inferred_type": inferred_type,
        "confidence": confidence,
        "fallback_type": None,
        "null_count": null_count,
        "null_ratio": null_ratio,
        "unique_count": 3,
        "sample_values": sample_values or [],
        "type_conflicts": conflicts or [],
        "outliers": outliers or [],
    }
    if mean is not None:
        p["mean"] = mean
    if distribution_bins is not None:
        p["distribution_bins"] = distribution_bins
    return p


class TestGenerateSuggestions:
    """TR-4.1: 建议生成的覆盖度与正确性."""

    def test_global_dedupe_suggestion(self):
        summary = {"total_rows": 100, "duplicate_rows": 5, "empty_columns": [], "high_null_columns": []}
        sugs = generate_cleaning_suggestions([], summary)
        assert any(s["action"] == "dedupe_rows" for s in sugs)

    def test_fill_null_on_high_null_ratio(self):
        profile = _mk_profile("notes", null_count=30, null_ratio=0.6, sample_values=["a", None, "b"])
        summary = {"duplicate_rows": 0, "empty_columns": [], "high_null_columns": ["notes"]}
        sugs = generate_cleaning_suggestions([profile], summary)
        assert any(s["action"] == "fill_null" and s["column"] == "notes" for s in sugs)

    def test_fill_null_numeric_uses_mean(self):
        profile = _mk_profile(
            "price",
            "number",
            null_count=20,
            null_ratio=0.4,
            mean=150.0,
            distribution_bins=[{"low": 100, "high": 200, "count": 5}],
        )
        summary = {"duplicate_rows": 0, "empty_columns": [], "high_null_columns": []}
        sugs = generate_cleaning_suggestions([profile], summary)
        fill = [s for s in sugs if s["action"] == "fill_null"]
        assert len(fill) == 1
        assert fill[0]["strategy"] == "mean"

    def test_ignore_column_on_almost_empty(self):
        profile = _mk_profile("empty_col", null_count=99, null_ratio=0.99)
        summary = {"duplicate_rows": 0, "empty_columns": ["empty_col"], "high_null_columns": ["empty_col"]}
        sugs = generate_cleaning_suggestions([profile], summary)
        assert any(s["action"] == "ignore_column" for s in sugs)

    def test_coerce_on_low_confidence_with_conflicts(self):
        profile = _mk_profile(
            "mix",
            "number",
            confidence=0.6,
            conflicts=[{"row_number": 1, "value": "abc", "conflicting_type": "text"}],
        )
        summary = {"duplicate_rows": 0, "empty_columns": [], "high_null_columns": []}
        sugs = generate_cleaning_suggestions([profile], summary)
        assert any(s["action"] == "coerce_type" for s in sugs)

    def test_drop_outliers_on_numeric(self):
        profile = _mk_profile(
            "amount",
            "number",
            outliers=[{"value": 9999.0, "type": "numeric"}],
            mean=100.0,
            distribution_bins=[{"low": 50, "high": 150, "count": 9}],
        )
        summary = {"duplicate_rows": 0, "empty_columns": [], "high_null_columns": []}
        sugs = generate_cleaning_suggestions([profile], summary)
        assert any(s["action"] == "drop_outliers" for s in sugs)

    def test_trim_on_whitespace_sample(self):
        profile = _mk_profile("name", "text", sample_values=[" alice ", " bob", "carol"])
        summary = {"duplicate_rows": 0, "empty_columns": [], "high_null_columns": []}
        sugs = generate_cleaning_suggestions([profile], summary)
        assert any(s["action"] == "trim_whitespace" for s in sugs)

    def test_all_suggestions_have_id_and_reason(self):
        summary = {"duplicate_rows": 3, "empty_columns": [], "high_null_columns": []}
        profile = _mk_profile(
            "mix",
            "number",
            confidence=0.5,
            null_count=10,
            null_ratio=0.3,
            conflicts=[{"row_number": 1, "value": "x", "conflicting_type": "text"}],
            outliers=[{"value": 999.0, "type": "numeric"}],
            sample_values=["1", "2", None],
            mean=50.0,
        )
        sugs = generate_cleaning_suggestions([profile], summary)
        for s in sugs:
            assert "id" in s and "reason" in s and "action" in s
            assert "preview_before" in s and "preview_after" in s

    def test_no_suggestions_on_clean_data(self):
        profile = _mk_profile("name", "text", sample_values=["a", "b", "c"])
        summary = {"duplicate_rows": 0, "empty_columns": [], "high_null_columns": []}
        sugs = generate_cleaning_suggestions([profile], summary)
        assert sugs == []


class TestApplyCleaningActions:
    """TR-5.1: 清洗执行的正确性."""

    def test_dedupe_keeps_first(self):
        rows = [{"a": 1}, {"a": 1}, {"a": 2}]
        cleaned, applied = apply_cleaning_actions(rows, [], [{"action": "dedupe_rows", "strategy": "keep_first"}])
        assert len(cleaned) == 2
        assert applied[0]["affected_rows"] == 1

    def test_fill_null_with_mean(self):
        rows = [{"price": 100}, {"price": 200}, {"price": None}]
        profile = _mk_profile("price", "number", mean=150.0)
        cleaned, applied = apply_cleaning_actions(
            rows, [profile], [{"column": "price", "action": "fill_null", "strategy": "mean"}]
        )
        assert cleaned[2]["price"] == 150.0
        assert applied[0]["affected_rows"] == 1

    def test_fill_null_noop_when_strategy_empty(self):
        rows = [{"x": None}]
        cleaned, applied = apply_cleaning_actions(
            rows, [], [{"column": "x", "action": "fill_null", "strategy": "empty"}]
        )
        assert cleaned[0]["x"] is None
        assert applied[0]["affected_rows"] == 0

    def test_trim_whitespace(self):
        rows = [{"name": "  alice  "}, {"name": "bob"}]
        cleaned, applied = apply_cleaning_actions(rows, [], [{"column": "name", "action": "trim_whitespace"}])
        assert cleaned[0]["name"] == "alice"
        assert cleaned[1]["name"] == "bob"
        assert applied[0]["affected_rows"] == 1

    def test_coerce_type_success(self):
        rows = [{"v": "123"}, {"v": "456"}, {"v": "not_a_number"}]
        profile = _mk_profile("v", "number")
        cleaned, applied = apply_cleaning_actions(
            rows, [profile], [{"column": "v", "action": "coerce_type", "strategy": "number", "on_fail": "nullify"}]
        )
        assert cleaned[0]["v"] == 123
        assert cleaned[1]["v"] == 456
        assert cleaned[2]["v"] is None
        assert applied[0]["affected_rows"] == 3  # 3 行都被修改或置空

    def test_coerce_type_reject_drops_row(self):
        rows = [{"v": "123"}, {"v": "bad"}, {"v": "456"}]
        profile = _mk_profile("v", "number")
        cleaned, _applied = apply_cleaning_actions(
            rows, [profile], [{"column": "v", "action": "coerce_type", "strategy": "number", "on_fail": "reject"}]
        )
        assert len(cleaned) == 2  # "bad" 被删除
        assert all(r["v"] in (123, 456) for r in cleaned)

    def test_coerce_boolean(self):
        rows = [{"active": "是"}, {"active": "否"}, {"active": "yes"}, {"active": "no"}]
        profile = _mk_profile("active", "boolean")
        cleaned, _applied = apply_cleaning_actions(
            rows,
            [profile],
            [{"column": "active", "action": "coerce_type", "strategy": "boolean", "on_fail": "nullify"}],
        )
        assert cleaned[0]["active"] is True
        assert cleaned[1]["active"] is False

    def test_drop_outliers_nullifies_value(self):
        rows = [{"price": 100}, {"price": 200}, {"price": 9999}]
        profile = _mk_profile("price", "number", outliers=[{"value": 9999.0, "type": "numeric"}])
        cleaned, applied = apply_cleaning_actions(rows, [profile], [{"column": "price", "action": "drop_outliers"}])
        assert cleaned[2]["price"] is None
        assert applied[0]["affected_rows"] == 1

    def test_ignore_column_removes_column(self):
        rows = [{"a": 1, "b": 2, "c": 3}]
        cleaned, _applied = apply_cleaning_actions(rows, [], [{"column": "b", "action": "ignore_column"}])
        assert "b" not in cleaned[0]
        assert cleaned[0] == {"a": 1, "c": 3}

    def test_empty_actions_returns_original(self):
        rows = [{"a": 1}, {"a": 2}]
        cleaned, applied = apply_cleaning_actions(rows, [], [])
        assert cleaned == rows
        assert applied == []

    def test_unknown_action_skipped(self):
        rows = [{"a": 1}]
        cleaned, applied = apply_cleaning_actions(rows, [], [{"action": "nonexistent"}])
        assert cleaned == rows
        assert applied == []

    def test_none_rows_handling(self):
        rows = [{"a": None}]
        cleaned, _applied = apply_cleaning_actions(
            rows, [], [{"column": "a", "action": "coerce_type", "strategy": "number"}]
        )
        assert cleaned[0]["a"] is None

    def test_multiple_actions_in_sequence(self):
        rows = [{"name": "  alice  ", "age": "30"}, {"name": " bob ", "age": "bad"}]
        profile_age = _mk_profile("age", "number")
        profile_name = _mk_profile("name", "text", sample_values=["  alice  ", " bob "])
        cleaned, applied = apply_cleaning_actions(
            rows,
            [profile_name, profile_age],
            [
                {"column": "name", "action": "trim_whitespace"},
                {"column": "age", "action": "coerce_type", "strategy": "number", "on_fail": "nullify"},
            ],
        )
        assert cleaned[0]["name"] == "alice"
        assert cleaned[0]["age"] == 30
        assert cleaned[1]["age"] is None
        assert len(applied) == 2

    def test_fill_null_median_from_bins(self):
        """median 策略：从 distribution_bins 估算."""
        rows = [{"price": 100}, {"price": 200}, {"price": None}]
        profile = _mk_profile(
            "price",
            "number",
            distribution_bins=[
                {"low": 50, "high": 150, "count": 1},
                {"low": 150, "high": 250, "count": 2},
            ],
        )
        cleaned, applied = apply_cleaning_actions(
            rows, [profile], [{"column": "price", "action": "fill_null", "strategy": "median"}]
        )
        assert cleaned[2]["price"] is not None
        assert applied[0]["affected_rows"] == 1

    def test_fill_null_strategy_none(self):
        """没有指定 strategy 或 strategy 无效时，fill_value=None → 不动."""
        rows = [{"x": None}]
        profile = _mk_profile("x", "number")
        cleaned, applied = apply_cleaning_actions(
            rows, [profile], [{"column": "x", "action": "fill_null", "strategy": None}]
        )
        assert cleaned[0]["x"] is None
        assert applied[0]["affected_rows"] == 0

    def test_coerce_boolean_all_variants(self):
        """中文布尔 / yes/no / on/off 全部转 boolean."""
        rows = [
            {"f": "true"},
            {"f": "false"},
            {"f": "yes"},
            {"f": "no"},
            {"f": "是"},
            {"f": "否"},
            {"f": "on"},
            {"f": "off"},
            {"f": "1"},
            {"f": "0"},
            {"f": "unknown"},
        ]
        profile = _mk_profile("f", "boolean")
        cleaned, _applied = apply_cleaning_actions(
            rows, [profile], [{"column": "f", "action": "coerce_type", "strategy": "boolean", "on_fail": "nullify"}]
        )
        assert cleaned[0]["f"] is True
        assert cleaned[1]["f"] is False
        assert cleaned[4]["f"] is True
        assert cleaned[5]["f"] is False
        assert cleaned[-1]["f"] is None  # unknown 转失败

    def test_coerce_date_variants(self):
        """多种日期格式都能被 coerce 通过."""
        rows = [{"d": "2024-01-15"}, {"d": "2024/1/1"}, {"d": "2024年3月15日"}]
        profile = _mk_profile("d", "date")
        cleaned, _applied = apply_cleaning_actions(
            rows, [profile], [{"column": "d", "action": "coerce_type", "strategy": "date", "on_fail": "nullify"}]
        )
        # 所有值应该保留（都能被识别）
        assert cleaned[0]["d"] == "2024-01-15"
        assert cleaned[2]["d"] == "2024年3月15日"

    def test_coerce_number_exception(self):
        """极端不可转值走异常分支."""
        rows = [{"v": object()}]
        profile = _mk_profile("v", "number")
        cleaned, _applied = apply_cleaning_actions(
            rows, [profile], [{"column": "v", "action": "coerce_type", "strategy": "number", "on_fail": "nullify"}]
        )
        assert cleaned[0]["v"] is None

    def test_drop_outliers_no_outliers(self):
        """profile 没有 outliers → 不做任何事."""
        rows = [{"x": 1}, {"x": 2}, {"x": 3}]
        profile = _mk_profile("x", "number", outliers=[])
        cleaned, applied = apply_cleaning_actions(rows, [profile], [{"column": "x", "action": "drop_outliers"}])
        assert cleaned == rows
        assert applied[0]["affected_rows"] == 0

    def test_drop_outliers_type_mismatch(self):
        """outliers 有 str 但行里是 float → float(v) 失败跳过."""
        rows = [{"x": "not-a-num"}, {"x": 9999}]
        profile = _mk_profile("x", "number", outliers=[{"value": 9999, "type": "numeric"}])
        cleaned, applied = apply_cleaning_actions(rows, [profile], [{"column": "x", "action": "drop_outliers"}])
        # "not-a-num" 无法 float 转换，9999 会被置空
        assert cleaned[1]["x"] is None
        assert applied[0]["affected_rows"] == 1

    def test_coerce_to_text(self):
        """coerce 到 text 类型，所有值转字符串."""
        rows = [{"v": 123}, {"v": None}, {"v": "ok"}]
        profile = _mk_profile("v", "text")
        cleaned, _applied = apply_cleaning_actions(
            rows, [profile], [{"column": "v", "action": "coerce_type", "strategy": "text", "on_fail": "nullify"}]
        )
        assert cleaned[0]["v"] == "123"
        assert cleaned[1]["v"] is None  # None 返回 None, True

    def test_apply_cleaning_empty_rows(self):
        """空 rows 边界."""
        cleaned, applied = apply_cleaning_actions([], [], [{"action": "dedupe_rows", "strategy": "keep_first"}])
        assert cleaned == []
        assert applied[0]["affected_rows"] == 0

    def test_apply_coerce_no_target_strategy(self):
        """coerce 没有 strategy → 空操作."""
        rows = [{"v": "123"}]
        profile = _mk_profile("v", "number")
        cleaned, applied = apply_cleaning_actions(
            rows,
            [profile],
            [
                {"column": "v", "action": "coerce_type"}  # 无 strategy
            ],
        )
        assert cleaned == rows
        assert len(applied) == 1 and applied[0]["affected_rows"] == 0
