"""datasource：``eastmoney_kline`` provider 解析 / 归一 / 请求构造单测（不依赖外网）.

覆盖：A/HK/US 市场 symbol 还原 / 11 字段拆解 / 最新行情快照 / 空 data 与空 klines /
非法 JSON 与错误码 / 缺列与无日期条目 / to_secid 前缀换算 / 多标的请求展开 /
默认归一（kline→JSON）与显式字段映射 / 注册表元信息。
"""

from __future__ import annotations

import json

import pytest

from cndb.plugins.datasource.providers.base import ProviderError, RequestSpec, SyncJobSpec
from cndb.plugins.datasource.providers.eastmoney_kline import (
    EASTMONEY_KLINE_URL_TEMPLATE,
    EastmoneyKlineProvider,
    to_secid,
)
from cndb.plugins.datasource.providers.registry import get_provider, list_providers

KLINE = EastmoneyKlineProvider()

A_SHARE_PAYLOAD = {
    "rc": 0,
    "data": {
        "code": "600519",
        "market": 1,
        "name": "贵州茅台",
        "klines": [
            "2024-01-02,1680.00,1700.00,1710.00,1670.00,30000,5100000000,2.38,1.19,20.00,0.24",
            "2024-01-03,1700.00,1690.00,1720.00,1680.00,28000,4704000000,2.35,-0.59,-10.00,0.22",
        ],
    },
}


def _job(provider: str = "eastmoney_kline", **kwargs) -> SyncJobSpec:
    return SyncJobSpec(
        request=RequestSpec(url_template=EASTMONEY_KLINE_URL_TEMPLATE),
        provider=provider,
        **kwargs,
    )


class TestParse:
    def test_parses_a_share_full_fields(self):
        rows = KLINE.parse(json.dumps(A_SHARE_PAYLOAD), _job())
        assert len(rows) == 1
        row = rows[0]
        assert row["symbol"] == "sh600519"
        assert row["name"] == "贵州茅台"
        assert row["kline"] == [
            {
                "date": "2024-01-02",
                "open": 1680.0,
                "close": 1700.0,
                "high": 1710.0,
                "low": 1670.0,
                "volume": 30000.0,
                "amount": 5100000000.0,
                "amplitude": 2.38,
                "pct_change": 1.19,
                "change": 20.0,
                "turnover": 0.24,
            },
            {
                "date": "2024-01-03",
                "open": 1700.0,
                "close": 1690.0,
                "high": 1720.0,
                "low": 1680.0,
                "volume": 28000.0,
                "amount": 4704000000.0,
                "amplitude": 2.35,
                "pct_change": -0.59,
                "change": -10.0,
                "turnover": 0.22,
            },
        ]
        # 最新行情快照取最后一根
        assert row["latest_date"] == "2024-01-03"
        assert row["latest_close"] == 1690.0
        assert row["latest_pct_change"] == -0.59
        assert row["latest_volume"] == 28000.0
        assert row["latest_amount"] == 4704000000.0

    @pytest.mark.parametrize(
        ("market", "code", "expected"),
        [
            (116, "00700", "hk00700"),
            (105, "AAPL", "usAAPL"),
            (106, "TSLA", "usTSLA"),
            (0, "000001", "sz000001"),
        ],
    )
    def test_symbol_restored_from_market(self, market, code, expected):
        payload = {
            "rc": 0,
            "data": {"code": code, "market": market, "klines": ["2024-01-02,1,1,1,1,1,1,0,0,0,0"]},
        }
        rows = KLINE.parse(json.dumps(payload), _job())
        assert rows[0]["symbol"] == expected

    def test_symbol_falls_back_to_raw_code(self):
        payload = {"rc": 0, "data": {"code": "600519", "market": 999, "klines": ["2024-01-02,1,1,1,1,1,1,0,0,0,0"]}}
        assert KLINE.parse(json.dumps(payload), _job())[0]["symbol"] == "600519"

    def test_missing_columns_become_none(self):
        payload = {"rc": 0, "data": {"code": "600519", "market": 1, "klines": ["2024-01-02,10,11"]}}
        point = KLINE.parse(json.dumps(payload), _job())[0]["kline"][0]
        assert point["date"] == "2024-01-02"
        assert point["open"] == 10.0
        assert point["close"] == 11.0
        assert point["high"] is None
        assert point["volume"] is None
        assert point["turnover"] is None

    def test_invalid_kline_items_dropped(self):
        payload = {
            "rc": 0,
            "data": {
                "code": "600519",
                "market": 1,
                "klines": ["", "   ", ",1,2,3,4", 123, "2024-01-02,1,1,1,1"],
            },
        }
        rows = KLINE.parse(json.dumps(payload), _job())
        assert len(rows) == 1
        assert [p["date"] for p in rows[0]["kline"]] == ["2024-01-02"]

    def test_empty_data_and_empty_klines(self):
        assert KLINE.parse('{"rc": 0}', _job()) == []
        assert KLINE.parse('{"rc": 0, "data": null}', _job()) == []
        assert KLINE.parse('{"rc": 0, "data": {"code": "600519", "klines": []}}', _job()) == []
        assert KLINE.parse('{"rc": 0, "data": {"code": "600519", "klines": "not-a-list"}}', _job()) == []
        # 全部条目无效 → 空（不产出行）
        assert KLINE.parse('{"rc": 0, "data": {"code": "600519", "klines": [",1,2"]}}', _job()) == []

    def test_error_code_raises(self):
        with pytest.raises(ProviderError, match="错误码"):
            KLINE.parse('{"rc": 102, "data": null}', _job())

    def test_invalid_json_raises(self):
        with pytest.raises(ProviderError, match="不是合法 JSON"):
            KLINE.parse("<html>", _job())
        with pytest.raises(ProviderError, match="顶层必须是对象"):
            KLINE.parse("[]", _job())


