"""内置 provider：``eastmoney_kline`` —— 东方财富多市场 K 线（日 / 周 / 月，前 / 后 / 不复权）.

接口形如::

    https://push2his.eastmoney.com/api/qt/stock/kline/get
        ?secid=1.600519
        &fields1=f1,f2,f3,f4,f5,f6
        &fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61
        &klt=101&fqt=1&beg=0&end=20500101&lmt=100000

``klt``：101 日线 / 102 周线 / 103 月线；``fqt``：0 不复权 / 1 前复权 / 2 后复权。
响应（嵌套 JSON）::

    {"rc": 0, "data": {"code": "600519", "market": 1, "name": "贵州茅台",
                       "klines": ["2024-01-02,1680.00,1700.00,1710.00,1670.00,..."]}}

与 ``tencent_kline`` 的差异：

- 一只股票输出 **一行**，K 线数组放在 ``kline`` 字段（目标表为「一只股一行」内嵌 JSON）；
- 一次请求覆盖全历史（``beg=0&lmt=100000``），不依赖时间分片；
- 字段更全：成交量、成交额、振幅、涨跌幅、涨跌额、换手率；
- 支持 A 股 / 港股 / 美股，``secid`` 由代码前缀换算。

继承 ``http_json`` 复用请求模板 / 归一；覆写 ``build_requests``、``_variables``、``parse``。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, override

from cndb.plugins.datasource.providers.base import (
    CursorStrategy,
    FieldTransform,
    ProviderError,
    RequestPlan,
    SourceProvider,
    SyncJobSpec,
)
from cndb.plugins.datasource.providers.http_json import HttpJsonProvider
from cndb.plugins.datasource.services.normalize import NormalizeResult, apply_field_mapping

# 向导预填用的请求模板：{secid} 由 provider 按代码前缀换算；klt/fqt 由 job 固定。
EASTMONEY_KLINE_URL_TEMPLATE = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?secid={secid}"
    "&fields1=f1,f2,f3,f4,f5,f6"
    "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
    "&klt=101&fqt=1&beg=0&end=20500101&lmt=100000"
)

EASTMONEY_KLINE_PARAMS_SCHEMA: dict[str, Any] = {
    "fields": [
        {
            "name": "symbol",
            "type": "text",
            "required": True,
            "label": "股票代码",
            "placeholder": "sh600519 / sz000001 / hk00700 / usAAPL",
            "multiple": True,
        },
        {
            "name": "url_template",
            "type": "text",
            "required": True,
            "label": "URL 模板（klt=101/102/103，fqt=0/1/2）",
            "default": EASTMONEY_KLINE_URL_TEMPLATE,
        },
        {
            "name": "period",
            "type": "select",
            "options": ["day", "week", "month"],
            "default": "day",
            "label": "周期（仅向导提示，实际由 URL 的 klt 决定）",
        },
        {
            "name": "adjust",
            "type": "select",
            "options": ["qfq", "hfq", "none"],
            "default": "qfq",
            "label": "复权（仅向导提示，实际由 URL 的 fqt 决定）",
        },
    ],
    "placeholders": ["symbol", "secid"],
    "notes": "一只股票输出一行，kline 为完整 K 线数组；全历史由 beg=0&lmt=100000 控制。",
}

# 东方财富 fields2 的字段顺序（f51..f61）
_KLINE_FIELDS: tuple[tuple[str, str], ...] = (
    ("date", "text"),
    ("open", "float"),
    ("close", "float"),
    ("high", "float"),
    ("low", "float"),
    ("volume", "float"),
    ("amount", "float"),
    ("amplitude", "float"),
    ("pct_change", "float"),
    ("change", "float"),
    ("turnover", "float"),
)

# 代码前缀 → secid 市场号（A 股 1/0，港股 116，美股 105/106/107 统一按 105 请求）
_MARKET_BY_PREFIX = {"sh": "1", "sz": "0", "hk": "116", "us": "105"}

# 响应 market → 代码前缀（1 沪 / 0 深 / 116 港 / 105-107 美）
_PREFIX_BY_MARKET = {1: "sh", 0: "sz", 116: "hk", 105: "us", 106: "us", 107: "us"}


class EastmoneyKlineProvider(HttpJsonProvider):
    """东方财富 K 线：一只股票一行，行内嵌完整 K 线 JSON."""

    name = "eastmoney_kline"
    label = "东方财富 K 线（A/HK/US，多周期复权）"
    params_schema: Mapping[str, Any] = EASTMONEY_KLINE_PARAMS_SCHEMA
    default_cursor: CursorStrategy = "none"
    supports_paging = False
    uses_custom_parse = True

    @override
    def build_requests(self, job: SyncJobSpec) -> list[RequestPlan]:
        if not job.entrant_values:
            raise ProviderError("eastmoney_kline 需要至少一个股票代码（entrant_keys）")
        return super().build_requests(job)

    @override
    def _variables(
        self,
        job: SyncJobSpec,
        entrant: str | None,
        window_start: str | None,
        window_end: str | None,
        page: int | None,
    ) -> dict[str, Any]:
        variables = super()._variables(job, entrant, window_start, window_end, page)
        if entrant:
            variables["secid"] = to_secid(entrant)
        return variables

    @override
    def parse(self, text: str, job: SyncJobSpec) -> list[dict[str, Any]]:
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(f"东方财富 K 线响应不是合法 JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ProviderError("东方财富 K 线响应顶层必须是对象")
        rc = payload.get("rc")
        if rc not in (0, "0", None):
            raise ProviderError(f"东方财富 K 线返回错误码 {rc!r}")
        data = payload.get("data")
        if not isinstance(data, dict):
            return []
        klines = data.get("klines")
        if not isinstance(klines, list):
            return []

        series: list[dict[str, Any]] = []
        for item in klines:
            point = _parse_kline_item(item)
            if point is not None:
                series.append(point)
        if not series:
            return []

        code = str(data.get("code") or "").strip()
        symbol = _symbol_from_payload(code, data.get("market"))
        name = str(data.get("name") or "").strip()
        row: dict[str, Any] = {
            "symbol": symbol,
            "name": name,
            "kline": series,
        }
        row.update(_latest_fields(series))
        return [row]

    @override
    def normalize(self, rows: Sequence[Mapping[str, Any]], job: SyncJobSpec) -> NormalizeResult:
        """未配置字段映射时按 K 线语义默认归类（JSON / 日期 / 数值）."""
        if job.field_mapping:
            return apply_field_mapping(rows, job.field_mapping)
        default_mapping = {
            "symbol": FieldTransform(name="symbol", field_type="text"),
            "name": FieldTransform(name="name", field_type="text"),
            "kline": FieldTransform(name="kline", field_type="json"),
            "latest_date": FieldTransform(name="latest_date", field_type="date"),
            "latest_close": FieldTransform(name="latest_close", field_type="float"),
            "latest_pct_change": FieldTransform(name="latest_pct_change", field_type="float"),
            "latest_volume": FieldTransform(name="latest_volume", field_type="float"),
            "latest_amount": FieldTransform(name="latest_amount", field_type="float"),
        }
        return apply_field_mapping(rows, default_mapping)


def to_secid(symbol: str) -> str:
    """把带市场前缀的代码换算为东方财富 ``secid``.

    ``sh600519`` → ``1.600519``；``sz000001`` → ``0.000001``；
    ``hk00700`` → ``116.00700``；``usAAPL`` → ``105.AAPL``。
    已形如 ``1.600519`` 的 secid 原样返回。
    """
    text = symbol.strip()
    if not text:
        raise ProviderError("股票代码不能为空")
    head, _, tail = text.partition(".")
    if head.isdigit() and tail:
        return text

    lower = text.lower()
    for prefix, market in _MARKET_BY_PREFIX.items():
        if lower.startswith(prefix):
            code = text[len(prefix) :].strip()
            if not code:
                raise ProviderError(f"股票代码缺少市场后缀: {symbol!r}")
            return f"{market}.{code.upper() if prefix == 'us' else code}"

    # 无前缀：5 位数字按港股，6/9 开头按沪市，其余数字按深市，字母按美股
    if text.isdigit():
        if len(text) == 5:
            return f"116.{text}"
        return f"1.{text}" if text.startswith(("6", "9")) else f"0.{text}"
    return f"105.{text.upper()}"


def _symbol_from_payload(code: str, market: Any) -> str:
    """响应中的 code + market 还原为带前缀代码；无法还原时回退原始 code."""
    if not code:
        return ""
    lower = code.lower()
    if lower.startswith(("sh", "sz", "hk", "us")):
        return lower
    try:
        market_no = int(market)
    except (TypeError, ValueError):
        return code
    prefix = _PREFIX_BY_MARKET.get(market_no)
    if prefix is None:
        return code
    return f"{prefix}{code.upper() if prefix == 'us' else code}"


def _parse_kline_item(item: Any) -> dict[str, Any] | None:
    """把 ``date,open,close,high,low,volume,amount,amplitude,pct_change,change,turnover`` 拆成字段."""
    if not isinstance(item, str) or not item.strip():
        return None
    parts = item.split(",")
    if not parts or not parts[0].strip():
        return None
    point: dict[str, Any] = {}
    for index, (name, kind) in enumerate(_KLINE_FIELDS):
        raw = parts[index].strip() if index < len(parts) else ""
        if kind == "text":
            point[name] = raw or None
        else:
            point[name] = _to_float(raw)
    if not point.get("date"):
        return None
    return point


def _to_float(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_fields(series: list[dict[str, Any]]) -> dict[str, Any]:
    """取最后一条 K 线作为最新行情快照（东方财富按日期升序返回）."""
    last = series[-1]
    return {
        "latest_date": last.get("date"),
        "latest_close": last.get("close"),
        "latest_pct_change": last.get("pct_change"),
        "latest_volume": last.get("volume"),
        "latest_amount": last.get("amount"),
    }


__all__ = [
    "EASTMONEY_KLINE_PARAMS_SCHEMA",
    "EASTMONEY_KLINE_URL_TEMPLATE",
    "EastmoneyKlineProvider",
    "to_secid",
]

if TYPE_CHECKING:
    _contract: SourceProvider = EastmoneyKlineProvider()
