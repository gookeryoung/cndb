"""api_fetch 补全测试 —— SSRF DNS 解析分支、腾讯股票解析、handler 机制、query_interval."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx2
import pytest

from cndb.plugins.tables import api_fetch as af

# ── _is_private_or_reserved_ip DNS 解析分支 ─────────


class TestIsPrivateOrReservedIpDns:
    def test_dns_gaierror_returns_false(self):
        """DNS 解析失败不应误判为私有 IP。"""
        import socket

        with patch("socket.getaddrinfo", side_effect=socket.gaierror("DNS fail")):
            assert af._is_private_or_reserved_ip("unknown-host.invalid") is False

    def test_dns_returns_private_ip_blocked(self):
        """域名解析到私有 IP 应被拦截."""
        fake_infos = [(None, None, None, None, ("192.168.1.1", 0))]
        with patch("socket.getaddrinfo", return_value=fake_infos):
            assert af._is_private_or_reserved_ip("internal.local") is True

    def test_dns_ipv6_linklocal_blocked(self):
        fake_infos = [(None, None, None, None, ("fe80::1", 0, 0, 0))]
        with patch("socket.getaddrinfo", return_value=fake_infos):
            assert af._is_private_or_reserved_ip("ipv6-host.local") is True

    def test_dns_valid_public_not_blocked(self):
        fake_infos = [(None, None, None, None, ("8.8.8.8", 0))]
        with patch("socket.getaddrinfo", return_value=fake_infos):
            assert af._is_private_or_reserved_ip("dns.google") is False

    def test_dns_invalid_ip_skipped(self):
        """IP 解析失败应 continue 跳过."""
        fake_infos = [(None, None, None, None, ("not.an.ip", 0))]
        with patch("socket.getaddrinfo", return_value=fake_infos):
            assert af._is_private_or_reserved_ip("garbage.invalid") is False


# ── validate_url 域名解析到内网 ────────────────────


class TestValidateUrlDnsResolution:
    def test_domain_resolves_to_private_blocked(self):
        with (
            patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("10.0.0.1", 0))]),
            pytest.raises(ValueError, match="内网"),
        ):
            af.validate_url("http://internal.local/path")

    def test_localhost_variant_0_0_0_0(self):
        with pytest.raises(ValueError, match=r"0\.0\.0\.0"):
            af.validate_url("http://0.0.0.0/x")


# ── _resolve_path 更多边界 ──────────────────────────


class TestResolvePathEdgeCases:
    def test_empty_part_skipped(self):
        # "a..b" 中间空 part
        assert af._resolve_path({"a": {"b": 1}}, "a..b") == 1

    def test_part_on_non_dict_returns_none(self):
        assert af._resolve_path([1, 2], "0.x") is None

    def test_array_index_on_non_list_returns_none(self):
        assert af._resolve_path({"a": {"b": "not-a-list"}}, "a.b[0]") is None

    def test_array_index_out_of_range(self):
        assert af._resolve_path({"a": [1, 2]}, "a[5]") is None

    def test_non_numeric_index(self):
        assert af._resolve_path({"a": [1]}, "a[abc]") is None

    def test_nested_array_indices(self):
        payload = {"m": [[{"v": 42}]]}
        assert af._resolve_path(payload, "m[0][0].v") == 42


# ── _extract_array 更多边界 ─────────────────────────


class TestExtractArrayEdgeCases:
    def test_path_found_but_no_dict_rows(self):
        """data_path 命中 list 但 list 里全是 non-dict → 退化空数组."""
        payload = {"items": [1, 2, 3]}
        # data_path 命中 items 得到 list，但过滤后 rows 为空
        result = af._extract_array(payload, "items", True)
        # explicit_list_found=True 但 rows 为空 → 返回 []
        assert result == []

    def test_candidate_nested_deep_two_levels(self):
        """顶级非候选 key 的 dict 再下一层有候选 key."""
        payload = {"response": {"data": [{"id": 1}]}}
        assert af._extract_array(payload, None, True) == [{"id": 1}]

    def test_candidate_top_level_skip_seen(self):
        """第二轮顶级候选查找应跳过第一轮已处理的 key."""
        payload = {"result": {"items": [{"x": 1}]}}
        assert af._extract_array(payload, None, True) == [{"x": 1}]

    def test_not_dict_not_list_degenerate(self):
        """整个响应是字符串等非 dict/list → 返回 []."""
        assert af._extract_array("just text", None, True) == []


# ── _parse_tencent_stock ────────────────────────────


class TestParseTencentStock:
    def test_single_stock(self):
        text = (
            'v_sh600519="1~贵州茅台~600519~1277.96~1270.00~1275.00~'
            "500000~250000~250000~1277.90~100~1277.80~200~1277.70~300~"
            "1277.60~400~1277.50~500~1278.00~100~1278.10~200~1278.20~300~"
            "1278.30~400~1278.40~500~~20250914103000~7.96~0.63~1280.00~"
            "1260.00~1277.96/500000/638735~500000~63873.5~0.5~35.2~"
            '2000~1300~1.57~1.6~150000~200000~12.5"'
        )
        rows = af._parse_tencent_stock(text, af.FetchConfig(url="http://x"))
        assert len(rows) == 1
        row = rows[0]
        assert row["symbol"] == "sh600519"
        assert row["market"] == "SH"
        assert row["stock_name"] == "贵州茅台"
        assert row["stock_code"] == "600519"
        assert row["current_price"] == pytest.approx(1277.96)
        assert row["open_price"] == pytest.approx(1275.00)
        assert row["timestamp"] == "2025-09-14 10:30:00"
        assert row["high_price"] == pytest.approx(1280.00)
        assert row["low_price"] == pytest.approx(1260.00)
        assert row["pe_ratio"] == pytest.approx(35.2)

    def test_multiple_stocks(self):
        text = (
            'v_sh600519="1~贵州茅台~600519~1277.96~1270.00~1275.00~0~0~0~~20250914103000~~~~";'
            'v_sz000001="1~平安银行~000001~12.34~12.30~12.35~0~0~0~~20250914103000~~~~"'
        )
        rows = af._parse_tencent_stock(text, af.FetchConfig(url="http://x"))
        assert len(rows) == 2
        assert rows[0]["symbol"] == "sh600519"
        assert rows[1]["symbol"] == "sz000001"
        assert rows[1]["market"] == "SZ"

    def test_empty_values_skipped(self):
        """v_xxx=\"\" 空值应跳过."""
        text = 'v_sh600519="";v_sz000001="1~平安银行~000001~12.34~12.30~12.35~0~0~0~~20250914103000~~~~"'
        rows = af._parse_tencent_stock(text, af.FetchConfig(url="http://x"))
        assert len(rows) == 1

    def test_missing_fields_short_string(self):
        """field 数量不够时只填充已有."""
        text = 'v_sh600519="1~贵州茅台~600519~1277.96"'
        rows = af._parse_tencent_stock(text, af.FetchConfig(url="http://x"))
        assert len(rows) == 1
        assert rows[0]["stock_name"] == "贵州茅台"
        assert rows[0]["current_price"] == pytest.approx(1277.96)
        # 没提供的字段不应该有
        assert "timestamp" not in rows[0]

    def test_numeric_conversion_fail_keeps_original(self):
        """数值转换失败时保留原值."""
        text = 'v_sh600519="1~贵州茅台~600519~not_a_number"'
        rows = af._parse_tencent_stock(text, af.FetchConfig(url="http://x"))
        assert rows[0]["current_price"] == "not_a_number"

    def test_empty_value_becomes_none(self):
        """空字符串 → None."""
        text = 'v_sh600519="1~股票名~600519~100.00~50.00~~~20250914103000"'
        rows = af._parse_tencent_stock(text, af.FetchConfig(url="http://x"))
        # 空的 volume_lots (index 6) 应变成 None
        assert rows[0]["volume_lots"] is None

    def test_no_match_returns_empty(self):
        rows = af._parse_tencent_stock("garbage text no v_xxx pattern", af.FetchConfig(url="http://x"))
        assert rows == []

    def test_timestamp_short_format_kept_raw(self):
        """timestamp 不是 14 位时保留原值."""
        # timestamp 在 TENCENT_STOCK_FIELDS 的 index 30，需填充 0~29 共 30 个 part
        filler = "~" * 21  # index 9~29 = 21 个空字段
        text = f'v_sh600519="1~N~C~100~50~99~0~0~0{filler}~2025-09-14"'
        rows = af._parse_tencent_stock(text, af.FetchConfig(url="http://x"))
        assert rows[0]["timestamp"] == "2025-09-14"


