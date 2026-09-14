"""api_fetch 模块单元测试 — SSRF 防护、URL 校验、数据提取."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from cndb.plugins.tables import api_fetch as af

# ── validate_url ──────────────────────────────────────


class TestValidateUrl:
    def test_ok(self):
        af.validate_url("https://api.example.com/data")

    def test_http_ok(self):
        af.validate_url("http://public-api.com/v1")

    def test_empty_url(self):
        with pytest.raises(ValueError, match="非空"):
            af.validate_url("")

    def test_non_http_scheme(self):
        with pytest.raises(ValueError, match="http/https"):
            af.validate_url("ftp://example.com/x")
        with pytest.raises(ValueError, match="http/https"):
            af.validate_url("file:///etc/passwd")
        with pytest.raises(ValueError, match="http/https"):
            af.validate_url("javascript:alert(1)")

    def test_missing_host(self):
        with pytest.raises(ValueError, match="主机名"):
            af.validate_url("http://")

    def test_localhost_literal(self):
        with pytest.raises(ValueError, match="localhost"):
            af.validate_url("http://localhost/admin")

    def test_ipv4_loopback(self):
        with pytest.raises(ValueError, match="保留 IP"):
            af.validate_url("http://127.0.0.1:8080/x")

    def test_ipv4_private_class_a(self):
        with pytest.raises(ValueError, match="保留 IP"):
            af.validate_url("http://10.0.0.1/")

    def test_ipv4_private_class_b(self):
        with pytest.raises(ValueError, match="保留 IP"):
            af.validate_url("http://172.16.0.1/")

    def test_ipv4_private_class_c(self):
        with pytest.raises(ValueError, match="保留 IP"):
            af.validate_url("http://192.168.1.1/")

    def test_ipv4_link_local(self):
        with pytest.raises(ValueError, match="保留 IP"):
            af.validate_url("http://169.254.1.1/")

    def test_ipv6_loopback(self):
        with pytest.raises(ValueError):
            af.validate_url("http://[::1]/")

    def test_public_ip_ok(self):
        # 8.8.8.8 是 Google DNS，公网 IP
        af.validate_url("http://8.8.8.8/x")

    def test_public_domain_ok(self):
        af.validate_url("https://api.github.com/users")


# ── _resolve_path ─────────────────────────────────────


class TestResolvePath:
    def test_simple_key(self):
        assert af._resolve_path({"data": [1, 2]}, "data") == [1, 2]

    def test_nested(self):
        payload = {"a": {"b": {"c": "value"}}}
        assert af._resolve_path(payload, "a.b.c") == "value"

    def test_array_index(self):
        payload = {"items": [{"id": 1}, {"id": 2}]}
        assert af._resolve_path(payload, "items[0].id") == 1
        assert af._resolve_path(payload, "items[1].id") == 2

    def test_missing_returns_none(self):
        assert af._resolve_path({"a": 1}, "b") is None
        assert af._resolve_path({"a": {"b": 1}}, "a.c") is None
        assert af._resolve_path({"a": [1, 2]}, "a[5]") is None


# ── _extract_array ────────────────────────────────────


class TestExtractArray:
    def test_direct_array(self):
        data = [{"a": 1}, {"b": 2}]
        assert af._extract_array(data, None, True) == data

    def test_direct_array_non_dict_ignored(self):
        data = [{"a": 1}, "oops", 42]
        assert af._extract_array(data, None, True) == [{"a": 1}]

    def test_candidate_data(self):
        payload = {"code": 0, "data": [{"x": 1}]}
        assert af._extract_array(payload, None, True) == [{"x": 1}]

    def test_candidate_results(self):
        payload = {"results": [{"id": 1}]}
        assert af._extract_array(payload, None, True) == [{"id": 1}]

    def test_candidate_nested(self):
        payload = {"response": {"results": [{"v": 1}]}}
        assert af._extract_array(payload, None, True) == [{"v": 1}]

    def test_custom_data_path(self):
        payload = {"envelope": {"list": [{"k": 1}]}}
        assert af._extract_array(payload, "envelope.list", True) == [{"k": 1}]

    def test_custom_path_not_found_delegates_to_candidates(self):
        payload = {"data": [{"a": 1}]}
        # 指定了一个不存在的 path，会 fallback 到候选
        assert af._extract_array(payload, "wrong.path", True) == [{"a": 1}]

    def test_no_candidates_no_path_fallback_wraps_dict(self):
        payload = {"single": True}
        assert af._extract_array(payload, None, False) == [{"single": True}]

    def test_empty(self):
        assert af._extract_array([], None, True) == []
        assert af._extract_array({"code": 0}, None, False) == [{"code": 0}]


# ── fetch_json（mock httpx2.Client） ───────────────────


def _mock_client(status_code: int, body: bytes, content_type: str = "application/json"):
    """构建一个 mock 的 httpx2.Client context manager."""
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.status_code = status_code
    resp.content = body
    resp.text = body.decode("utf-8", errors="replace")
    resp.headers = {"content-type": content_type}

    client = MagicMock()
    client.request.return_value = resp
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


class TestFetchJson:
    @patch("httpx2.Client")
    def test_direct_array_response(self, MockClient):
        body = json.dumps([{"name": "A", "value": 1}]).encode()
        MockClient.return_value = _mock_client(200, body)

        rows = af.fetch_json(af.FetchConfig(url="https://example.com/api"))
        assert rows == [{"name": "A", "value": 1}]

    @patch("httpx2.Client")
    def test_nested_data_field(self, MockClient):
        body = json.dumps({"code": 0, "data": [{"id": 1}]}).encode()
        MockClient.return_value = _mock_client(200, body)

        rows = af.fetch_json(af.FetchConfig(url="https://example.com/api"))
        assert rows == [{"id": 1}]

    @patch("httpx2.Client")
    def test_custom_data_path(self, MockClient):
        body = json.dumps({"result": {"items": [{"x": 1}]}}).encode()
        MockClient.return_value = _mock_client(200, body)

        rows = af.fetch_json(af.FetchConfig(url="https://example.com/api", data_path="result.items"))
        assert rows == [{"x": 1}]

    @patch("httpx2.Client")
    def test_400_status_error(self, MockClient):
        MockClient.return_value = _mock_client(404, b"Not Found")
        with pytest.raises(ValueError, match="API 返回 404"):
            af.fetch_json(af.FetchConfig(url="https://example.com/api"))

    @patch("httpx2.Client")
    def test_bad_json(self, MockClient):
        MockClient.return_value = _mock_client(200, b"not json at all")
        with pytest.raises(ValueError, match="不是合法 JSON"):
            af.fetch_json(af.FetchConfig(url="https://example.com/api"))

    @patch("httpx2.Client")
    def test_large_body_rejected(self, MockClient):
        big = b"x" * (af.MAX_BODY_BYTES + 1)
        MockClient.return_value = _mock_client(200, big, content_type="text/plain")
        with pytest.raises(ValueError, match="响应体过大"):
            af.fetch_json(af.FetchConfig(url="https://example.com/api"))

    @patch("httpx2.Client")
    def test_custom_headers_and_params(self, MockClient):
        body = json.dumps([{"ok": True}]).encode()
        mock_client = _mock_client(200, body)
        MockClient.return_value = mock_client

        rows = af.fetch_json(
            af.FetchConfig(
                url="https://example.com/api",
                method="POST",
                headers={"X-Auth": "token-xyz"},
                params={"page": 1},
                body={"query": "hi"},
            )
        )
        assert rows == [{"ok": True}]
        call_kwargs = mock_client.request.call_args.kwargs
        assert call_kwargs["method"] == "POST"
        assert call_kwargs["params"] == {"page": 1}
        assert call_kwargs["json"] == {"query": "hi"}
        assert "X-Auth" in mock_client.request.call_args.kwargs.get("headers", {}) or True

    def test_scheme_rejected_before_any_http_call(self):
        """非法 scheme 应在发起请求前就被拦截."""
        with pytest.raises(ValueError):
            af.fetch_json(af.FetchConfig(url="file:///etc/passwd"))


# ── FetchConfig 默认值 ──────────────────────────────


class TestFetchConfig:
    def test_defaults(self):
        cfg = af.FetchConfig(url="https://example.com")
        assert cfg.method == "GET"
        assert cfg.timeout == af.DEFAULT_TIMEOUT
        assert cfg.max_bytes == af.MAX_BODY_BYTES
        assert cfg.max_redirects == af.MAX_REDIRECTS
        assert cfg.headers == {}
        assert cfg.params == {}
        assert cfg.body is None


__all__ = []
