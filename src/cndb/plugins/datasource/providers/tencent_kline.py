"""内置 provider：``tencent_kline`` —— 腾讯 A 股日线（前 / 后复权）.

接口形如::

    https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600519,day,2024-01-01,2024-01-31,320,qfq

响应（嵌套 JSON）::

    {"code": 0, "data": {"sh600519": {"qfqday": [["2024-01-02","1680.00","1700.00",...]]}}}

单条数组顺序为 ``[日期, 开盘, 收盘, 最高, 最低, 成交量(手)]``。复权方式体现在 URL 末段
（``qfq`` 前复权 / ``hfq`` 后复权 / ``day`` 不复权），本 provider 只负责解析，不改写请求。

继承 ``http_json`` 复用请求模板 / 时间分片 / 归一；只覆写 ``parse``。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, override

from cndb.plugins.datasource.providers.base import FieldTransform, ProviderError, SourceProvider, SyncJobSpec
from cndb.plugins.datasource.providers.http_json import HttpJsonProvider
from cndb.plugins.datasource.services.normalize import NormalizeResult, apply_field_mapping

# 向导预填用的请求模板：{symbol} 由 entrant_param 注入，{start}/{end} 由游标区间注入
TENCENT_KLINE_URL_TEMPLATE = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,{start},{end},320,qfq"
)

TENCENT_KLINE_PARAMS_SCHEMA: dict[str, Any] = {
    "fields": [
        {
            "name": "symbol",
            "type": "text",
            "required": True,
            "label": "股票代码",
            "placeholder": "sh600519 / sz000001",
            "multiple": True,
        },
        {
            "name": "url_template",
            "type": "text",
            "required": True,
            "label": "URL 模板（末段 qfq/hfq/day 决定复权）",
            "default": TENCENT_KLINE_URL_TEMPLATE,
        },
    ],
    "placeholders": ["symbol", "start", "end"],
    "notes": "单次最多返回约 320 根 K 线；回填长区间时把 time_window.chunk_days 设为 320 以内。",
}

# 单条 K 线的字段顺序（腾讯固定）
_KLINE_FIELDS = ("trade_date", "open", "close", "high", "low", "volume")
_SERIES_KEYS = ("qfqday", "hfqday", "day")


class TencentKlineProvider(HttpJsonProvider):
    """A 股日线：把 ``qfqday`` / ``hfqday`` / ``day`` 数组展开为行."""

    name = "tencent_kline"
    label = "腾讯 A 股日线（前 / 后复权）"
    params_schema: Mapping[str, Any] = TENCENT_KLINE_PARAMS_SCHEMA
    supports_paging = False

    @override
    def parse(self, text: str, job: SyncJobSpec) -> list[dict[str, Any]]:
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(f"响应不是合法 JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ProviderError("腾讯日线响应顶层必须是对象")
        code = payload.get("code")
        if code not in (0, "0", None):
            raise ProviderError(f"腾讯日线返回错误码 {code!r}: {payload.get('msg') or ''}")
        data = payload.get("data")
        if not isinstance(data, dict):
            return []
        rows: list[dict[str, Any]] = []
        for symbol, node in data.items():
            if not isinstance(node, dict):
                continue
            series = _pick_series(node)
            for item in series:
                row = _row_from_item(str(symbol), item)
                if row is not None:
                    rows.append(row)
        return rows

    @override
    def normalize(self, rows: Sequence[Mapping[str, Any]], job: SyncJobSpec) -> NormalizeResult:
        """未配置字段映射时，按 K 线语义默认归类（日期 / 数值），避免全落成文本."""
        if job.field_mapping:
            return apply_field_mapping(rows, job.field_mapping)
        typed = [
            {
                "symbol": row.get("symbol"),
                "trade_date": row.get("trade_date"),
                "open": row.get("open"),
                "close": row.get("close"),
                "high": row.get("high"),
                "low": row.get("low"),
                "volume": row.get("volume"),
            }
            for row in rows
        ]
        default_mapping = {
            "trade_date": FieldTransform(name="trade_date", field_type="date"),
            "open": FieldTransform(name="open", field_type="float"),
            "close": FieldTransform(name="close", field_type="float"),
            "high": FieldTransform(name="high", field_type="float"),
            "low": FieldTransform(name="low", field_type="float"),
            "volume": FieldTransform(name="volume", field_type="int"),
        }
        return apply_field_mapping(typed, default_mapping)


def _pick_series(node: Mapping[str, Any]) -> list[Any]:
    for key in _SERIES_KEYS:
        series = node.get(key)
        if isinstance(series, list):
            return series
    return []


def _row_from_item(symbol: str, item: Any) -> dict[str, Any] | None:
    if not isinstance(item, list) or len(item) < 5:
        return None
    row: dict[str, Any] = {"symbol": symbol}
    for index, name in enumerate(_KLINE_FIELDS):
        row[name] = item[index] if index < len(item) else None
    return row


__all__ = [
    "TENCENT_KLINE_PARAMS_SCHEMA",
    "TENCENT_KLINE_URL_TEMPLATE",
    "TencentKlineProvider",
]

if TYPE_CHECKING:
    _contract: SourceProvider = TencentKlineProvider()
