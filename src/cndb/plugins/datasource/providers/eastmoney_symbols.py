"""内置 provider：``eastmoney_symbols`` —— 东方财富全市场标的列表（A / HK / US）.

接口形如::

    https://push2.eastmoney.com/api/qt/clist/get
        ?pn=1&pz=100&po=1&np=1&fltt=2&invt=2&fid=f3
        &fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23
        &fields=f12,f13,f14

``fs`` 是市场过滤表达式（沪 / 深 / 港 / 美），``pn`` 页码、``pz`` 每页条数；
``np=1`` 时 ``data.diff`` 是对象数组，``np=0`` 时是按序号索引的对象。响应::

    {"rc": 0, "data": {"total": 5612, "diff": [
        {"f12": "000001", "f13": 0, "f14": "平安银行"}, ...]}}

``f12`` 代码 / ``f13`` 市场号 / ``f14`` 名称。输出行固定为
``{symbol, code, name, market}``：

- ``symbol`` 带市场前缀（``sh600519`` / ``sz000001`` / ``hk00700`` / ``usAAPL``），
  可直接作为 K 线任务的 ``entrant_keys``；
- ``market`` 为下游「自选股」表的选项值（``A股`` / ``港股`` / ``美股``）。

与 ``eastmoney_kline`` 的分工：本 provider 只发现标的（K 线列为空），
K 线由按批切分的 ``eastmoney_kline`` 任务填充（``cndb sync batch-kline``）。

继承 ``http_json`` 复用请求模板 / 分页 / 归一；覆写 ``build_requests``、``_variables``、``parse``。
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

# 向导预填用的请求模板：{fs} 由 market 换算，{page}/{page_size} 由分页注入
EASTMONEY_SYMBOLS_URL_TEMPLATE = (
    "https://push2.eastmoney.com/api/qt/clist/get"
    "?pn={page}&pz={page_size}&po=1&np=1&fltt=2&invt=2&fid=f3"
    "&fs={fs}"
    "&fields=f12,f13,f14"
)

EASTMONEY_SYMBOLS_PARAMS_SCHEMA: dict[str, Any] = {
    "fields": [
        {
            "name": "market",
            "type": "select",
            "required": True,
            "label": "市场",
            "options": ["A", "HK", "US", "ALL"],
            "default": "A",
            "multiple": True,
        },
        {
            "name": "url_template",
            "type": "text",
            "required": True,
            "label": "URL 模板（fs 由市场换算，pn/pz 为分页）",
            "default": EASTMONEY_SYMBOLS_URL_TEMPLATE,
        },
    ],
    "placeholders": ["market", "fs", "page", "page_size"],
    "notes": "分页拉取全市场标的列表，输出 symbol/name/market；K 线列留空，由 batch-kline 任务按批填充。",
}

# 市场表达式（与东方财富行情列表页的 fs 参数一致）
_FS_BY_MARKET: dict[str, str] = {
    "A": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
    "HK": "m:116",
    "US": "m:105,m:106,m:107",
}
_FS_ALL = ",".join(_FS_BY_MARKET.values())

# 市场别名 → 规范键（CLI 与 job 配置共用；大小写/中英文均容忍）
_MARKET_ALIASES: dict[str, str] = {
    "a": "A",
    "a股": "A",
    "cn": "A",
    "china": "A",
    "沪深": "A",
    "hk": "HK",
    "港股": "HK",
    "hongkong": "HK",
    "us": "US",
    "美股": "US",
    "usa": "US",
    "all": "ALL",
    "全部": "ALL",
    "全市场": "ALL",
}

# 规范市场 → 代码前缀集合（CLI 按表内代码前缀过滤时复用）
MARKET_PREFIXES: dict[str, tuple[str, ...]] = {
    "A": ("sh", "sz"),
    "HK": ("hk",),
    "US": ("us",),
    "ALL": ("sh", "sz", "hk", "us"),
}

# 响应 market 号 → (代码前缀, 市场选项值)
_MARKET_BY_NO: dict[int, tuple[str, str]] = {
    0: ("sz", "A股"),
    1: ("sh", "A股"),
    116: ("hk", "港股"),
    105: ("us", "美股"),
    106: ("us", "美股"),
    107: ("us", "美股"),
}


class EastmoneySymbolsProvider(HttpJsonProvider):
    """东方财富行情列表：分页产出全市场标的（代码 / 名称 / 市场）."""

    name = "eastmoney_symbols"
    label = "东方财富全市场标的（A/HK/US 分页列表）"
    params_schema: Mapping[str, Any] = EASTMONEY_SYMBOLS_PARAMS_SCHEMA
    default_cursor: CursorStrategy = "none"
    supports_paging = True

    @override
    def build_requests(self, job: SyncJobSpec) -> list[RequestPlan]:
        if not job.entrant_values:
            raise ProviderError("eastmoney_symbols 需要至少一个市场（entrant_keys: A/HK/US/ALL）")
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
            variables["market"] = entrant
            variables["fs"] = fs_for_market(entrant)
        # paging=none 时也给出首页变量，让「只抓一页」的最小配置能直接跑通
        variables.setdefault("page", 1)
        variables.setdefault("page_size", job.request.paging.page_size)
        return variables

    @override
    def parse(self, text: str, job: SyncJobSpec) -> list[dict[str, Any]]:
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(f"东方财富标的列表响应不是合法 JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ProviderError("东方财富标的列表响应顶层必须是对象")
        rc = payload.get("rc")
        if rc not in (0, "0", None):
            raise ProviderError(f"东方财富标的列表返回错误码 {rc!r}")
        data = payload.get("data")
        if not isinstance(data, dict):
            return []
        items = _extract_items(data.get("diff"))
        rows: list[dict[str, Any]] = []
        for item in items:
            row = _row_from_item(item)
            if row is not None:
                rows.append(row)
        return rows

    @override
    def normalize(self, rows: Sequence[Mapping[str, Any]], job: SyncJobSpec) -> NormalizeResult:
        """未配置字段映射时按标的语义默认归类（全部文本）."""
        if job.field_mapping:
            return apply_field_mapping(rows, job.field_mapping)
        default_mapping = {
            "symbol": FieldTransform(name="symbol", field_type="text"),
            "code": FieldTransform(name="code", field_type="text"),
            "name": FieldTransform(name="name", field_type="text"),
            "market": FieldTransform(name="market", field_type="text"),
        }
        return apply_field_mapping(rows, default_mapping)


def normalize_market(value: str) -> str:
    """市场别名 → 规范键（``A`` / ``HK`` / ``US`` / ``ALL``）；未知值抛 ProviderError."""
    key = str(value or "").strip().lower()
    if not key:
        raise ProviderError("市场不能为空（可选: A / HK / US / ALL）")
    canonical = _MARKET_ALIASES.get(key)
    if canonical is None:
        raise ProviderError(f"未知市场: {value!r}（可选: A / HK / US / ALL）")
    return canonical


def fs_for_market(value: str) -> str:
    """规范市场（或已是 ``m:`` 表达式）→ 东方财富 ``fs`` 参数."""
    text = str(value or "").strip()
    if text.startswith("m:"):
        return text  # 已是 fs 表达式，原样放行（便于自定义板块）
    key = normalize_market(text)
    return _FS_ALL if key == "ALL" else _FS_BY_MARKET[key]


def market_for_symbol(symbol: str) -> str:
    """按代码前缀还原市场选项值（``sh600519`` → ``A股``）；无法识别返回空串."""
    lower = str(symbol or "").strip().lower()
    for key, prefixes in MARKET_PREFIXES.items():
        if key == "ALL":
            continue
        if lower.startswith(prefixes):
            return {"A": "A股", "HK": "港股", "US": "美股"}[key]
    return ""


def _extract_items(diff: Any) -> list[Mapping[str, Any]]:
    """``data.diff`` 兼容对象数组与按序号索引的对象两种形态."""
    if isinstance(diff, list):
        return [item for item in diff if isinstance(item, Mapping)]
    if isinstance(diff, Mapping):
        return [item for item in diff.values() if isinstance(item, Mapping)]
    return []


def _row_from_item(item: Mapping[str, Any]) -> dict[str, Any] | None:
    code = str(item.get("f12") or "").strip()
    if not code:
        return None
    name = str(item.get("f14") or "").strip()
    prefix, market = _market_of(item.get("f13"), code)
    symbol = f"{prefix}{code.upper() if prefix == 'us' else code}" if prefix else code
    return {
        "symbol": symbol,
        "code": code,
        "name": name,
        "market": market,
    }


def _market_of(raw: Any, code: str) -> tuple[str, str]:
    """市场号 → (前缀, 市场选项值)；无法识别时按代码形态兜底."""
    try:
        market_no = int(raw)
    except (TypeError, ValueError):
        market_no = -1
    hit = _MARKET_BY_NO.get(market_no)
    if hit is not None:
        return hit
    # 兜底：5 位数字视为港股，字母视为美股，其余视为 A 股深市
    if code.isdigit() and len(code) == 5:
        return "hk", "港股"
    if not code.isdigit():
        return "us", "美股"
    return "sz", "A股"


__all__ = [
    "EASTMONEY_SYMBOLS_PARAMS_SCHEMA",
    "EASTMONEY_SYMBOLS_URL_TEMPLATE",
    "MARKET_PREFIXES",
    "EastmoneySymbolsProvider",
    "fs_for_market",
    "market_for_symbol",
    "normalize_market",
]

if TYPE_CHECKING:
    _contract: SourceProvider = EastmoneySymbolsProvider()
