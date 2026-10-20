"""datasource M1：Normalizer（字段映射 + 类型归一）单测."""

from __future__ import annotations

from datetime import UTC, date, datetime

from cndb.plugins.datasource.providers.base import FieldTransform
from cndb.plugins.datasource.services.normalize import NormalizeResult, apply_field_mapping, coerce_value


class TestApplyFieldMapping:
    def test_empty_mapping_is_shallow_copy(self):
        rows = [{"a": 1, "b": 2}]
        result = apply_field_mapping(rows, {})
        assert result.rows == [{"a": 1, "b": 2}]
        assert result.rows[0] is not rows[0]
        assert result.dropped == 0
        assert result.failed == 0

    def test_rename_and_coerce(self):
        rows = [{"temp": "23.5", "city": "北京"}]
        mapping = {"temp": FieldTransform(name="temperature", field_type="float")}
        result = apply_field_mapping(rows, mapping)
        assert result.rows == [{"temperature": 23.5, "city": "北京"}]

    def test_dropped_field_removed(self):
        rows = [{"keep": "1", "noise": "x"}]
        result = apply_field_mapping(rows, {"noise": None})
        assert result.rows == [{"keep": "1"}]
        assert result.dropped == 1

    def test_unmapped_fields_kept_as_is(self):
        rows = [{"a": "1", "b": "keep"}]
        result = apply_field_mapping(rows, {"a": FieldTransform(name="a", field_type="int")})
        assert result.rows == [{"a": 1, "b": "keep"}]

    def test_coerce_failure_keeps_row_and_records(self):
        rows = [{"v": "not-a-number", "other": "ok"}]
        result = apply_field_mapping(rows, {"v": FieldTransform(name="v", field_type="float")})
        assert result.rows == [{"v": None, "other": "ok"}]
        assert result.failed == 1
        failure = result.failures[0]
        assert (failure.row_index, failure.field, failure.raw) == (0, "v", "not-a-number")
        assert "无法转为数值" in failure.reason

    def test_multiple_rows_failure_index(self):
        rows = [{"v": "1"}, {"v": "bad"}]
        result = apply_field_mapping(rows, {"v": FieldTransform(name="v", field_type="int")})
        assert result.rows == [{"v": 1}, {"v": None}]
        assert result.failures[0].row_index == 1

    def test_empty_rows(self):
        assert apply_field_mapping([], {"a": FieldTransform(name="b")}).rows == []


class TestCoerceValue:
    def test_none_stays_none(self):
        for kind in ("text", "int", "float", "date", "datetime", "bool"):
            assert coerce_value(None, kind) == (None, None)

    def test_text(self):
        assert coerce_value(12, "text") == ("12", None)
        assert coerce_value(True, "text") == ("true", None)
        assert coerce_value({"a": 1}, "text") == ('{"a": 1}', None)
        assert coerce_value("raw", "text") == ("raw", None)

    def test_int(self):
        assert coerce_value("42", "number") == (42, None)
        assert coerce_value(42.9, "int") == (42, None)
        assert coerce_value("1,234", "int") == (1234, None)
        assert coerce_value(True, "int") == (1, None)
        assert coerce_value("", "int") == (None, None)
        assert coerce_value("abc", "int")[0] is None

    def test_float(self):
        assert coerce_value("3.14", "float") == (3.14, None)
        assert coerce_value(3, "float") == (3.0, None)
        assert coerce_value("1，5", "float")[0] is None  # 中文逗号不是合法数字分隔
        assert coerce_value("", "float") == (None, None)

    def test_date(self):
        assert coerce_value("2024-03-05", "date") == ("2024-03-05", None)
        assert coerce_value("2024/03/05", "date") == ("2024-03-05", None)
        assert coerce_value("20240305", "date") == ("2024-03-05", None)
        assert coerce_value(datetime(2024, 3, 5, 12, 0), "date") == ("2024-03-05", None)
        assert coerce_value(date(2024, 3, 5), "date") == ("2024-03-05", None)
        assert coerce_value("2024-03-05T08:30:00", "date") == ("2024-03-05", None)
        assert coerce_value(1709596800, "date")[0] is not None
        assert coerce_value("", "date") == (None, None)
        assert coerce_value("不是日期", "date")[0] is None

    def test_datetime(self):
        assert coerce_value("2024-03-05 08:30:00", "datetime") == ("2024-03-05 08:30:00", None)
        assert coerce_value("20240305083000", "datetime") == ("2024-03-05 08:30:00", None)
        assert coerce_value("2024-03-05T08:30:00Z", "datetime") == ("2024-03-05 08:30:00", None)
        assert coerce_value(date(2024, 3, 5), "datetime") == ("2024-03-05 00:00:00", None)
        assert coerce_value(datetime(2024, 3, 5, 8, 30, 15), "datetime") == ("2024-03-05 08:30:15", None)
        assert coerce_value(1709596800000, "datetime")[0] is not None  # 毫秒
        assert coerce_value("2024-03-05 08:30", "datetime") == ("2024-03-05 08:30:00", None)
        assert coerce_value("", "datetime") == (None, None)
        assert coerce_value("nope", "datetime")[0] is None

    def test_bool(self):
        for token in ("1", "true", "YES", "on", "是"):
            assert coerce_value(token, "bool") == (True, None)
        for token in ("0", "false", "No", "off", "否"):
            assert coerce_value(token, "bool") == (False, None)
        assert coerce_value(True, "boolean") == (True, None)
        assert coerce_value("", "bool") == (None, None)
        assert coerce_value("maybe", "bool")[0] is None

    def test_unknown_type_falls_back_to_text(self):
        assert coerce_value(5, "weird_type") == ("5", None)

    def test_aware_datetime_formats_without_tz_suffix(self):
        aware = datetime(2024, 3, 5, 8, 30, tzinfo=UTC)
        assert coerce_value(aware, "datetime") == ("2024-03-05 08:30:00", None)


class TestNormalizeResult:
    def test_properties(self):
        result = NormalizeResult(rows=[{"a": 1}], dropped_fields=2)
        assert result.dropped == 2
        assert result.failed == 0
