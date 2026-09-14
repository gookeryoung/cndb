"""API 建表配置文件加载器 — 从 JSON 配置批量建表.

JSON 配置文件格式（.json）：

```json
{
  "tables": [
    {
      "table_name": "股票实时行情",
      "description": "10支典型A股的腾讯实时快照",
      "fetch": {
        "url": "https://qt.gtimg.cn/q=sh600519,sz000001,...",
        "method": "GET",
        "headers": {"User-Agent": "Mozilla/5.0"},
        "response_handler": "tencent_stock",
        "encoding": "gbk",
        "query_interval": 60
      }
    }
  ]
}
```

顶层：
- `tables`: 数组，每项一个表定义

每个表定义：
- `table_name` (必填): 新建表的中文名称
- `description` (可选): 表描述
- `fetch` (必填): API 抓取配置
  - `url` (必填): API URL
  - `method` (可选): HTTP 方法，默认 GET
  - `headers` (可选): 请求头 dict
  - `params` (可选): URL 查询参数 dict
  - `body` (可选): 请求体
  - `timeout` (可选): 超时秒数，默认 15
  - `data_path` (可选): 响应路径（JSON 模式）
  - `response_handler` (可选): "json" | "tencent_stock" | 自定义
  - `encoding` (可选): 响应编码，默认 utf-8
  - `query_interval` (可选): 查询间隔秒数，默认 60（最短 6）
- `field_mapping` (可选): 字段重命名/类型覆盖
  - `{原字段名: {name: "新名", field_type: "float"}}`
- `views` (可选): 视图定义（同 views.json 格式）
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from cndb.plugins.tables.api_fetch import (
    DEFAULT_QUERY_INTERVAL,
    MIN_QUERY_INTERVAL,
    RESPONSE_HANDLERS,
    FetchConfig,
    validate_query_interval,
)

logger = logging.getLogger(__name__)


class ApiConfigError(ValueError):
    """API 配置文件解析 / 校验错误."""


# ── 配置文件校验 ─────────────────────────────────


def validate_api_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    """校验 API 配置文件结构并返回表定义列表.

    Raises:
        ApiConfigError: 校验不通过
    """
    if not isinstance(config, dict):
        raise ApiConfigError("配置文件顶层必须是对象")

    tables = config.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ApiConfigError("缺少有效的 tables 数组")

    validated: list[dict[str, Any]] = []
    table_names: set[str] = set()

    for idx, tbl in enumerate(tables):
        if not isinstance(tbl, dict):
            raise ApiConfigError(f"tables[{idx}] 必须是对象")

        name = tbl.get("table_name")
        if not name or not isinstance(name, str):
            raise ApiConfigError(f"tables[{idx}] 缺少 table_name")

        if name in table_names:
            raise ApiConfigError(f"table_name 重复: {name}")
        table_names.add(name)

        fetch = tbl.get("fetch")
        if not isinstance(fetch, dict):
            raise ApiConfigError(f"tables[{idx}].fetch 必须是对象")

        url = fetch.get("url")
        if not url or not isinstance(url, str):
            raise ApiConfigError(f"tables[{idx}].fetch.url 必须是非空字符串")

        # 校验 response_handler
        handler = fetch.get("response_handler", "json")
        if isinstance(handler, str) and handler != "json" and handler not in RESPONSE_HANDLERS:
            raise ApiConfigError(
                f"tables[{idx}].fetch.response_handler={handler!r} 未注册，可选: 'json', {list(RESPONSE_HANDLERS)}"
            )

        # 校验 query_interval
        interval = fetch.get("query_interval", DEFAULT_QUERY_INTERVAL)
        if isinstance(interval, (int, float)) and interval < MIN_QUERY_INTERVAL:
            logger.warning(
                "table '%s' query_interval=%.1fs 低于最小值 %.1fs，将被夹取",
                name,
                interval,
                MIN_QUERY_INTERVAL,
            )

        validated.append(tbl)

    return validated


def build_fetch_config(table_def: dict[str, Any]) -> FetchConfig:
    """从表定义构建 FetchConfig."""
    fetch = table_def["fetch"]
    return FetchConfig(
        url=fetch["url"],
        method=fetch.get("method", "GET"),
        headers=fetch.get("headers") or {},
        params=fetch.get("params") or {},
        body=fetch.get("body"),
        timeout=float(fetch.get("timeout", 15)),
        data_path=fetch.get("data_path"),
        response_handler=fetch.get("response_handler", "json"),
        encoding=fetch.get("encoding", "utf-8"),
        query_interval=validate_query_interval(fetch.get("query_interval", DEFAULT_QUERY_INTERVAL)),
    )


def load_api_config_file(path: Path | str) -> list[dict[str, Any]]:
    """从 .json 文件加载并校验 API 建表配置."""
    p = Path(path)
    if not p.is_file():
        raise ApiConfigError(f"配置文件不存在: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ApiConfigError(f"配置文件解析失败 {p}: {exc}") from exc
    return validate_api_config(raw)


def load_api_config_text(text: str) -> list[dict[str, Any]]:
    """从 JSON 字符串加载并校验 API 建表配置."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ApiConfigError(f"JSON 解析失败: {exc}") from exc
    return validate_api_config(raw)


# ── 批量建表执行器 ─────────────────────────────────


def ingest_tables_from_config(
    engine: Any,
    db: Any,
    workspace_id: int,
    table_defs: list[dict[str, Any]],
    owner_id: int | None = None,
) -> list[dict[str, Any]]:
    """按配置批量建表 + 导入数据.

    Returns:
        每张表的结果 [{table_name, table_id, imported_rows, field_count, query_interval}, ...]

    Raises:
        ApiConfigError: 配置问题
        ValueError: 建表/导入失败
    """
    from cndb.plugins.tables.transfer import ingest_from_api

    results: list[dict[str, Any]] = []

    for table_def in table_defs:
        fetch_cfg = build_fetch_config(table_def)
        table_name = table_def["table_name"]

        logger.info(
            "[api-config] 建表: %s (handler=%s, interval=%.0fs)",
            table_name,
            fetch_cfg.response_handler,
            fetch_cfg.query_interval,
        )

        dt, ids, columns = ingest_from_api(
            engine,
            db,
            workspace_id,
            table_name,
            api_url=fetch_cfg.url,
            method=fetch_cfg.method,
            headers=fetch_cfg.headers,
            params=fetch_cfg.params,
            body=fetch_cfg.body,
            data_path=fetch_cfg.data_path,
            timeout=fetch_cfg.timeout,
            owner_id=owner_id,
        )

        results.append(
            {
                "table_name": table_name,
                "table_id": dt.id,
                "imported_rows": len(ids),
                "field_count": len(columns),
                "query_interval": fetch_cfg.query_interval,
            }
        )

    return results


__all__ = [
    "ApiConfigError",
    "build_fetch_config",
    "ingest_tables_from_config",
    "load_api_config_file",
    "load_api_config_text",
    "validate_api_config",
]