# ── _get_response_handler ──────────────────────────


class TestGetResponseHandler:
    def test_json_returns_none(self):
        assert af._get_response_handler("json") is None

    def test_registered_name(self):
        h = af._get_response_handler("tencent_stock")
        assert h is af._parse_tencent_stock

    def test_callable_passthrough(self):
        def custom(text, cfg):
            return [{"raw": text}]

        assert af._get_response_handler(custom) is custom

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="未知的响应处理器"):
            af._get_response_handler("no_such_handler")


# ── fetch_json 更多 body 类型 / HTTP 错误 / 自定义 handler ─


def _make_client(status: int, body: bytes, content_type: str = "application/json", exc=None):
    resp = MagicMock()
    resp.status_code = status
    resp.content = body
    resp.text = body.decode("utf-8", errors="replace")
    resp.headers = {"content-type": content_type}

    client = MagicMock()
    if exc is not None:
        client.request.side_effect = exc
    else:
        client.request.return_value = resp
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


class TestFetchJsonMore:
    @patch("httpx2.Client")
    def test_str_body_adds_content_type(self, MockClient):
        mock_client = _make_client(200, json.dumps([{"ok": 1}]).encode())
        MockClient.return_value = mock_client

        af.fetch_json(af.FetchConfig(url="https://x.com", method="POST", body='{"query":"hi"}'))

        call_kwargs = mock_client.request.call_args.kwargs
        assert call_kwargs["content"] == '{"query":"hi"}'
        assert call_kwargs["json"] is None

    @patch("httpx2.Client")
    def test_bytes_body(self, MockClient):
        mock_client = _make_client(200, json.dumps([{"ok": 1}]).encode())
        MockClient.return_value = mock_client

        af.fetch_json(af.FetchConfig(url="https://x.com", body=b"raw bytes"))

        call_kwargs = mock_client.request.call_args.kwargs
        assert call_kwargs["content"] == b"raw bytes"

    def test_invalid_body_type(self):
        with pytest.raises(ValueError, match="body 必须是"):
            af.fetch_json(af.FetchConfig(url="https://x.com", body=123))

    def test_unsupported_http_method(self):
        with pytest.raises(ValueError, match="不支持的 HTTP 方法"):
            af.fetch_json(af.FetchConfig(url="https://x.com", method="PATCHX"))

    @patch("httpx2.Client")
    def test_httpx_too_many_redirects(self, MockClient):
        mock_client = _make_client(200, b"", exc=httpx2.TooManyRedirects("too many"))
        MockClient.return_value = mock_client

        with pytest.raises(ValueError, match="重定向次数过多"):
            af.fetch_json(af.FetchConfig(url="https://x.com"))

    @patch("httpx2.Client")
    def test_httpx_request_error(self, MockClient):
        mock_client = _make_client(200, b"", exc=httpx2.RequestError("timeout"))
        MockClient.return_value = mock_client

        with pytest.raises(ValueError, match="请求失败"):
            af.fetch_json(af.FetchConfig(url="https://x.com"))

    @patch("httpx2.Client")
    def test_custom_response_handler_callable(self, MockClient):
        raw = b"custom raw response"
        mock_client = _make_client(200, raw, content_type="text/plain")
        MockClient.return_value = mock_client

        def _my_handler(text, _cfg):
            return [{"parsed": text.upper()}]

        rows = af.fetch_json(af.FetchConfig(url="https://x.com", response_handler=_my_handler))
        assert rows == [{"parsed": "CUSTOM RAW RESPONSE"}]

    @patch("httpx2.Client")
    def test_tencent_stock_handler_integration(self, MockClient):
        raw = ('v_sh600519="1~贵州茅台~600519~1277.96~1270.00~1275.00~0~0~0~~20250914103000~~"').encode("gbk")
        mock_client = _make_client(200, raw, content_type="text/plain")
        MockClient.return_value = mock_client

        rows = af.fetch_json(
            af.FetchConfig(
                url="https://qt.gtimg.cn/q=sh600519",
                response_handler="tencent_stock",
                encoding="gbk",
            )
        )
        assert len(rows) == 1
        assert rows[0]["symbol"] == "sh600519"


