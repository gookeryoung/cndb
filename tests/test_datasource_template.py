"""datasource M1：请求模板求值与配置校验单测."""

from __future__ import annotations

import pytest

from cndb.plugins.datasource.providers.base import (
    FieldTransform,
    PagingSpec,
    ProviderError,
    RequestSpec,
    SyncJobSpec,
    TimeWindowSpec,
)
from cndb.plugins.datasource.providers.template import render_text, render_value


class TestRenderText:
    def test_plain_text_untouched(self):
        assert render_text("https://api.example.com/v1/weather", {}) == "https://api.example.com/v1/weather"

    def test_single_placeholder(self):
        assert render_text("?city={city}", {"city": "北京"}) == "?city=北京"

    def test_repeated_placeholder(self):
        assert render_text("{a}-{a}", {"a": "x"}) == "x-x"

    def test_none_renders_empty(self):
        assert render_text("k={v}", {"v": None}) == "k="

    def test_bool_renders_lowercase(self):
        assert render_text("f={v}", {"v": True}) == "f=true"

    def test_number_renders_str(self):
        assert render_text("p={v}", {"v": 3}) == "p=3"

    def test_missing_variable_raises(self):
        with pytest.raises(ProviderError, match="模板变量缺失"):
            render_text("?city={city}", {})

    def test_unclosed_placeholder_raises(self):
        with pytest.raises(ProviderError, match="未闭合"):
            render_text("?city={city", {"city": "x"})

    def test_empty_placeholder_raises(self):
        with pytest.raises(ProviderError, match="空占位符"):
            render_text("a={}", {})

    def test_stray_closing_brace_raises(self):
        with pytest.raises(ProviderError, match="未转义的"):
            render_text("a=b}c", {})

    def test_escaped_braces(self):
        assert render_text("{{city}}", {"city": "上海"}) == "{city}"

    def test_escaped_brace_mixed_with_placeholder(self):
        assert render_text('{{"d":"{v}"}}', {"v": 1}) == '{"d":"1"}'


class TestRenderValue:
    def test_nested_mapping(self):
        out = render_value({"a": "{x}", "b": {"c": "{y}"}}, {"x": 1, "y": 2})
        assert out == {"a": "1", "b": {"c": "2"}}

    def test_list_and_tuple(self):
        out = render_value(["{x}", 3], {"x": "v"})
        assert out == ["v", 3]
        assert render_value(("{x}",), {"x": "v"}) == ("v",)

    def test_scalar_passthrough(self):
        assert render_value(42, {}) == 42
        assert render_value(None, {}) is None


class TestSpecValidation:
    def test_request_requires_url(self):
        with pytest.raises(ProviderError, match="url_template"):
            RequestSpec(url_template="")

    def test_request_requires_http_scheme(self):
        with pytest.raises(ProviderError, match="http/https"):
            RequestSpec(url_template="ftp://example.com/x")

    def test_paging_limits(self):
        with pytest.raises(ProviderError, match="max_pages"):
            PagingSpec(mode="page", max_pages=0)
        with pytest.raises(ProviderError, match="page_size"):
            PagingSpec(mode="page", page_size=0)

    def test_paging_none_skips_limits(self):
        assert PagingSpec().mode == "none"

    def test_time_window_requires_bounds(self):
        with pytest.raises(ProviderError, match="start 与 end"):
            TimeWindowSpec(mode="range", start="2024-01-01")

    def test_time_window_rejects_negative_chunk(self):
        with pytest.raises(ProviderError, match="不能为负"):
            TimeWindowSpec(mode="range", start="2024-01-01", end="2024-01-02", chunk_days=-1)

    def test_time_window_none_ignores_bounds(self):
        assert TimeWindowSpec().mode == "none"

    def test_field_transform_requires_name(self):
        with pytest.raises(ProviderError, match="目标字段名"):
            FieldTransform(name="")

    def test_entrant_values_require_param(self):
        with pytest.raises(ProviderError, match="entrant_param"):
            SyncJobSpec(request=RequestSpec(url_template="https://a.example.com"), entrant_values=("x",))

    def test_bare_job_is_valid(self):
        job = SyncJobSpec(request=RequestSpec(url_template="https://a.example.com"))
        assert job.provider == "http_json"
        assert job.match_keys == ()
