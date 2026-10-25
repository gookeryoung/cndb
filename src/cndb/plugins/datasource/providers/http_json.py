"""内置 provider：``http_json`` —— 声明式通用 HTTP/JSON 数据源.

一次 ``SyncJobSpec`` 会被展开成一组请求：
``entrant × 时间窗口 × 页码``，每个请求的 URL / headers / params / body 由模板求值得到。

- 分页：``page``（页码递增）/ ``offset``（偏移量递增），``none`` 表示单页；
- 时间分片：``time_window.chunk_days > 0`` 时按天切段，逐段抓取后合并；
- 解析：JSON + ``data_path``（缺省时按 data / items / results 等常见键探测）；
- 归一：字段映射 + 类型归一，委托 ``services/normalize.py``。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from cndb.plugins.datasource.providers.base import (
    CursorStrategy,
    PagingSpec,
    ProviderError,
    RequestPlan,
    RequestSpec,
    SourceProvider,
    SyncJobSpec,
    TimeWindowSpec,
)
from cndb.plugins.datasource.providers.template import render_text, render_value
from cndb.plugins.datasource.services.normalize import NormalizeResult, apply_field_mapping
from cndb.plugins.tables.services.importing.api_fetch import (
    FetchConfig,
    ResponseHandler,
    _extract_array,
    _resolve_path,
)

# 供前端动态渲染的表单描述（M3 的「新建向导」消费）
HTTP_JSON_PARAMS_SCHEMA: dict[str, Any] = {
    "fields": [
        {"name": "url_template", "type": "text", "required": True, "label": "URL 模板"},
        {"name": "method", "type": "select", "options": ["GET", "POST"], "default": "GET"},
        {"name": "headers_template", "type": "json", "label": "请求头模板"},
        {"name": "params_template", "type": "json", "label": "查询参数模板"},
        {"name": "body_template", "type": "json", "label": "请求体模板"},
        {"name": "data_path", "type": "text", "label": "响应数组路径（a.b.c）"},
        {"name": "encoding", "type": "text", "default": "utf-8"},
    ],
    "placeholders": ["entrant", "start", "end", "page", "page_size", "offset"],
}


class HttpJsonProvider:
    """通用 REST / JSON provider（声明式优先路径，覆盖大多数天气 / 新闻 / 行情源）."""

    name = "http_json"
    label = "通用 HTTP/JSON"
    params_schema: Mapping[str, Any] = HTTP_JSON_PARAMS_SCHEMA
    default_cursor: CursorStrategy = "date"
    supports_paging = True
    # 覆写了 parse 的专用 provider 置 True：抓取时把原始文本交给自身 parse，
    # 否则 fetch_json 的通用数组探测会把嵌套结构（腾讯 / 东财）解析成错误的一行
    uses_custom_parse = False

    def build_requests(self, job: SyncJobSpec) -> list[RequestPlan]:
        """展开为具体请求列表（entrant × 窗口 × 页码，顺序稳定便于断言）.

        ``job.entrant_ends``（backfill_date 游标，ADR 0034 D2）非空时，
        该标的的 ``{end}`` 模板变量注入其专属锚点（水位 − 1 天），
        不出现在映射里的标的无锚点（历史配置零影响）。
        """
        spec = job.request
        handler = self.response_handler_for(job)
        plans: list[RequestPlan] = []
        # 标的集合已解析为空（回补全达标 / 清单尚无行）→ 零请求；未声明标的才发单条请求
        values: tuple[str | None, ...] = () if job.entrants_exhausted else (job.entrant_values or (None,))
        for entrant in values:
            entrant_end = job.entrant_ends.get(entrant) if (job.entrant_ends and entrant is not None) else None
            for window_start, window_end in iter_windows(spec.time_window):
                for page in iter_pages(spec.paging):
                    variables = self._variables(job, entrant, window_start, window_end, page, entrant_end)
                    plans.append(
                        RequestPlan(
                            config=self._build_config(spec, variables, handler),
                            label=_label(job, entrant, window_start, window_end, page),
                            entrant=entrant,
                            page=page,
                            window_start=window_start,
                            window_end=window_end or entrant_end,
                        )
                    )
        return plans

    def response_handler_for(self, job: SyncJobSpec) -> ResponseHandler | None:
        """返回响应处理器：专用 provider 用自己的 ``parse`` 处理原始文本.

        ``rows_array`` 模式也必须走自定义 handler——通用 ``fetch_json`` 的数组探测
        会把「数组的数组」过滤成空行。
        """
        if not (self.uses_custom_parse or job.request.record_mode == "rows_array"):
            return None

        def handler(text: str, config: FetchConfig) -> list[dict[str, Any]]:
            # data_path 已在 _build_config 按标的渲染，交给 parse 覆盖原始模板
            return self.parse(text, job, data_path=config.data_path)

        return handler

    def parse(self, text: str, job: SyncJobSpec, *, data_path: str | None = None) -> list[dict[str, Any]]:
        """响应文本 → 对象数组（JSON 解析失败即 ProviderError，不静默返回空）.

        ``data_path`` 显式给出时优先（请求构造阶段已把 ``{entrant}`` 等模板求值），
        否则用 job 声明里的原样路径。
        """
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(f"响应不是合法 JSON: {exc}") from exc
        spec = job.request
        path = data_path if data_path is not None else spec.data_path
        if spec.record_mode == "columns":
            return columns_to_rows(payload, path, spec.record_layout)
        if spec.record_mode == "rows_array":
            return rows_array_to_rows(payload, path, spec.record_layout)
        return _extract_array(payload, path, True)

    def normalize(self, rows: Sequence[Mapping[str, Any]], job: SyncJobSpec) -> NormalizeResult:
        """字段映射 + 类型归一."""
        return apply_field_mapping(rows, job.field_mapping)

    # ── 内部 ─────────────────────────────────────
    def _variables(
        self,
        job: SyncJobSpec,
        entrant: str | None,
        window_start: str | None,
        window_end: str | None,
        page: int | None,
        entrant_end: str | None = None,
    ) -> dict[str, Any]:
        spec = job.request
        # 会话密钥等额外变量先铺底，内置变量（entrant / 窗口 / 分页）随后覆盖
        variables: dict[str, Any] = dict(job.extra_variables)
        if job.entrant_param:
            variables[job.entrant_param] = entrant
        variables["entrant"] = entrant
        if window_start is not None and window_end is not None:
            variables[spec.time_window.start_param] = window_start
            variables[spec.time_window.end_param] = window_end
            variables["start"] = window_start
            variables["end"] = window_end
        elif entrant_end is not None:
            # backfill_date 锚点（ADR 0034 D2）：无窗口区间时只注入 end（start 位由模板留空）
            variables[spec.time_window.end_param] = entrant_end
            variables["end"] = entrant_end
        if page is not None:
            paging = spec.paging
            offset = (page - paging.start_page) * paging.page_size
            # offset 模式下 page_param 承载的是偏移量（常见 API 用 ?offset=），否则是页码
            variables[paging.page_param] = offset if paging.mode == "offset" else page
            variables[paging.size_param] = paging.page_size
            variables["page"] = page
            variables["page_size"] = paging.page_size
            variables["offset"] = offset
        return variables

    def _build_config(
        self,
        spec: RequestSpec,
        variables: Mapping[str, Any],
        response_handler: ResponseHandler | None = None,
    ) -> FetchConfig:
        headers = {key: render_text(value, variables) for key, value in spec.headers_template.items()}
        return FetchConfig(
            url=render_text(spec.url_template, variables),
            method=spec.method,
            headers=headers,
            params=render_value(dict(spec.params_template), variables),
            body=render_value(spec.body_template, variables),
            timeout=spec.timeout,
            data_path=render_text(spec.data_path, variables) if spec.data_path else None,
            encoding=spec.encoding,
            response_handler=response_handler or "json",
        )


def columns_to_rows(
    payload: Any,
    data_path: str | None = None,
    layout: Mapping[str, str | int] | None = None,
) -> list[dict[str, Any]]:
    """把「列名 → 数组」的响应拼成行（逐索引 zip，缺值补 None）.

    ``layout`` 给出时按 ``{目标列名: 源键}`` 取列，否则把目标对象下所有数组键都当列。
    """
    node: Any = _resolve_path(payload, data_path) if data_path else payload
    if not isinstance(node, dict):
        raise ProviderError("列式记录要求 data_path 指向一个对象（列名 → 数组）")
    columns: dict[str, list[Any]] = {}
    if layout:
        for target, source in layout.items():
            series = node.get(str(source))
            if not isinstance(series, list):
                raise ProviderError(f"列式记录缺少数组列: {source}")
            columns[target] = series
    else:
        for key, value in node.items():
            if isinstance(value, list):
                columns[key] = value
    if not columns:
        raise ProviderError("列式记录未找到任何数组列")
    width = max(len(series) for series in columns.values())
    rows: list[dict[str, Any]] = []
    for index in range(width):
        rows.append({name: (series[index] if index < len(series) else None) for name, series in columns.items()})
    return rows


def rows_array_to_rows(
    payload: Any,
    data_path: str | None = None,
    layout: Mapping[str, str | int] | None = None,
) -> list[dict[str, Any]]:
    """把「行数组的数组」响应拼成对象数组（按 ``layout`` 的位置索引取值）.

    ``layout`` 形如 ``{"日期": 0, "开盘": 1}``：目标列名 → 行内元素下标。
    行长度不足最大下标时该字段补 ``None``（不丢行）；``data_path`` 未命中数组即报错。

    Raises:
        ProviderError: ``data_path`` 未指向数组、行不是数组、下标非法.
    """
    node: Any = _resolve_path(payload, data_path) if data_path else payload
    if not isinstance(node, list):
        raise ProviderError("行数组记录要求 data_path 指向一个数组")
    positions = _layout_positions(layout)
    rows: list[dict[str, Any]] = []
    for item in node:
        if not isinstance(item, list):
            raise ProviderError(f"行数组记录的元素必须是数组，实际为 {type(item).__name__}")
        rows.append({name: (item[index] if index < len(item) else None) for name, index in positions.items()})
    return rows


def _layout_positions(layout: Mapping[str, str | int] | None) -> dict[str, int]:
    """把 ``rows_array`` 的布局声明规范为 ``{目标列名: 位置索引}``（接受数字字符串）."""
    if not layout:
        raise ProviderError("rows_array 模式必须声明 record_layout（目标列名 → 位置索引）")
    positions: dict[str, int] = {}
    for name, raw in layout.items():
        if isinstance(raw, bool):
            raise ProviderError(f"record_layout[{name!r}] 的位置索引不能是布尔值")
        if isinstance(raw, int):
            index = raw
        else:
            try:
                index = int(raw.strip())
            except (TypeError, ValueError) as exc:
                raise ProviderError(f"record_layout[{name!r}] 的位置索引必须是整数: {raw!r}") from exc
        if index < 0:
            raise ProviderError(f"record_layout[{name!r}] 的位置索引不能为负: {index}")
        positions[name] = index
    return positions


def iter_windows(spec: TimeWindowSpec) -> list[tuple[str | None, str | None]]:
    """把时间区间展开为窗口列表；``chunk_days`` > 0 时按天切片（含端点）."""
    if spec.mode == "none":
        return [(None, None)]
    start = _parse_day(spec.start)
    end = _parse_day(spec.end)
    if end < start:
        raise ProviderError(f"time_window 的 end({spec.end}) 早于 start({spec.start})")
    if spec.chunk_days <= 0:
        return [(_format_day(start, spec.date_format), _format_day(end, spec.date_format))]
    windows: list[tuple[str | None, str | None]] = []
    cursor = start
    step = timedelta(days=spec.chunk_days - 1)
    while cursor <= end:
        chunk_end = min(cursor + step, end)
        windows.append((_format_day(cursor, spec.date_format), _format_day(chunk_end, spec.date_format)))
        cursor = chunk_end + timedelta(days=1)
    return windows


def iter_pages(spec: PagingSpec) -> list[int | None]:
    """把分页配置展开为页码列表（``none`` → ``[None]``）."""
    if spec.mode == "none":
        return [None]
    return list(range(spec.start_page, spec.start_page + spec.max_pages))


def _label(
    job: SyncJobSpec,
    entrant: str | None,
    window_start: str | None,
    window_end: str | None,
    page: int | None,
) -> str:
    parts: list[str] = []
    if job.entrant_param and entrant is not None:
        parts.append(f"{job.entrant_param}={entrant}")
    if window_start is not None and window_end is not None:
        parts.append(f"{window_start}~{window_end}")
    if page is not None:
        parts.append(f"page={page}")
    return " ".join(parts) if parts else "single"


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ProviderError(f"时间区间必须是 ISO 日期（YYYY-MM-DD）: {value!r}") from exc


def _format_day(value: date, fmt: str) -> str:
    return value.strftime(fmt)


__all__ = [
    "HTTP_JSON_PARAMS_SCHEMA",
    "HttpJsonProvider",
    "columns_to_rows",
    "iter_pages",
    "iter_windows",
    "rows_array_to_rows",
]

if TYPE_CHECKING:
    # 类型检查期验证实现满足 SourceProvider 协议（运行期零开销）
    _contract: SourceProvider = HttpJsonProvider()
