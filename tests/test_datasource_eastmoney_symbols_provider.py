"""datasource：``eastmoney_symbols`` provider 解析 / 归一 / 请求构造单测（不依赖外网）.

覆盖：``data.diff`` 的数组与索引对象两种形态 / 市场号还原代码前缀与市场选项值 /
未知市场号按代码兜底 / 空 f12 剔除 / 空 data 与非法响应 / 市场别名归一 /
``fs`` 表达式换算 / 分页请求展开 / 默认归一与显式字段映射 / 注册表元信息。
"""

from __future__ import annotations

import json

import pytest

from cndb.plugins.datasource.providers.base import (
    PagingSpec,
    ProviderError,
    RequestSpec,
    SyncJobSpec,
)
from cndb.plugins.datasource.providers.eastmoney_symbols import (
    EASTMONEY_SYMBOLS_URL_TEMPLATE,
    MARKET_PREFIXES,
    EastmoneySymbolsProvider,
    fs_for_market,
    market_for_symbol,
    normalize_market,
)
from cndb.plugins.datasource.providers.registry import get_provider, list_providers

SYMBOLS = EastmoneySymbolsProvider()

A_SHARE_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"

PAYLOAD = {
    "rc": 0,
    "data": {
        "total": 4,
        "diff": [
            {"f12": "600519", "f13": 1, "f14": "贵州茅台"},
            {"f12": "000001", "f13": 0, "f14": "平安银行"},
            {"f12": "00700", "f13": 116, "f14": "腾讯控股"},
            {"f12": "AAPL", "f13": 105, "f14": "苹果"},
        ],
    },
}


def _job(**kwargs) -> SyncJobSpec:
    spec: dict[str, object] = {
        "request": RequestSpec(url_template=EASTMONEY_SYMBOLS_URL_TEMPLATE),
        "provider": "eastmoney_symbols",
        "entrant_param": "market",
        "entrant_values": ("A",),
    }
    spec.update(kwargs)
    return SyncJobSpec(**spec)  # type: ignore[arg-type]


class TestParse:
    def test_parses_list_diff(self):
        rows = SYMBOLS.parse(json.dumps(PAYLOAD), _job())
        assert [row["symbol"] for row in rows] == ["sh600519", "sz000001", "hk00700", "usAAPL"]
        assert [row["market"] for row in rows] == ["A股", "A股", "港股", "美股"]
        assert rows[0]["name"] == "贵州茅台"
        assert rows[0]["code"] == "600519"

    def test_parses_indexed_diff_object(self):
        indexed = {
            "0": {"f12": "600519", "f13": 1, "f14": "贵州茅台"},
            "1": {"f12": "00700", "f13": 116, "f14": "腾讯"},
        }
        rows = SYMBOLS.parse(json.dumps({"rc": 0, "data": {"diff": indexed}}), _job())
        assert [row["symbol"] for row in rows] == ["sh600519", "hk00700"]

    @pytest.mark.parametrize(
        ("market_no", "code", "symbol", "market"),
        [
            (106, "TSLA", "usTSLA", "美股"),
            (107, "BRK.A", "usBRK.A", "美股"),
            (999, "00700", "hk00700", "港股"),  # 未知市场号 → 5 位数字按港股
            (None, "AAPL", "usAAPL", "美股"),  # 字母按美股
            ("bad", "000001", "sz000001", "A股"),
        ],
    )
    def test_unknown_market_falls_back_by_code(self, market_no, code, symbol, market):
        payload = {"rc": 0, "data": {"diff": [{"f12": code, "f13": market_no, "f14": "x"}]}}
        row = SYMBOLS.parse(json.dumps(payload), _job())[0]
        assert row["symbol"] == symbol
        assert row["market"] == market

    def test_symbol_lowercase_prefix_normalized_to_upper_us(self):
        payload = {"rc": 0, "data": {"diff": [{"f12": "aapl", "f13": 105, "f14": "苹果"}]}}
        assert SYMBOLS.parse(json.dumps(payload), _job())[0]["symbol"] == "usAAPL"

    def test_skips_items_without_code_or_non_dict(self):
        payload = {"rc": 0, "data": {"diff": [{"f13": 1, "f14": "无代码"}, "bad", None, {"f12": "600519", "f13": 1}]}}
        rows = SYMBOLS.parse(json.dumps(payload), _job())
        assert [row["symbol"] for row in rows] == ["sh600519"]
        assert rows[0]["name"] == ""  # f14 缺失 → 空名

    def test_empty_payloads_return_no_rows(self):
        assert SYMBOLS.parse('{"rc": 0}', _job()) == []
        assert SYMBOLS.parse('{"rc": 0, "data": null}', _job()) == []
        assert SYMBOLS.parse('{"rc": 0, "data": {"diff": []}}', _job()) == []
        assert SYMBOLS.parse('{"rc": 0, "data": {"diff": "oops"}}', _job()) == []

    def test_error_code_and_invalid_json_raise(self):
        with pytest.raises(ProviderError, match="错误码"):
            SYMBOLS.parse('{"rc": 102, "data": null}', _job())
        with pytest.raises(ProviderError, match="不是合法 JSON"):
            SYMBOLS.parse("<html>", _job())
        with pytest.raises(ProviderError, match="顶层必须是对象"):
            SYMBOLS.parse("[]", _job())


