"""标的动态来源解析（ADR 0034 D3）.

职责边界：

- 解析 ``entrant_source``：查同工作区数据表目标字段 distinct 值，可按前缀过滤；
- 与静态 ``entrant_keys`` 并集去重。

与领域无关：标的叫 ``entrant``，来源表 / 字段 / 前缀全部由 job 配置声明。
"""

from __future__ import annotations

import logging

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from cndb.plugins.datasource.models import DatasourceSyncJob

logger = logging.getLogger(__name__)


def resolve_entrant_values(
    db: Session,
    job: DatasourceSyncJob,
) -> tuple[str, ...]:
    """解析任务标的集合：``entrant_source`` 动态来源 distinct 值 + 静态 ``entrant_keys`` 并集.

    动态来源声明 ``{"table": 表名, "field": 字段名, "prefix_in": [前缀, ...]?}``；
    来源表 / 字段不存在时抛 ``ValueError``（由 runner 落成 failed 运行记录，
    不静默空跑）；声明存在但表无行时返回空动态集（清单尚未首拉属正常启动顺序）。
    """
    values: list[str] = list(job.entrant_keys or ())
    source = job.entrant_source
    if not source:
        return tuple(dict.fromkeys(values))

    from cndb.plugins.tables.models import DataTable

    table_name = str(source.get("table") or "").strip()
    field_name = str(source.get("field") or "").strip()
    if not table_name or not field_name:
        raise ValueError("entrant_source 必须同时声明 table 与 field")
    table = db.execute(
        select(DataTable).where(
            DataTable.workspace_id == job.workspace_id,
            DataTable.name == table_name,
        )
    ).scalar_one_or_none()
    if table is None:
        raise ValueError(f"entrant_source 指向的表不存在: {table_name!r}")
    field = next((item for item in table.active_fields() if item.name == field_name), None)
    if field is None:
        raise ValueError(f"entrant_source 指向的字段不存在: {table_name}.{field_name}")

    statement = text(f'SELECT DISTINCT "{field.db_column_name}" FROM "{table.db_table_name}"')
    rows = db.execute(statement).scalars().all()
    prefixes = tuple(str(item) for item in (source.get("prefix_in") or ()) if str(item))
    seen: dict[str, None] = dict.fromkeys(values)
    for raw in rows:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        if prefixes and not value.startswith(prefixes):
            continue
        seen[value] = None
    dynamic = len(seen) - len(values)
    if dynamic:
        logger.info("任务 %s 从 %s.%s 解析出 %d 个动态标的", job.id, table_name, field_name, dynamic)
    return tuple(seen)


__all__ = ["resolve_entrant_values"]
