"""内置 provider：``sina_kline`` —— 新浪 A 股日线（仅不复权）.

接口形如::

    https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData
        ?symbol=sh600519&scale=240&ma=no&datalen=1023

响应是**平铺数组**（无外层 data 包裹，也不回显标的）::

    [{"day":"2026-10-16","open":"1311.570","high":"1329.880",
      "low":"1301.680","close":"1329.000","volume":"3850175"}, ...]

要点：

- 只支持最近 ``datalen`` 根（实测上限 1023，约 4 年交易日），不支持 start/end 区间；
  长历史回填请用 ``baostock_kline`` 或 ``tencent_kline``。
- 无复权参数，返回的是不复权价；与表内前复权列混写会污染口径，务必分开落表。
- ``volume`` 单位为股（与 baostock 一致，腾讯为手，已在腾讯 provider 内换算）。
- 响应不带 symbol：由管线按 ``entrant_param`` 自动补齐（``fill_entrant``）。

继承 ``http_json`` 复用请求模板 / 分页 / 归一；覆写 ``parse``（平铺数组 + 字段改名）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, override

from cndb.plugins.datasource.providers.base import (
    FieldTransform,
    ProviderError,
    SourceProvider,
    SyncJobSpec,
)
from cndb.plugins.datasource.providers.http_json import HttpJsonProvider
from cndb.plugins.datasource.services.normalize import NormalizeResult, apply_field_mapping

SINA_KLINE_URL_TEMPLATE = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    "?symbol={symbol}&scale=240&ma=no&datalen=1023"
)

SINA_KLINE_PARAMS_SCHEMA: dict[str, Any] = {
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
            "label": "URL 模板（datalen 决定根数，上限 1023）",
            "default": SINA_KLINE_URL_TEMPLATE,
        },
    ],
    "placeholders": ["symbol"],
    "notes": "仅不复权 + 仅最近 1023 根；长历史/复权请用 baostock_kline / tencent_kline。",
}

# 新浪日线的原始键 → 统一字段名（day 是日期，其余同名）
_RAW_TO_FIELD = {
    "day": "trade_date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
}


class SinaKlineProvider(HttpJsonProvider):
    """新浪 A 股日线：平铺数组 + 字符串数值 → 统一日线行."""

    name = "sina_kline"
    label = "新浪 A 股日线（不复权）"
    params_schema: Mapping[str, Any] = SINA_KLINE_PARAMS_SCHEMA
    default_cursor = "none"
    supports_paging = False
    uses_custom_parse = True

    @override
    def parse(self, text: str, job: SyncJobSpec) -> list[dict[str, Any]]:
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(f"响应不是合法 JSON: {exc}") from exc
        if not isinstance(payload, list):
            raise ProviderError("新浪日线响应顶层必须是数组")
        rows: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            row: dict[str, Any] = {}
            for raw_key, field in _RAW_TO_FIELD.items():
                value = item.get(raw_key)
                if value is not None and value != "":
                    row[field] = value
            if row.get("trade_date"):
                rows.append(row)
        return rows

    @override
    def normalize(self, rows: Sequence[Mapping[str, Any]], job: SyncJobSpec) -> NormalizeResult:
        """未配置字段映射时按日线语义默认归类（日期 / 数值），避免全落成文本."""
        if job.field_mapping:
            return apply_field_mapping(rows, job.field_mapping)
        default_mapping = {
            "trade_date": FieldTransform(name="trade_date", field_type="date"),
            "open": FieldTransform(name="open", field_type="float"),
            "close": FieldTransform(name="close", field_type="float"),
            "high": FieldTransform(name="high", field_type="float"),
            "low": FieldTransform(name="low", field_type="float"),
            "volume": FieldTransform(name="volume", field_type="int"),
        }
        return apply_field_mapping(rows, default_mapping)


__all__ = ["SINA_KLINE_PARAMS_SCHEMA", "SINA_KLINE_URL_TEMPLATE", "SinaKlineProvider"]

if TYPE_CHECKING:
    _contract: SourceProvider = SinaKlineProvider()
