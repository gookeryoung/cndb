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
from cndb.plugins.tables.services.importing.api_fetch import FetchConfig, _extract_array

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

    def build_requests(self, job: SyncJobSpec) -> list[RequestPlan]:
        """展开为具体请求列表（entrant × 窗口 × 页码，顺序稳定便于断言）."""
        spec = job.request
        plans: list[RequestPlan] = []
        for entrant in job.entrant_values or (None,):
            for window_start, window_end in iter_windows(spec.time_window):
                for page in iter_pages(spec.paging):
                    variables = self._variables(job, entrant, window_start, window_end, page)
                    plans.append(
                        RequestPlan(
                            config=self._build_config(spec, variables),
                            label=_label(job, entrant, window_start, window_end, page),
                            entrant=entrant,
                            page=page,
                            window_start=window_start,
                            window_end=window_end,
                        )
                    )
        return plans

    def parse(self, text: str, job: SyncJobSpec) -> list[dict[str, Any]]:
        """响应文本 → 对象数组（JSON 解析失败即 ProviderError，不静默返回空）."""
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(f"响应不是合法 JSON: {exc}") from exc
        return _extract_array(payload, job.request.data_path, True)

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
    ) -> dict[str, Any]:
        spec = job.request
        variables: dict[str, Any] = {}
        if job.entrant_param:
            variables[job.entrant_param] = entrant
        variables["entrant"] = entrant
        if window_start is not None and window_end is not None:
            variables[spec.time_window.start_param] = window_start
            variables[spec.time_window.end_param] = window_end
            variables["start"] = window_start
            variables["end"] = window_end
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

    def _build_config(self, spec: RequestSpec, variables: Mapping[str, Any]) -> FetchConfig:
        headers = {key: render_text(value, variables) for key, value in spec.headers_template.items()}
        return FetchConfig(
            url=render_text(spec.url_template, variables),
            method=spec.method,
            headers=headers,
            params=render_value(dict(spec.params_template), variables),
            body=render_value(spec.body_template, variables),
            timeout=spec.timeout,
            data_path=spec.data_path,
            encoding=spec.encoding,
        )


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


__all__ = ["HTTP_JSON_PARAMS_SCHEMA", "HttpJsonProvider", "iter_pages", "iter_windows"]

if TYPE_CHECKING:
    # 类型检查期验证实现满足 SourceProvider 协议（运行期零开销）
    _contract: SourceProvider = HttpJsonProvider()
