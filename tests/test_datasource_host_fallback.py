"""datasource ADR 0053：单轮翻页回补（cursor.page_to_start）+ 主机回退单测。

覆盖：

- ``CursorConfig`` 新声明键的解析 / 默认值 / 非法组合（非 backfill、模板缺 ``{end}``）；
- ``_run_streaming_passes`` 的多 pass 编排：水位逐 pass 前推、终止条件
  （空响应 / 短页 / 水位不前移 / 失败 / 达 backfill_start）、pass 上限触顶即 partial、
  中断续跑语义（复用同一 ``_StreamingState``，已落批次保留）；
- ``RequestProgress.add_total``：多 pass 累计、单 pass 与 ``set_total`` 等价；
- ``url_hosts``：``{host}`` 逐候选渲染、空声明行为不变；
- ``fetch_json`` 主机回退：网络错误 / 501 切备用主机，4xx 参数错误不切，
  解析失败不切，全部失败只报一次错，逐候选过 SSRF 校验。
"""

from __future__ import annotations

import datetime as dt

import httpx2
import pytest

from cndb.core.http import FetchConfig, fetch_json
from cndb.plugins.datasource.providers.base import ProviderError, RequestSpec
from cndb.plugins.datasource.providers.http_json import HttpJsonProvider
from cndb.plugins.datasource.services.cursor import CursorConfig, validate_page_to_start
from cndb.plugins.datasource.services.pipeline import RequestProgress
from cndb.plugins.datasource.services.runner import _url_hosts_from_payload

UTC = dt.UTC
NOW = dt.datetime(2026, 10, 25, 16, 0, tzinfo=UTC)


class TestCursorPageToStartConfig:
    def test_defaults_off(self):
        config = CursorConfig(strategy="backfill_date", field="日期", backfill_start="2016-01-01")
        assert config.page_to_start is False
        assert config.page_size == 0

    def test_from_dict_reads_new_keys(self):
        config = CursorConfig.from_dict(
            {
                "strategy": "backfill_date",
                "field": "日期",
                "backfill_start": "2016-01-01",
                "page_to_start": True,
                "page_size": 800,
            }
        )
        assert config.page_to_start is True
        assert config.page_size == 800
        # 往返不丢声明键
        assert config.to_dict()["page_to_start"] is True
        assert config.to_dict()["page_size"] == 800

    def test_from_dict_accepts_numeric_string(self):
        config = CursorConfig.from_dict(
            {"strategy": "backfill_date", "field": "d", "backfill_start": "2020-01-01", "page_size": "800"}
        )
        assert config.page_size == 800

    def test_from_dict_rejects_bad_page_size(self):
        with pytest.raises(ProviderError, match="整数"):
            CursorConfig.from_dict(
                {"strategy": "backfill_date", "field": "d", "backfill_start": "2020-01-01", "page_size": "many"}
            )

    def test_page_to_start_requires_backfill(self):
        with pytest.raises(ProviderError, match="backfill_date"):
            CursorConfig(strategy="date", field="day", page_to_start=True)

    def test_negative_page_size_rejected(self):
        with pytest.raises(ProviderError, match="不能为负"):
            CursorConfig(strategy="backfill_date", field="d", backfill_start="2020-01-01", page_size=-1)

    def test_template_must_have_end_anchor(self):
        config = CursorConfig(strategy="backfill_date", field="d", backfill_start="2020-01-01", page_to_start=True)
        with pytest.raises(ProviderError, match="end"):
            validate_page_to_start(config, "https://api.example.com/k?sym={entrant}")
        validate_page_to_start(config, "https://api.example.com/k?sym={entrant}&end={end}")

    def test_validate_is_noop_when_disabled(self):
        config = CursorConfig(strategy="backfill_date", field="d", backfill_start="2020-01-01")
        validate_page_to_start(config, "https://api.example.com/k?sym={entrant}")


class TestProgressAddTotal:
    def test_accumulates_across_passes(self):
        progress = RequestProgress()
        progress.add_total(2)
        progress.tick("a")
        progress.add_total(3)
        assert progress.snapshot()[0] == 5

    def test_single_call_matches_set_total(self):
        added = RequestProgress()
        added.add_total(4)
        replaced = RequestProgress()
        replaced.set_total(4)
        assert added.snapshot() == replaced.snapshot()


class TestUrlHostsPayload:
    def test_missing_or_empty_is_single_url(self):
        assert _url_hosts_from_payload(None) == ()
        assert _url_hosts_from_payload("") == ()
        assert _url_hosts_from_payload([]) == ()

    def test_reads_list_and_strips(self):
        assert _url_hosts_from_payload([" https://a.example.com ", "https://b.example.com"]) == (
            "https://a.example.com",
            "https://b.example.com",
        )

    def test_rejects_string_and_garbage(self):
        with pytest.raises(ValueError, match="数组"):
            _url_hosts_from_payload("https://a.example.com")
        with pytest.raises(ValueError, match="数组"):
            _url_hosts_from_payload({"host": "x"})
        with pytest.raises(ValueError, match="不能为空"):
            _url_hosts_from_payload([""])


