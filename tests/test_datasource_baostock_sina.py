"""datasource：``sina_kline`` / ``baostock_kline`` provider 与管线补标的单测（不联网）.

覆盖：
- 新浪平铺数组解析、字段改名、空值剔除、非法响应报错
- baostock 标的格式互转、传输参数校验、查询结果 → 统一字段、会话失败重登标记
- ``uses_custom_parse`` → ``response_handler`` 注入（否则 fetch_json 的通用数组探测会解析错）
- 管线：provider 自带 ``fetch_plan`` 优先于 ``fetch_json``；响应不带标的时按 entrant 补齐
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from cndb.plugins.datasource.providers import baostock_kline as bs_mod
from cndb.plugins.datasource.providers.base import (
    FieldTransform,
    ProviderError,
    RequestPlan,
    RequestSpec,
    SyncJobSpec,
    TimeWindowSpec,
)
from cndb.plugins.datasource.providers.registry import get_provider
from cndb.plugins.datasource.providers.sina_kline import SinaKlineProvider
from cndb.plugins.datasource.services import pipeline as pipeline_mod
from cndb.plugins.datasource.services.pipeline import fill_entrant, run_pipeline
from cndb.plugins.tables.services.importing.api_fetch import FetchConfig

SINA = SinaKlineProvider()
BAOSTOCK = bs_mod.BaostockKlineProvider()


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


class TestBaostockSymbols:
    """标的格式互转：表内无点（sh600519）↔ baostock 有点（sh.600519）."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("sh600519", "sh.600519"),
            ("SZ000001", "sz.000001"),
            ("600519.SH", "sh.600519"),
            ("sh.600519", "sh.600519"),
        ],
    )
    def test_to_baostock_symbol(self, raw: str, expected: str):
        assert bs_mod._to_baostock_symbol(raw) == expected

    def test_to_baostock_symbol_rejects_garbage(self):
        with pytest.raises(ProviderError):
            bs_mod._to_baostock_symbol("600519")

    def test_from_baostock_symbol(self):
        assert bs_mod._from_baostock_symbol("sh.600519") == "sh600519"


class TestBaostockTransportOptions:
    def test_defaults(self):
        assert bs_mod._parse_transport_options("baostock://kline") == ("d", "2")

    def test_reads_query(self):
        assert bs_mod._parse_transport_options("baostock://kline?frequency=w&adjustflag=1") == ("w", "1")

    @pytest.mark.parametrize("url", ["baostock://kline?frequency=x", "baostock://kline?adjustflag=9"])
    def test_rejects_bad_options(self, url: str):
        with pytest.raises(ProviderError):
            bs_mod._parse_transport_options(url)


class _FakeResult:
    """最小 baostock 结果集桩：fields + next()/get_row_data()."""

    def __init__(self, rows: list[list[str]], *, error_code: str = "0"):
        self.fields = ["date", "code", "open", "high", "low", "close", "volume", "amount"]
        self.error_code = error_code
        self.error_msg = "" if error_code == "0" else "boom"
        self._rows = iter(rows)
        self._current: list[str] = []

    def next(self) -> bool:
        try:
            self._current = next(self._rows)
            return True
        except StopIteration:
            return False

    def get_row_data(self) -> list[str]:
        return self._current


class _FakeBs:
    def __init__(self, rows: list[list[str]], *, error_code: str = "0", login_error: str = "0"):
        self.rows = rows
        self.error_code = error_code
        self.login_error = login_error
        self.calls: list[dict[str, Any]] = []

    def login(self):
        return type("R", (), {"error_code": self.login_error, "error_msg": ""})()

    def logout(self):  # pragma: no cover - 退出钩子
        return None

    def query_history_k_data_plus(self, code, fields, **kwargs):
        self.calls.append({"code": code, "fields": fields, **kwargs})
        return _FakeResult(self.rows, error_code=self.error_code)