# ── validate_query_interval ────────────────────────


class TestValidateQueryInterval:
    def test_none_returns_default(self):
        assert af.validate_query_interval(None) == af.DEFAULT_QUERY_INTERVAL

    def test_zero_returns_default(self):
        assert af.validate_query_interval(0) == af.DEFAULT_QUERY_INTERVAL

    def test_negative_returns_default(self):
        assert af.validate_query_interval(-5) == af.DEFAULT_QUERY_INTERVAL

    def test_below_min_clamped(self):
        assert af.validate_query_interval(3) == af.MIN_QUERY_INTERVAL
        assert af.validate_query_interval(5) == af.MIN_QUERY_INTERVAL

    def test_at_min_unchanged(self):
        assert af.validate_query_interval(af.MIN_QUERY_INTERVAL) == af.MIN_QUERY_INTERVAL

    def test_above_min_unchanged(self):
        assert af.validate_query_interval(60) == 60.0
        assert af.validate_query_interval(120) == 120.0

    def test_float_value(self):
        assert af.validate_query_interval(7.5) == 7.5

    def test_return_type_is_numeric(self):
        """validate_query_interval 返回数值类型；夹取到 MIN_QUERY_INTERVAL(int) 时返回 int."""
        r = af.validate_query_interval(10)
        assert r == 10.0
        r2 = af.validate_query_interval(3)
        assert r2 == af.MIN_QUERY_INTERVAL


__all__ = []
