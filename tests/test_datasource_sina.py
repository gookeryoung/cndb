"""datasource：``sina_kline`` provider 与管线补标的单测（不联网）.

覆盖：
- 新浪平铺数组解析、字段改名、空值剔除、非法响应报错
- ``uses_custom_parse`` → ``response_handler`` 注入（否则 fetch_json 的通用数组探测会解析错）
- 管线：响应不带标的时按 entrant 补齐
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from cndb.plugins.datasource.providers.base import (
    ProviderError,
    RequestSpec,
    SyncJobSpec,
)
from cndb.plugins.datasource.providers.sina_kline import SinaKlineProvider
from cndb.plugins.datasource.services.pipeline import fill_entrant

SINA = SinaKlineProvider()


def _job(provider: str, url: str, **kwargs: Any) -> SyncJobSpec:
    return SyncJobSpec(request=RequestSpec(url_template=url), provider=provider, **kwargs)


class TestSinaKline:
    def test_parses_flat_array(self):
        payload = json.dumps(
            [
                {
                    "day": "2026-10-16",
                    "open": "1311.57",
                    "high": "1329.88",
                    "low": "1301.68",
                    "close": "1329.00",
                    "volume": "3850175",
                },
                {
                    "day": "2026-10-19",
                    "open": "1322.50",
                    "high": "1348.60",
                    "low": "1321.00",
                    "close": "1324.97",
                    "volume": "3972894",
                },
            ]
        )
        rows = SINA.parse(payload, _job("sina_kline", "https://example/x"))
        assert len(rows) == 2
        assert rows[0] == {
            "trade_date": "2026-10-16",
            "open": "1311.57",
            "high": "1329.88",
            "low": "1301.68",
            "close": "1329.00",
            "volume": "3850175",
        }

    def test_drops_rows_without_day(self):
        payload = json.dumps([{"open": "1"}, {"day": "", "open": "2"}, {"day": "2026-10-19", "close": "9"}])
        rows = SINA.parse(payload, _job("sina_kline", "https://example/x"))
        assert [r["trade_date"] for r in rows] == ["2026-10-19"]

    def test_rejects_non_array_payload(self):
        with pytest.raises(ProviderError):
            SINA.parse(json.dumps({"data": []}), _job("sina_kline", "https://example/x"))
        with pytest.raises(ProviderError):
            SINA.parse("<html>waf</html>", _job("sina_kline", "https://example/x"))

    def test_default_normalize_types(self):
        job = SyncJobSpec(request=RequestSpec(url_template="https://example/x"), provider="sina_kline")
        result = SINA.normalize(
            [{"trade_date": "2026-10-16", "open": "1.5", "close": "2.5", "high": "3", "low": "1", "volume": "100"}],
            job,
        )
        assert result.rows[0]["volume"] == 100
        assert result.rows[0]["close"] == 2.5

    def test_custom_parse_injected_as_response_handler(self):
        """专用 provider 必须让 fetch_json 把原始文本交回自身 parse（否则嵌套/平铺结构会被误判）."""
        job = _job("sina_kline", "https://example/x", entrant_param="symbol", entrant_values=("sh600519",))
        plan = SINA.build_requests(job)[0]
        assert callable(plan.config.response_handler)
        rows = plan.config.response_handler('[{"day":"2026-10-19","close":"9"}]', plan.config)
        assert rows[0]["trade_date"] == "2026-10-19"

    def test_plain_http_json_has_no_custom_handler(self):
        """通用 provider 不注入自定义 handler，保持默认 JSON 探测."""
        from cndb.plugins.datasource.providers.http_json import HttpJsonProvider

        provider = HttpJsonProvider()
        plan = provider.build_requests(_job("http_json", "https://example/x"))[0]
        assert not callable(plan.config.response_handler)
        assert plan.config.response_handler == "json"


class TestPipelineEntrantFill:
    def test_fill_entrant_defaults_missing_column(self):
        rows = fill_entrant([{"close": "1"}], "symbol", "sh600519")
        assert rows[0]["symbol"] == "sh600519"

    def test_fill_entrant_keeps_response_value(self):
        rows = fill_entrant([{"symbol": "sz000001"}], "symbol", "sh600519")
        assert rows[0]["symbol"] == "sz000001"

    def test_fill_entrant_noop_without_param(self):
        rows = fill_entrant([{"close": "1"}], None, "sh600519")
        assert "symbol" not in rows[0]
