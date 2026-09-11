"""field_types 单元测试."""

import pytest

from cndb.plugins.tables.field_types import default_registry


def _ft(name: str):
    ft = default_registry.get(name)
    assert ft is not None, f"未知字段类型: {name}"
    return ft


def test_number_min_violation():
    ft = _ft("number")
    with pytest.raises(ValueError):
        ft.validate_value(5, {"min": 10})


def test_number_max_violation():
    ft = _ft("number")
    with pytest.raises(ValueError):
        ft.validate_value(100, {"max": 50})


def test_number_none_passthrough():
    ft = _ft("number")
    assert ft.validate_value(None, {}) is None


def test_link_none_passthrough():
    ft = _ft("link")
    # LinkFieldType None → 空列表（空关联集合，语义正确）
    assert ft.validate_value(None, {}) == []


def test_link_invalid_int():
    ft = _ft("link")
    with pytest.raises(ValueError):
        ft.validate_value("not_an_int", {})


def test_select_option_not_in_list():
    ft = _ft("select")
    with pytest.raises(ValueError):
        ft.validate_value("xyz", {"options": ["a", "b"]})


def test_text_none_passthrough():
    ft = _ft("text")
    assert ft.validate_value(None, {}) is None


def test_number_none_passthrough_already():
    """NumberFieldType None passthrough (int 版本)."""
    ft = _ft("number")
    assert ft.validate_value(None, {}) is None


def test_float_none_passthrough():
    ft = _ft("float")
    assert ft.validate_value(None, {}) is None


def test_longtext_none_passthrough():
    ft = _ft("longtext")
    assert ft.validate_value(None, {}) is None


def test_multiselect_none_passthrough():
    ft = _ft("multiselect")
    assert ft.validate_value(None, {}) is None


def test_date_none_passthrough():
    ft = _ft("date")
    assert ft.validate_value(None, {}) is None


def test_datetime_none_passthrough():
    ft = _ft("datetime")
    assert ft.validate_value(None, {}) is None


def test_boolean_none_passthrough():
    ft = _ft("boolean")
    assert ft.validate_value(None, {}) is None


def test_registry_register_class():
    """register 直接传 class（而非实例）应自动实例化."""
    from cndb.plugins.tables.field_types import FieldTypeRegistry, TextFieldType

    reg = FieldTypeRegistry()
    reg.register(TextFieldType)
    assert reg.get("text") is not None


def test_number_int_min_violation():
    """NumberFieldType (int) 的 min 校验."""
    ft = _ft("number")
    with pytest.raises(ValueError):
        ft.validate_value(5, {"min": 10})


# ── 覆盖率补测 ──────────────────────────────────────────


def test_make_column_with_default():
    """FieldType.make_column(default=...) 分支 — L38."""
    ft = _ft("text")
    col = ft.make_column("name", default="hello")
    assert col.default is not None


def test_base_default_value_returns_none():
    """基类 FieldType.default_value 返回 None — L47."""
    ft = _ft("text")
    assert ft.default_value({}) is None


def test_float_min_violation():
    """DecimalFieldType (float) 的 min 校验 — L108."""
    ft = _ft("float")
    with pytest.raises(ValueError) as ei:
        ft.validate_value("0", {"min": 1.0})
    assert "小于最小值" in str(ei.value)


def test_select_field_config_non_empty_ok():
    """SelectFieldConfig._non_empty validator 返回值分支 — L168."""
    from cndb.plugins.tables.field_types import SelectFieldConfig

    cfg = SelectFieldConfig(options=["a", "b"])
    assert cfg.options == ["a", "b"]


def test_select_field_type_none_passthrough():
    """SelectFieldType.validate_value None passthrough — L182."""
    ft = _ft("select")
    assert ft.validate_value(None, {"options": ["a", "b"]}) is None
