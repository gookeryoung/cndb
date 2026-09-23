"""API 摄取编排 — 抓 API → 推断列 → 建表 → 导入 的一站式入口."""

from __future__ import annotations

from typing import Any

from cndb.plugins.tables.services.transfer.table_create import analyze_json_columns, create_table_from_json_data


def ingest_from_api(
    engine: Any,
    db: Any,
    workspace_id: int,
    table_name: str,
    *,
    api_url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    body: Any = None,
    data_path: str | None = None,
    timeout: float = 15.0,
    response_handler: str | Any = "json",
    encoding: str = "utf-8",
    query_interval: float | None = None,
    owner_id: int | None = None,
) -> tuple[Any, list[int], list[dict[str, Any]]]:
    """一站式：抓 API → 推断列 → 建表 → 导入.

    Args:
        response_handler: "json" (默认) / "tencent_stock" / 自定义 callable
        encoding: 响应编码，默认 utf-8（腾讯股票用 gbk）
        query_interval: 查询间隔秒数，None 时用 DEFAULT_QUERY_INTERVAL

    Returns:
        (DataTable, 新行 id 列表, 列信息)
    """
    from cndb.plugins.tables.services.importing.api_fetch import (
        DEFAULT_QUERY_INTERVAL,
        FetchConfig,
        fetch_json,
        validate_query_interval,
    )

    qi = validate_query_interval(query_interval) if query_interval is not None else DEFAULT_QUERY_INTERVAL

    rows = fetch_json(
        FetchConfig(
            url=api_url,
            method=method,
            headers=headers or {},
            params=params or {},
            body=body,
            timeout=timeout,
            data_path=data_path,
            response_handler=response_handler,
            encoding=encoding,
            query_interval=qi,
        )
    )

    if not rows:
        raise ValueError("API 未返回有效对象数组")

    columns = analyze_json_columns(rows)
    dt, ids = create_table_from_json_data(engine, db, workspace_id, table_name, rows, owner_id=owner_id)
    return dt, ids, columns
