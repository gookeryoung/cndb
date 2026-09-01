"""字段类型系统测试：注册表与全部内置类型."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from cndb.tables import field_types as ft_pkg
from cndb.tables.field_types import (
    InvalidFieldConfigError,
    InvalidFieldValueError,
    UnknownFieldTypeError,
    get_field_type,
    registered_types,
    registry,
)


def test_registry_contains_builtin_types() -> None:
    """内置九种类型全部注册."""
    names = registered_types()
    for name in (
        "text",
        "long_text",
        "number",
        "boolean",
        "date",
        "single_select",
        "multi_select",
        "email",
        "url",
    ):
        assert name in names


def test_get_unknown_type_raises() -> None:
    """未注册类型抛 UnknownFieldTypeError."""
    with pytest.raises(UnknownFieldTypeError, match="未注册"):
        get_field_type("nope")


def test_duplicate_register_rejected() -> None:
    """同名类型重复注册抛 ValueError."""
    with pytest.raises(ValueError, match="已注册"):
        registry.register(ft_pkg.BUILTIN_FIELD_TYPES[0])


def test_validate_value_none_passthrough() -> None:
    """空值 None 直接放行，不触发值校验."""
    assert get_field_type("text").validate_value(None, {}) is None


def test_validate_config_rejects_non_mapping() -> None:
    """config 非对象抛 InvalidFieldConfigError."""
    with pytest.raises(InvalidFieldConfigError, match="必须是对象"):
        get_field_type("text").validate_config([1, 2])  # type: ignore[arg-type]


def test_validate_config_none_returns_empty() -> None:
    """无配置类型（long_text）的 config 为 None 时归一化为空字典."""
    assert get_field_type("long_text").validate_config(None) == {}


# ---------- text ----------


def test_text_config_default() -> None:
    """text 默认 max_length 255."""
    assert get_field_type("text").validate_config({}) == {"max_length": 255}


def test_text_config_invalid() -> None:
    """text max_length 非法：越界与非整数."""
    ft = get_field_type("text")
    with pytest.raises(InvalidFieldConfigError):
        ft.validate_config({"max_length": 0})
    with pytest.raises(InvalidFieldConfigError):
        ft.validate_config({"max_length": "abc"})


def test_text_clean_value() -> None:
    """text：去空白、限长、类型校验、DDL 列类型."""
    ft = get_field_type("text")
    assert ft.clean_value("  hello  ", {"max_length": 255}) == "hello"
    assert ft.db_column_type({"max_length": 100}) == "varchar(100)"
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value("a" * 11, {"max_length": 10})
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value(123, {})


# ---------- long_text ----------


def test_long_text_clean_value() -> None:
    """long_text：接受任意字符串，DDL 为 text."""
    ft = get_field_type("long_text")
    assert ft.clean_value(" 长文本 ", {}) == "长文本"
    assert ft.db_column_type({}) == "text"
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value(123, {})


# ---------- number ----------


def test_number_config_default_and_invalid() -> None:
    """number：默认精度标度、scale 不得大于 precision."""
    ft = get_field_type("number")
    assert ft.validate_config({}) == {"precision": 10, "scale": 2}
    with pytest.raises(InvalidFieldConfigError):
        ft.validate_config({"precision": 3, "scale": 5})
    with pytest.raises(InvalidFieldConfigError):
        ft.validate_config({"precision": 99})


def test_number_clean_value() -> None:
    """number：四舍五入到标度、精度上限、拒绝布尔与字符串."""
    ft = get_field_type("number")
    config = {"precision": 5, "scale": 2}
    assert ft.clean_value(Decimal("3.14159"), config) == Decimal("3.14")
    assert ft.clean_value(3.6, {"precision": 5, "scale": 0}) == Decimal("4")
    assert ft.clean_value(42, config) == Decimal("42")
    # numeric 参数间不留空格：规避 Django SQLite 内省对含逗号空格类型的解析缺陷
    assert ft.db_column_type(config) == "numeric(5,2)"
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value(Decimal("123456"), config)
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value(True, config)
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value("12", config)
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value(float("nan"), config)


# ---------- boolean ----------


def test_boolean_clean_value() -> None:
    """boolean：bool 放行、0/1 归一化、其余拒绝."""
    ft = get_field_type("boolean")
    assert ft.clean_value(True, {}) is True
    assert ft.clean_value(1, {}) is True
    assert ft.clean_value(0, {}) is False
    assert ft.db_column_type({}) == "boolean"
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value(2, {})
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value("yes", {})


# ---------- date ----------


def test_date_clean_value() -> None:
    """date：实例、datetime、ISO 字符串均可，非法格式拒绝."""
    ft = get_field_type("date")
    assert ft.clean_value(date(2026, 1, 2), {}) == date(2026, 1, 2)
    assert ft.clean_value(datetime(2026, 1, 2, 12, 30), {}) == date(2026, 1, 2)
    assert ft.clean_value("2026-01-02", {}) == date(2026, 1, 2)
    assert ft.db_column_type({}) == "date"
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value("2026/01/02", {})
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value(5, {})


# ---------- select ----------


def test_single_select_config_and_value() -> None:
    """single_select：choices 校验与值域校验."""
    ft = get_field_type("single_select")
    config = {"choices": ["待处理", "进行中", "已完成"]}
    assert ft.validate_config(config) == config
    assert ft.clean_value("进行中", config) == "进行中"
    assert ft.db_column_type(config) == "varchar(255)"
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value("已取消", config)
    with pytest.raises(InvalidFieldConfigError):
        ft.validate_config({"choices": []})
    with pytest.raises(InvalidFieldConfigError):
        ft.validate_config({"choices": ["a", "a"]})
    with pytest.raises(InvalidFieldConfigError):
        ft.validate_config({"choices": ["a", 1]})
    with pytest.raises(InvalidFieldConfigError):
        ft.validate_config({"choices": [f"选项{i}" for i in range(201)]})


def test_multi_select_config_and_value() -> None:
    """multi_select：列表值域校验、去重保序、DDL 为 jsonb."""
    ft = get_field_type("multi_select")
    config = {"choices": ["红", "绿", "蓝"]}
    assert ft.clean_value(["蓝", "红", "蓝"], config) == ["蓝", "红"]
    assert ft.db_column_type(config) == "jsonb"
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value("红", config)
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value(["黄"], config)
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value([1], config)


# ---------- email / url ----------


def test_email_clean_value() -> None:
    """email：格式与长度校验."""
    ft = get_field_type("email")
    assert ft.clean_value("user@example.com", {}) == "user@example.com"
    assert ft.db_column_type({}) == "varchar(254)"
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value("not-an-email", {})
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value("a" * 250 + "@x.com", {})
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value(123, {})


def test_url_clean_value() -> None:
    """url：仅接受 http(s) 链接."""
    ft = get_field_type("url")
    assert ft.clean_value("https://example.com/a", {}) == "https://example.com/a"
    assert ft.clean_value("http://example.com", {}) == "http://example.com"
    assert ft.db_column_type({}) == "varchar(2000)"
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value("ftp://example.com", {})
    with pytest.raises(InvalidFieldValueError):
        ft.clean_value("example.com", {})
