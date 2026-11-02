"""Coverage: field_types edge cases - email/url/phone empty string, link validation, timestamp/percentage non-numeric."""

from __future__ import annotations

import pytest

from cndb.plugins.tables.field_types import (
    EmailFieldType,
    LinkFieldType,
    PercentageFieldType,
    PhoneFieldType,
    TimestampFieldType,
    UrlFieldType,
    default_registry,
)


def _ft(name):
    ft = default_registry.get(name)
    assert ft is not None
    return ft


class TestBaseParseQueryValue:
    def test_base_default_passthrough(self):
        ft = _ft("text")
        assert ft.parse_query_value("hello", {}) == "hello"
        assert ft.parse_query_value(42, {}) == 42


class TestEmailEmptyString:
    def test_email_empty_string_returns_none(self):
        ft = EmailFieldType()
        assert ft.validate_value("   ", {}) is None


class TestUrlEmptyString:
    def test_url_empty_string_returns_none(self):
        ft = UrlFieldType()
        assert ft.validate_value("  ", {}) is None


class TestUrlValidation:
    """URL 校验只卡协议 / 主机，路径与查询按 RFC 3986 放行（采集落表回归）."""

    def test_accepts_real_world_paths_and_queries(self):
        ft = UrlFieldType()
        for text in (
            "http://thesis.lib.nccu.edu.tw/cgi-bin/cdrfb3/gsweb.cgi?o=dstdcdr&amp;i=sid=%22B2002001367%22.",
            "https://example.com/a;b:c~d@e,f(g)/h?x=1&y=%20z",
            "https://例子.测试/路径/文件?q=中文",
        ):
            assert ft.validate_value(text, {}) == text

    def test_rejects_non_http_and_missing_host(self):
        ft = UrlFieldType()
        for text in ("ftp://example.com/x", "javascript:alert(1)", "http://", "//example.com/x"):
            with pytest.raises(ValueError, match="URL 格式无效"):
                ft.validate_value(text, {})

    def test_rejects_whitespace_and_control_chars(self):
        ft = UrlFieldType()
        with pytest.raises(ValueError, match="URL 格式无效"):
            ft.validate_value("https://example.com/a b", {})


class TestPhoneEmptyString:
    def test_phone_empty_string_returns_none(self):
        ft = PhoneFieldType()
        assert ft.validate_value(" ", {}) is None


class TestPercentageNonNumeric:
    def test_percentage_non_numeric_raises(self):
        ft = PercentageFieldType()
        with pytest.raises(ValueError):
            ft.validate_value("abc", {})


class TestTimestampNonInteger:
    def test_timestamp_non_integer_raises(self):
        ft = TimestampFieldType()
        with pytest.raises(ValueError):
            ft.validate_value("abc", {})


class TestLinkMakeColumnRaises:
    def test_link_make_column_raises_runtime_error(self):
        ft = LinkFieldType()
        with pytest.raises(RuntimeError):
            ft.make_column("link_col")


class TestLinkValidateValueEdgeCases:
    def test_link_bool_item_rejected(self):
        ft = LinkFieldType()
        with pytest.raises(ValueError):
            ft.validate_value([1, True], {})

    def test_link_non_int_item_rejected(self):
        ft = LinkFieldType()
        with pytest.raises(ValueError):
            ft.validate_value([1, "abc"], {})

    def test_link_zero_rejected(self):
        ft = LinkFieldType()
        with pytest.raises(ValueError):
            ft.validate_value([1, 0], {})

    def test_link_negative_rejected(self):
        ft = LinkFieldType()
        with pytest.raises(ValueError):
            ft.validate_value([1, -1], {})

    def test_link_valid_deduplicates(self):
        ft = LinkFieldType()
        result = ft.validate_value([1, 2, 1, 3], {})
        assert result == [1, 2, 3]


class TestLinkParseQueryValue:
    def test_parse_non_string_passthrough(self):
        ft = LinkFieldType()
        assert ft.parse_query_value([1, 2], {}) == [1, 2]

    def test_parse_empty_string_returns_empty_list(self):
        ft = LinkFieldType()
        assert ft.parse_query_value("  ", {}) == []

    def test_parse_semicolon_string(self):
        ft = LinkFieldType()
        assert ft.parse_query_value("1;2;3", {}) == [1, 2, 3]

    def test_parse_invalid_format_raises(self):
        ft = LinkFieldType()
        with pytest.raises(ValueError):
            ft.parse_query_value("a;b", {})