class TestMarketHelpers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("A", "A"),
            ("a股", "A"),
            ("CN", "A"),
            ("hk", "HK"),
            ("港股", "HK"),
            ("US", "US"),
            ("美股", "US"),
            ("ALL", "ALL"),
            ("全市场", "ALL"),
        ],
    )
    def test_normalize_market(self, raw, expected):
        assert normalize_market(raw) == expected

    def test_normalize_market_rejects_unknown(self):
        with pytest.raises(ProviderError, match="未知市场"):
            normalize_market("jp")
        with pytest.raises(ProviderError, match="不能为空"):
            normalize_market("  ")

    def test_fs_for_market(self):
        assert fs_for_market("A") == A_SHARE_FS
        assert fs_for_market("港股") == "m:116"
        assert fs_for_market("ALL") == "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:116,m:105,m:106,m:107"
        # 已是 fs 表达式 → 原样放行（自定义板块）
        assert fs_for_market("m:90+t:2") == "m:90+t:2"

    @pytest.mark.parametrize(
        ("symbol", "expected"),
        [("sh600519", "A股"), ("SZ000001", "A股"), ("hk00700", "港股"), ("usAAPL", "美股"), ("bj430047", "")],
    )
    def test_market_for_symbol(self, symbol, expected):
        assert market_for_symbol(symbol) == expected

    def test_market_prefixes_cover_all(self):
        assert MARKET_PREFIXES["ALL"] == ("sh", "sz", "hk", "us")


class TestBuildRequests:
    def test_expands_market_and_page_matrix(self):
        job = _job(
            entrant_values=("A", "HK"),
            request=RequestSpec(
                url_template=EASTMONEY_SYMBOLS_URL_TEMPLATE,
                paging=PagingSpec(mode="page", page_size=100, start_page=1, max_pages=3),
            ),
        )
        plans = SYMBOLS.build_requests(job)
        assert len(plans) == 6
        assert plans[0].entrant == "A"
        assert plans[0].page == 1
        assert "pn=1" in plans[0].config.url
        assert "pz=100" in plans[0].config.url
        assert "fs=m:0+t:6" in plans[0].config.url
        # 第二个市场使用港股 fs
        hk_plans = [p for p in plans if p.entrant == "HK"]
        assert len(hk_plans) == 3
        assert all("fs=m:116" in p.config.url for p in hk_plans)

    def test_requires_at_least_one_market(self):
        with pytest.raises(ProviderError, match="entrant_keys"):
            SYMBOLS.build_requests(_job(entrant_values=()))

    def test_custom_fs_expression_passes_through(self):
        job = _job(entrant_values=("m:90+t:2",))
        plans = SYMBOLS.build_requests(job)
        assert len(plans) == 1  # paging=none → 只抓首页
        assert "fs=m:90+t:2" in plans[0].config.url
        assert "pn=1" in plans[0].config.url
        assert "pz=50" in plans[0].config.url  # PagingSpec 默认页大小


class TestNormalize:
    def test_default_mapping_keeps_code_columns(self):
        rows = SYMBOLS.parse(json.dumps(PAYLOAD), _job())
        result = SYMBOLS.normalize(rows, _job())
        assert result.failed == 0
        out = result.rows[0]
        assert out == {
            "symbol": "sh600519",
            "code": "600519",
            "name": "贵州茅台",
            "market": "A股",
        }

    def test_explicit_mapping_wins(self):
        job = _job(
            field_mapping={
                "symbol": {"name": "股票代码", "field_type": "text"},
                "name": {"name": "股票名称", "field_type": "text"},
                "market": {"name": "市场", "field_type": "text"},
                "code": None,
            }
        )
        rows = SYMBOLS.parse(json.dumps(PAYLOAD), job)
        out = SYMBOLS.normalize(rows, job).rows[0]
        assert out == {"股票代码": "sh600519", "股票名称": "贵州茅台", "市场": "A股"}


class TestRegistry:
    def test_registered_with_paging(self):
        provider = get_provider("eastmoney_symbols")
        assert provider.name == "eastmoney_symbols"
        assert provider.default_cursor == "none"
        assert provider.supports_paging is True

    def test_listed_in_provider_catalog(self):
        entries = {item["name"]: item for item in list_providers()}
        entry = entries["eastmoney_symbols"]
        assert entry["supports_paging"] is True
        placeholders = entry["params_schema"]["placeholders"]
        assert {"market", "fs", "page", "page_size"} <= set(placeholders)

    def test_url_template_uses_paging_and_fs(self):
        assert "{page}" in EASTMONEY_SYMBOLS_URL_TEMPLATE
        assert "{page_size}" in EASTMONEY_SYMBOLS_URL_TEMPLATE
        assert "{fs}" in EASTMONEY_SYMBOLS_URL_TEMPLATE
        assert "f12,f13,f14" in EASTMONEY_SYMBOLS_URL_TEMPLATE