class TestToSecid:
    @pytest.mark.parametrize(
        ("symbol", "expected"),
        [
            ("sh600519", "1.600519"),
            ("sz000001", "0.000001"),
            ("hk00700", "116.00700"),
            ("usAAPL", "105.AAPL"),
            ("usaapl", "105.AAPL"),
            # 无前缀兜底：5 位港股 / 6·9 开头沪市 / 其余数字深市 / 字母美股
            ("00700", "116.00700"),
            ("600519", "1.600519"),
            ("000001", "0.000001"),
            ("AAPL", "105.AAPL"),
            # 已是 secid 原样返回
            ("1.600519", "1.600519"),
        ],
    )
    def test_secid(self, symbol, expected):
        assert to_secid(symbol) == expected

    def test_blank_symbol_raises(self):
        with pytest.raises(ProviderError, match="不能为空"):
            to_secid("  ")
        with pytest.raises(ProviderError, match="缺少市场后缀"):
            to_secid("sh")


class TestBuildRequests:
    def test_expands_one_plan_per_entrant(self):
        job = _job(entrant_param="symbol", entrant_values=("sh600519", "hk00700"))
        plans = KLINE.build_requests(job)
        assert len(plans) == 2
        assert "secid=1.600519" in plans[0].config.url
        assert "secid=116.00700" in plans[1].config.url
        assert plans[0].entrant == "sh600519"
        assert "klt=101" in plans[0].config.url
        assert "fqt=1" in plans[0].config.url

    def test_requires_entrants(self):
        with pytest.raises(ProviderError, match="entrant_keys"):
            KLINE.build_requests(_job())


class TestNormalize:
    def test_default_mapping_serializes_kline_json(self):
        rows = KLINE.parse(json.dumps(A_SHARE_PAYLOAD), _job())
        result = KLINE.normalize(rows, _job())
        assert result.failed == 0
        out = result.rows[0]
        assert isinstance(out["kline"], str)
        decoded = json.loads(out["kline"])
        assert len(decoded) == 2
        assert decoded[0]["date"] == "2024-01-02"
        assert out["latest_close"] == 1690.0
        assert out["latest_date"] == "2024-01-03"
        assert out["symbol"] == "sh600519"

    def test_explicit_mapping_wins(self):
        job = _job(
            field_mapping={
                "symbol": {"name": "股票代码", "field_type": "text"},
                "kline": {"name": "日线前复权", "field_type": "json"},
                "latest_close": {"name": "最新价", "field_type": "float"},
                "name": None,  # 丢弃
            }
        )
        rows = KLINE.parse(json.dumps(A_SHARE_PAYLOAD), job)
        result = KLINE.normalize(rows, job)
        out = result.rows[0]
        assert out["股票代码"] == "sh600519"
        assert out["最新价"] == 1690.0
        assert json.loads(out["日线前复权"])[0]["close"] == 1700.0
        assert "name" not in out


class TestRegistry:
    def test_registered_with_contract(self):
        provider = get_provider("eastmoney_kline")
        assert provider.name == "eastmoney_kline"
        assert provider.default_cursor == "none"
        assert provider.supports_paging is False

    def test_listed_in_provider_catalog(self):
        entries = {item["name"]: item for item in list_providers()}
        entry = entries["eastmoney_kline"]
        assert entry["supports_paging"] is False
        assert "fields" in entry["params_schema"]
        assert "secid" in entry["params_schema"]["placeholders"]

    def test_url_template_carries_period_and_adjust_params(self):
        assert "{secid}" in EASTMONEY_KLINE_URL_TEMPLATE
        assert "klt=101" in EASTMONEY_KLINE_URL_TEMPLATE
        assert "fqt=1" in EASTMONEY_KLINE_URL_TEMPLATE
        assert "lmt=100000" in EASTMONEY_KLINE_URL_TEMPLATE
