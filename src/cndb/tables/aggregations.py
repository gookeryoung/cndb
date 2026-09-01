"""聚合统计：按视图筛选规则对行数据做分组聚合.

聚合函数走封闭集合并按字段类型约束（sum/avg 仅数值），分组列与聚合列
全部经元数据白名单映射为系统生成的物理列名，聚合值由数据库计算。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import connection

from cndb.tables.field_types import get_field_type
from cndb.tables.models import DataTable
from cndb.tables.query import RowQuery
from cndb.tables.sql import quote

# 聚合函数集合
AGG_FUNCS = frozenset({"count", "sum", "avg", "min", "max"})
# 各字段类型允许的聚合函数
_AGG_BY_FIELD_TYPE: dict[str, frozenset[str]] = {
    "number": frozenset({"count", "sum", "avg", "min", "max"}),
    "date": frozenset({"count", "min", "max"}),
    "text": frozenset({"count", "min", "max"}),
    "long_text": frozenset({"count", "min", "max"}),
    "email": frozenset({"count", "min", "max"}),
    "url": frozenset({"count", "min", "max"}),
    "single_select": frozenset({"count", "min", "max"}),
    "boolean": frozenset({"count"}),
    "multi_select": frozenset({"count"}),
}
_SQL_FUNC = {"count": "COUNT", "sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX"}


class InvalidAggregationError(Exception):
    """聚合请求非法（未知字段/函数/类型不支持）."""


@dataclass
class AggSpec:
    """聚合请求：分组字段名（None 为整体聚合）与字段到聚合函数的映射."""

    group_by: str | None = None
    aggs: dict[str, str] = field(default_factory=dict)


def parse_aggregations(table: DataTable, params: Mapping[str, Any]) -> AggSpec:
    """解析 group_by 与 agg__<字段>=<函数> 参数为聚合请求."""
    fields = {str(f.name): f for f in table.active_fields()}
    group_by = params.get("group_by") or None
    if group_by is not None:
        if group_by == "id":
            raise InvalidAggregationError("分组字段不支持 id")
        if group_by not in fields:
            raise InvalidAggregationError(f"未知分组字段: {group_by}")
    aggs: dict[str, str] = {}
    for key, value in params.items():
        if not key.startswith("agg__"):
            continue
        field_name = key[len("agg__") :]
        target = fields.get(field_name)
        if target is None:
            raise InvalidAggregationError(f"未知聚合字段: {field_name}")
        func = str(value)
        if func not in AGG_FUNCS:
            raise InvalidAggregationError(f"不支持的聚合函数: {func}")
        allowed = _AGG_BY_FIELD_TYPE.get(str(target.field_type), frozenset({"count"}))
        if func not in allowed:
            raise InvalidAggregationError(f"字段 {field_name} 不支持 {func} 聚合")
        aggs[field_name] = func
    return AggSpec(group_by=group_by, aggs=aggs)


def _to_decimal(value: Any) -> Decimal | None:
    """把数据库返回的数值统一为 Decimal，空聚合返回 None."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def fetch_aggregations(table: DataTable, spec: RowQuery, agg: AggSpec) -> dict[str, Any]:
    """按筛选条件执行分组聚合，返回 {group_by, results: [{value, count, aggregations}]}.

    无分组时 results 仅一个元素，value 为 None。
    """
    fields = {str(f.name): f for f in table.active_fields()}
    select_parts = [f"COUNT(*) AS {quote('row_count')}"]
    group_column = ""
    if agg.group_by is not None:
        group_field = fields[agg.group_by]
        group_column = str(group_field.db_column_name)
        select_parts.append(f"{quote(group_column)} AS {quote('group_value')}")
    for index, (field_name, func) in enumerate(agg.aggs.items()):
        column = str(fields[field_name].db_column_name)
        select_parts.append(f"{_SQL_FUNC[func]}({quote(column)}) AS {quote(f'agg_{index}')}")
    sql = f"SELECT {', '.join(select_parts)} FROM {quote(table.db_table_name)}{spec.where}"
    sql_params: list[Any] = list(spec.params)
    if group_column:
        sql += f" GROUP BY {quote(group_column)} ORDER BY {quote(group_column)}"
    with connection.cursor() as cursor:
        cursor.execute(sql, sql_params)
        db_rows = cursor.fetchall()
    columns = ["row_count", *(["group_value"] if group_column else []), *(f"agg_{i}" for i in range(len(agg.aggs)))]
    results: list[dict[str, Any]] = []
    for db_row in db_rows:
        row = dict(zip(columns, db_row, strict=True))
        count = int(row["row_count"])
        value: Any = None
        if agg.group_by is not None:
            group_field = fields[agg.group_by]
            value = get_field_type(str(group_field.field_type)).from_db(row.get("group_value"), group_field.config)  # type: ignore[arg-type]
        aggregations: dict[str, Any] = {}
        for index, (field_name, func) in enumerate(agg.aggs.items()):
            raw = row.get(f"agg_{index}")
            if func in ("sum", "avg"):
                aggregations[field_name] = _to_decimal(raw)
            elif func == "count":
                aggregations[field_name] = int(raw) if raw is not None else 0
            else:  # min/max：按字段类型往返转换
                target = fields[field_name]
                aggregations[field_name] = get_field_type(str(target.field_type)).from_db(raw, target.config)  # type: ignore[arg-type]
        results.append({"value": value, "count": count, "aggregations": aggregations})
    return {"group_by": agg.group_by, "results": results}
