"""内置 provider：``baostock_kline`` —— baostock（证券宝）A 股日线.

与其它内置 provider 的关键差异：**不走 HTTP**。baostock 是 Python 库 + 全局 TCP
会话（``bs.login()`` / ``query_history_k_data_plus``），因此本 provider 实现
``fetch_plan(plan)`` 自带传输通道，管线检测到该方法即跳过 ``fetch_json``。

任务声明的 ``url_template`` 用伪协议承载参数（不走网络，只作为配置载体）::

    baostock://kline?frequency=d&adjustflag=2

- ``frequency``：``d`` 日线 / ``w`` 周线 / ``m`` 月线
- ``adjustflag``：``1`` 后复权 / ``2`` 前复权 / ``3`` 不复权（baostock 原生口径）
- ``{symbol}`` / ``{start}`` / ``{end}`` 占位符由 ``entrant_keys`` 与时间窗口注入

输出字段：``symbol``（``sh600519`` 风格，与示例表一致）/ ``trade_date`` /
``open`` / ``high`` / ``low`` / ``close`` / ``volume``（股）/ ``amount``（元）。

注意：baostock 一次调用即可返回完整区间（无 320 / 1023 根上限），是长历史回填首选；
依赖为可选 extra（``uv sync --extra market``），缺失时给出安装提示。
"""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import threading
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, override
from urllib.parse import parse_qs, urlparse

from cndb.plugins.datasource.providers.base import (
    FieldTransform,
    ProviderError,
    RequestPlan,
    SourceProvider,
    SyncJobSpec,
)
from cndb.plugins.datasource.providers.http_json import HttpJsonProvider
from cndb.plugins.datasource.services.normalize import NormalizeResult, apply_field_mapping

logger = logging.getLogger(__name__)

BAOSTOCK_KLINE_URL_TEMPLATE = "baostock://kline?frequency=d&adjustflag=2"

BAOSTOCK_KLINE_PARAMS_SCHEMA: dict[str, Any] = {
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
            "label": "参数载体（baostock://kline?frequency=d&adjustflag=2）",
            "default": BAOSTOCK_KLINE_URL_TEMPLATE,
        },
    ],
    "placeholders": ["symbol", "start", "end"],
    "notes": "adjustflag: 1=后复权 2=前复权 3=不复权；一次调用可返回完整区间，无根数上限。",
}

# 查询字段：与表内列一一对应（amount 成交额 baostock 独有）
_QUERY_FIELDS = "date,code,open,high,low,close,volume,amount"

_FIELD_MAP = {
    "date": "trade_date",
    "code": "symbol",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
}

# baostock 的全局会话句柄：登录一次复用，查询异常时重登
# 用 dict 承载状态而非模块级 bool，避免到处 global（ruff PLW0603）
_session_lock = threading.Lock()
_state: dict[str, bool] = {"logged_in": False}


def _to_baostock_symbol(symbol: str) -> str:
    """``sh600519`` / ``600519.SH`` → baostock 的 ``sh.600519``."""
    value = symbol.strip()
    if "." in value:
        left, _, right = value.partition(".")
        if left.isdigit():  # 600519.SH
            return f"{right.lower()}.{left}"
        return f"{left.lower()}.{right}"  # 已是 sh.600519
    if len(value) > 2 and value[:2].lower() in ("sh", "sz", "bj"):
        return f"{value[:2].lower()}.{value[2:]}"
    raise ProviderError(f"无法识别的股票代码: {symbol!r}（支持 sh600519 / 600519.SH）")


def _from_baostock_symbol(code: str) -> str:
    """``sh.600519`` → ``sh600519``（表内口径，无点）."""
    prefix, _, digits = code.partition(".")
    return f"{prefix.lower()}{digits}" if digits else code


def _login() -> Any:
    """惰性登录；进程内复用同一 TCP 会话."""
    with _session_lock:
        bs = _bs_module()
        if _state["logged_in"]:
            return bs
        result = bs.login()
        if getattr(result, "error_code", "1") != "0":
            raise ProviderError(
                f"baostock 登录失败: {getattr(result, 'error_code', '?')} {getattr(result, 'error_msg', '')}"
            )
        _state["logged_in"] = True
        return bs


def _bs_module() -> Any:
    try:
        import baostock as bs
    except ImportError as exc:  # pragma: no cover - 依赖缺失时给出可执行提示
        raise ProviderError("缺少 baostock 依赖：请执行 uv sync --extra market（或 pip install baostock）") from exc
    return bs