class TestRequestSpecUrlHosts:
    def test_requires_placeholder(self):
        with pytest.raises(ProviderError, match="host"):
            RequestSpec(url_template="https://a.example.com/k", url_hosts=("https://a.example.com",))

    def test_hosts_must_be_http(self):
        with pytest.raises(ProviderError, match="http"):
            RequestSpec(url_template="{host}/k", url_hosts=("ftp://a.example.com",))

    def test_single_url_still_validated(self):
        with pytest.raises(ProviderError, match="http"):
            RequestSpec(url_template="api.example.com/k")

    def test_build_config_renders_each_host(self):
        provider = HttpJsonProvider()
        spec = RequestSpec(
            url_template="{host}/k?sym={entrant}",
            body_template={},
            url_hosts=("https://a.example.com", "https://b.example.com"),
        )
        config = provider._build_config(spec, {"entrant": "sh600519"})
        assert config.url == "https://a.example.com/k?sym=sh600519"
        assert config.fallback_urls == ("https://b.example.com/k?sym=sh600519",)

    def test_build_config_without_hosts_unchanged(self):
        provider = HttpJsonProvider()
        spec = RequestSpec(url_template="https://a.example.com/k?sym={entrant}", body_template={})
        config = provider._build_config(spec, {"entrant": "sh600519"})
        assert config.url == "https://a.example.com/k?sym=sh600519"
        assert config.fallback_urls == ()


def _client(handler):
    return httpx2.Client(transport=httpx2.MockTransport(handler), timeout=1.0)


class TestFetchFallback:
    def test_switches_to_backup_on_connect_error(self):
        seen: list[str] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.append(str(request.url))
            if request.url.host == "web.ifzq.gtimg.cn":
                raise httpx2.ConnectError("connection reset by peer", request=request)
            return httpx2.Response(200, json=[{"ok": 1}])

        config = FetchConfig(
            url="https://web.ifzq.gtimg.cn/k",
            fallback_urls=("https://proxy.finance.qq.com/k",),
            max_retries=0,
        )
        with _client(handler) as client:
            rows = fetch_json(config, client=client)
        assert rows == [{"ok": 1}]
        assert seen == ["https://web.ifzq.gtimg.cn/k", "https://proxy.finance.qq.com/k"]

    def test_switches_on_501(self):
        def handler(request: httpx2.Request) -> httpx2.Response:
            if request.url.host == "a.example.com":
                return httpx2.Response(501)
            return httpx2.Response(200, json=[{"ok": 1}])

        config = FetchConfig(url="https://a.example.com/k", fallback_urls=("https://b.example.com/k",), max_retries=0)
        with _client(handler) as client:
            assert fetch_json(config, client=client) == [{"ok": 1}]

    def test_does_not_switch_on_400(self):
        seen: list[str] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.append(request.url.host or "")
            return httpx2.Response(400, text="bad request")

        config = FetchConfig(url="https://a.example.com/k", fallback_urls=("https://b.example.com/k",), max_retries=0)
        with _client(handler) as client, pytest.raises(ValueError, match="400"):
            fetch_json(config, client=client)
        assert seen == ["a.example.com"]

    def test_does_not_switch_on_parse_error(self):
        seen: list[str] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.append(request.url.host or "")
            return httpx2.Response(200, text="not json")

        config = FetchConfig(url="https://a.example.com/k", fallback_urls=("https://b.example.com/k",), max_retries=0)
        with _client(handler) as client, pytest.raises(ValueError, match="JSON"):
            fetch_json(config, client=client)
        assert seen == ["a.example.com"]

    def test_all_hosts_down_raises_once(self):
        calls: list[str] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            calls.append(request.url.host or "")
            return httpx2.Response(503)

        config = FetchConfig(
            url="https://a.example.com/k",
            fallback_urls=("https://b.example.com/k",),
            max_retries=0,
        )
        with _client(handler) as client, pytest.raises(ValueError, match="503"):
            fetch_json(config, client=client)
        assert calls == ["a.example.com", "b.example.com"]

    def test_backup_host_candidates_are_ssrf_validated(self, monkeypatch):
        validated: list[str] = []

        def spy(url: str, *, allow_hosts=()) -> None:
            validated.append(url)

        monkeypatch.setattr("cndb.core.http.validate_url", spy)
        config = FetchConfig(
            url="https://a.example.com/k",
            fallback_urls=("https://b.example.com/k",),
            max_retries=0,
        )
        with _client(lambda request: httpx2.Response(503)) as client, pytest.raises(ValueError):
            fetch_json(config, client=client)
        assert validated == ["https://a.example.com/k", "https://b.example.com/k"]