@pytest.fixture
def fake_bs(monkeypatch):
    """把模块级 _login 换成桩，避免任何真实 TCP 连接."""
    state: dict[str, Any] = {}

    def install(rows: list[list[str]], **kwargs: Any) -> _FakeBs:
        fake = _FakeBs(rows, **kwargs)
        monkeypatch.setattr(bs_mod, "_login", lambda: fake)
        monkeypatch.setitem(bs_mod._state, "logged_in", True)
        state["fake"] = fake
        return fake

    return install


class TestBaostockProvider:
    def test_query_maps_fields_and_symbol(self, fake_bs):
        fake = fake_bs(
            [["2021-10-18", "sh.600519", "1631.85", "1631.85", "1544.55", "1555.79", "6965202", "12651498606.59"]]
        )
        rows = BAOSTOCK.query("sh600519", start="2021-10-18", end="2021-10-18")
        assert rows == [
            {
                "trade_date": "2021-10-18",
                "symbol": "sh600519",
                "open": "1631.85",
                "high": "1631.85",
                "low": "1544.55",
                "close": "1555.79",
                "volume": "6965202",
                "amount": "12651498606.59",
            }
        ]
        assert fake.calls[0]["code"] == "sh.600519"
        assert fake.calls[0]["adjustflag"] == "2"

    def test_query_raises_on_error_code(self, fake_bs, monkeypatch):
        fake_bs([], error_code="10001")
        monkeypatch.setitem(bs_mod._state, "logged_in", True)
        with pytest.raises(ProviderError):
            BAOSTOCK.query("sh600519", start="2021-10-18", end="2021-10-18")
        # 失败后标记未登录，下次调用重登（否则断线会一直失败）
        assert bs_mod._state["logged_in"] is False

    def test_fetch_plan_requires_window(self, fake_bs):
        fake_bs([["2021-10-18", "sh.600519", "1", "1", "1", "1", "1", "1"]])
        plan = RequestPlan(
            config=FetchConfig(url="baostock://kline?adjustflag=2"),
            label="symbol=sh600519",
            entrant="sh600519",
            variables={"symbol": "sh600519"},
        )
        with pytest.raises(ProviderError):
            BAOSTOCK.fetch_plan(plan)

    def test_fetch_plan_queries_window(self, fake_bs):
        fake_bs([["2021-10-18", "sh.600519", "1", "2", "0.5", "1.5", "100", "200"]])
        plan = RequestPlan(
            config=FetchConfig(url="baostock://kline?adjustflag=2"),
            label="symbol=sh600519",
            entrant="sh600519",
            variables={"symbol": "sh600519", "start": "2021-10-18", "end": "2026-10-20"},
        )
        rows = BAOSTOCK.fetch_plan(plan)
        assert rows[0]["symbol"] == "sh600519"
        assert rows[0]["trade_date"] == "2021-10-18"

    def test_registered_in_registry(self):
        assert get_provider("baostock_kline").name == "baostock_kline"
        assert get_provider("sina_kline").name == "sina_kline"


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

    def test_pipeline_prefers_provider_fetch_plan(self, monkeypatch):
        """provider 自带 fetch_plan 时不得再走 fetch_json（baostock 是 TCP 不是 HTTP）."""
        called: list[str] = []

        def boom(_config):  # pragma: no cover - 走了就是缺陷
            called.append("fetch_json")
            raise AssertionError("不应调用 fetch_json")

        monkeypatch.setattr(pipeline_mod, "fetch_json", boom)
        # 必须打在类上：registry 里的实例与模块级 BAOSTOCK 不是同一个对象
        monkeypatch.setattr(
            bs_mod.BaostockKlineProvider,
            "fetch_plan",
            lambda _self, plan: [{"trade_date": "2021-10-18", "symbol": plan.entrant, "close": "1"}],
        )
        job = SyncJobSpec(
            request=RequestSpec(
                url_template="baostock://kline?adjustflag=2",
                time_window=TimeWindowSpec(mode="range", start="2021-10-18", end="2021-10-18"),
            ),
            provider="baostock_kline",
            entrant_param="symbol",
            entrant_values=("sh600519",),
            field_mapping={"close": FieldTransform(name="close", field_type="float")},
        )
        outcome = run_pipeline(job)
        assert called == []
        assert outcome.status == "success"
        assert outcome.rows[0]["symbol"] == "sh600519"