def _logout() -> None:  # pragma: no cover - 进程退出钩子
    with _session_lock:
        if not _state["logged_in"]:
            return
        # 退出阶段的清理失败不影响主流程
        with contextlib.suppress(Exception):
            _bs_module().logout()
        _state["logged_in"] = False


atexit.register(_logout)


class BaostockKlineProvider(HttpJsonProvider):
    """A 股日线（baostock TCP 传输）：一次查询返回完整区间."""

    name = "baostock_kline"
    label = "baostock A 股日线（前 / 后 / 不复权）"
    params_schema: Mapping[str, Any] = BAOSTOCK_KLINE_PARAMS_SCHEMA
    default_cursor = "date"
    supports_paging = False

    def fetch_plan(self, plan: RequestPlan) -> list[dict[str, Any]]:
        """自带传输：直接查 baostock，返回原始行（键为统一字段名）."""
        variables = dict(plan.variables)
        symbol = variables.get("symbol") or plan.entrant
        if not symbol:
            raise ProviderError("baostock 任务缺少 symbol（entrant_param + entrant_keys）")
        start = str(variables.get("start") or "")
        end = str(variables.get("end") or "")
        if not start or not end:
            raise ProviderError("baostock 任务必须配置 time_window（range + start/end 占位）")
        frequency, adjustflag = _parse_transport_options(str(plan.config.url))
        return self.query(str(symbol), start=start, end=end, frequency=frequency, adjustflag=adjustflag)

    def query(
        self,
        symbol: str,
        *,
        start: str,
        end: str,
        frequency: str = "d",
        adjustflag: str = "2",
    ) -> list[dict[str, Any]]:
        """查询一只标的的区间日线（可在子类 / 单测中覆写，避免联网）."""
        bs = _login()
        result = bs.query_history_k_data_plus(
            _to_baostock_symbol(symbol),
            _QUERY_FIELDS,
            start_date=start,
            end_date=end,
            frequency=frequency,
            adjustflag=adjustflag,
        )
        if getattr(result, "error_code", "1") != "0":
            _state["logged_in"] = False  # 会话可能已断，下次重登
            raise ProviderError(f"baostock 查询失败: {result.error_code} {result.error_msg}")
        rows: list[dict[str, Any]] = []
        while result.next():
            record = dict(zip(result.fields, result.get_row_data(), strict=False))
            row = {target: record.get(source) for source, target in _FIELD_MAP.items()}
            if row.get("symbol"):
                row["symbol"] = _from_baostock_symbol(str(row["symbol"]))
            if row.get("trade_date"):
                rows.append(row)
        return rows

    @override
    def parse(self, text: str, job: SyncJobSpec) -> list[dict[str, Any]]:
        """兜底：允许离线导入 baostock 查询结果导出的 JSON 数组."""
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(f"响应不是合法 JSON: {exc}") from exc
        if not isinstance(payload, list):
            raise ProviderError("baostock 离线数据必须是行数组")
        return [dict(item) for item in payload if isinstance(item, dict)]

    @override
    def normalize(self, rows: Sequence[Mapping[str, Any]], job: SyncJobSpec) -> NormalizeResult:
        """未配置字段映射时按日线语义默认归类（日期 / 数值）."""
        if job.field_mapping:
            return apply_field_mapping(rows, job.field_mapping)
        default_mapping = {
            "trade_date": FieldTransform(name="trade_date", field_type="date"),
            "open": FieldTransform(name="open", field_type="float"),
            "close": FieldTransform(name="close", field_type="float"),
            "high": FieldTransform(name="high", field_type="float"),
            "low": FieldTransform(name="low", field_type="float"),
            "volume": FieldTransform(name="volume", field_type="int"),
            "amount": FieldTransform(name="amount", field_type="float"),
        }
        return apply_field_mapping(rows, default_mapping)


def _parse_transport_options(url: str) -> tuple[str, str]:
    """从 ``baostock://kline?frequency=d&adjustflag=2`` 取传输参数."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    frequency = (query.get("frequency") or ["d"])[0] or "d"
    adjustflag = (query.get("adjustflag") or ["2"])[0] or "2"
    if frequency not in ("d", "w", "m"):
        raise ProviderError(f"baostock frequency 仅支持 d/w/m: {frequency!r}")
    if adjustflag not in ("1", "2", "3"):
        raise ProviderError(f"baostock adjustflag 仅支持 1/2/3: {adjustflag!r}")
    return frequency, adjustflag


__all__ = [
    "BAOSTOCK_KLINE_PARAMS_SCHEMA",
    "BAOSTOCK_KLINE_URL_TEMPLATE",
    "BaostockKlineProvider",
]

if TYPE_CHECKING:
    _contract: SourceProvider = BaostockKlineProvider()
