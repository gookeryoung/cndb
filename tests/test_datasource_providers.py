"""datasource M3：内置 provider（tencent_kline / rss_atom）解析单测."""

from __future__ import annotations

import json

import pytest

from cndb.plugins.datasource.providers.base import ProviderError, RequestSpec, SyncJobSpec
from cndb.plugins.datasource.providers.registry import PROVIDERS, get_provider, list_providers
from cndb.plugins.datasource.providers.rss_atom import RssAtomProvider
from cndb.plugins.datasource.providers.tencent_kline import (
    TENCENT_KLINE_URL_TEMPLATE,
    TencentKlineProvider,
)

KLINE = TencentKlineProvider()
RSS = RssAtomProvider()


def _job(provider: str = "http_json") -> SyncJobSpec:
    return SyncJobSpec(request=RequestSpec(url_template="https://api.example.com/x"), provider=provider)


class TestTencentKline:
    def test_parses_qfqday(self):
        payload = {
            "code": 0,
            "data": {
                "sh600519": {
                    "qfqday": [
                        ["2024-01-02", "1680.000", "1700.000", "1710.000", "1670.000", "30000"],
                        ["2024-01-03", "1700.000", "1690.000", "1720.000", "1680.000", "28000"],
                    ]
                }
            },
        }
        rows = KLINE.parse(json.dumps(payload), _job("tencent_kline"))
        assert len(rows) == 2
        # volume 由「手」换算成「股」（×100），与新浪同表口径一致
        assert rows[0] == {
            "symbol": "sh600519",
            "trade_date": "2024-01-02",
            "open": "1680.000",
            "close": "1700.000",
            "high": "1710.000",
            "low": "1670.000",
            "volume": 3000000,
        }

    def test_falls_back_to_other_series_keys(self):
        for key in ("hfqday", "day"):
            payload = {"code": 0, "data": {"sz000001": {key: [["2024-02-01", "10", "11", "12", "9", "100"]]}}}
            rows = KLINE.parse(json.dumps(payload), _job("tencent_kline"))
            assert rows[0]["trade_date"] == "2024-02-01"

    def test_skips_short_items(self):
        payload = {
            "code": 0,
            "data": {"sh600519": {"qfqday": [["2024-01-02", "1"], ["2024-01-03", "1", "2", "3", "4"]]}},
        }
        rows = KLINE.parse(json.dumps(payload), _job("tencent_kline"))
        assert len(rows) == 1
        assert rows[0]["trade_date"] == "2024-01-03"
        assert rows[0]["volume"] is None

    def test_empty_data(self):
        assert KLINE.parse('{"code": 0, "data": {}}', _job("tencent_kline")) == []
        assert KLINE.parse('{"code": 0}', _job("tencent_kline")) == []
        assert KLINE.parse('{"code": 0, "data": {"x": "not-a-dict"}}', _job("tencent_kline")) == []

    def test_error_code_raises(self):
        with pytest.raises(ProviderError, match="错误码"):
            KLINE.parse('{"code": 1, "msg": "bad symbol"}', _job("tencent_kline"))

    def test_invalid_json_raises(self):
        with pytest.raises(ProviderError, match="不是合法 JSON"):
            KLINE.parse("<html>", _job("tencent_kline"))
        with pytest.raises(ProviderError, match="顶层必须是对象"):
            KLINE.parse("[]", _job("tencent_kline"))

    def test_default_normalize_types(self):
        rows = [
            {
                "symbol": "sh600519",
                "trade_date": "2024/01/02",
                "open": "1680.5",
                "close": "1700",
                "high": "1710",
                "low": "1670",
                "volume": "30000",
            }
        ]
        result = KLINE.normalize(rows, _job("tencent_kline"))
        assert result.rows[0]["trade_date"] == "2024-01-02"
        assert result.rows[0]["open"] == 1680.5
        assert result.rows[0]["volume"] == 30000
        assert result.failed == 0

    def test_explicit_mapping_wins(self):
        job = SyncJobSpec(
            request=RequestSpec(url_template="https://api.example.com/x"),
            provider="tencent_kline",
            field_mapping={"close": {"name": "收盘价", "field_type": "text"}},
        )
        rows = [{"symbol": "sh600519", "trade_date": "2024-01-02", "close": "1700"}]
        result = KLINE.normalize(rows, job)
        assert result.rows[0]["收盘价"] == "1700"
        # 未映射字段按原名保留
        assert result.rows[0]["symbol"] == "sh600519"

    def test_default_url_template_shape(self):
        assert "{symbol}" in TENCENT_KLINE_URL_TEMPLATE
        assert "{start}" in TENCENT_KLINE_URL_TEMPLATE
        assert TENCENT_KLINE_URL_TEMPLATE.endswith("qfq")


RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>示例科技新闻</title>
    <item>
      <title>第一条</title>
      <link>https://example.com/news/1</link>
      <description>摘要一</description>
      <pubDate>Tue, 02 Jan 2024 08:30:00 +0800</pubDate>
    </item>
    <item>
      <title>第二条</title>
      <link>https://example.com/news/2</link>
      <pubDate>Wed, 03 Jan 2024 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom 示例源</title>
  <entry>
    <title type="html">原子条目</title>
    <link rel="alternate" href="https://example.org/posts/1"/>
    <link rel="edit" href="https://example.org/edit/1"/>
    <summary>摘要</summary>
    <updated>2024-01-04T10:15:00Z</updated>
  </entry>
</feed>
"""


class TestRssAtom:
    def test_parses_rss(self):
        rows = RSS.parse(RSS_SAMPLE, _job("rss_atom"))
        assert len(rows) == 2
        assert rows[0] == {
            "title": "第一条",
            "link": "https://example.com/news/1",
            "summary": "摘要一",
            "published_at": "2024-01-02 08:30:00",
            "source": "示例科技新闻",
        }
        assert rows[1]["summary"] == ""
        assert rows[1]["published_at"] == "2024-01-03 09:00:00"

    def test_parses_atom_with_namespace(self):
        rows = RSS.parse(ATOM_SAMPLE, _job("rss_atom"))
        assert len(rows) == 1
        assert rows[0]["title"] == "原子条目"
        assert rows[0]["link"] == "https://example.org/posts/1"
        assert rows[0]["summary"] == "摘要"
        assert rows[0]["published_at"] == "2024-01-04 10:15:00"
        assert rows[0]["source"] == "Atom 示例源"

    def test_invalid_xml_raises(self):
        with pytest.raises(ProviderError, match="不是合法 XML"):
            RSS.parse("<rss><channel>", _job("rss_atom"))

    def test_empty_feed(self):
        assert RSS.parse("<rss><channel><title>空</title></channel></rss>", _job("rss_atom")) == []

    def test_missing_time_left_blank(self):
        sample = (
            "<rss><channel><title>S</title><item><title>T</title>"
            "<link>https://e.com/1</link><pubDate>not-a-date</pubDate></item></channel></rss>"
        )
        rows = RSS.parse(sample, _job("rss_atom"))
        assert rows[0]["published_at"] == ""

    def test_iso_without_seconds(self):
        sample = (
            "<rss><channel><title>S</title><item><title>T</title>"
            "<pubDate>2024-01-05T06:00</pubDate></item></channel></rss>"
        )
        rows = RSS.parse(sample, _job("rss_atom"))
        assert rows[0]["published_at"] == "2024-01-05 06:00:00"


class TestRegistryM3:
    def test_three_builtins(self):
        assert {"http_json", "tencent_kline", "rss_atom"} <= set(PROVIDERS)

    def test_default_cursor_per_provider(self):
        assert get_provider("tencent_kline").default_cursor == "date"
        assert get_provider("rss_atom").default_cursor == "datetime"
        assert get_provider("http_json").default_cursor == "date"

    def test_list_contains_kline_template(self):
        entries = {item["name"]: item for item in list_providers()}
        assert entries["tencent_kline"]["supports_paging"] is False
        assert entries["rss_atom"]["supports_paging"] is False
        assert "fields" in entries["rss_atom"]["params_schema"]
