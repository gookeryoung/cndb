"""查询编译：把过滤/排序输入安全编译为 SQL 片段.

安全设计：字段名经元数据白名单映射为系统生成的物理列名，操作符走封闭集合，
值全部参数化传参；用户输入永不拼接进 SQL 标识符位置。

两类入口：
- parse_filters/parse_order_by：URL 查询参数（filter__<字段>__<操作符> / order_by）
- compile_filters/compile_sortings：视图保存的结构化规则（[{"field","op","value"}] / [{"field","desc"}]）
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from cndb.tables.field_types import FieldTypeError, get_field_type
from cndb.tables.models import DataTable
from cndb.tables.sql import quote

# 过滤操作符到 SQL 比较符的映射（contains/is_null 单独处理）
_FILTER_OPS = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
# 全部合法过滤操作符（视图规则校验共用）
FILTER_OPS = frozenset({*_FILTER_OPS, "contains", "is_null"})
# 条件组合方式
MATCH_TYPES = frozenset({"AND", "OR"})
# 允许使用 contains 的文本类字段类型
_TEXT_LIKE_TYPES = frozenset({"text", "long_text", "email", "url", "single_select"})


class InvalidQueryError(Exception):
    """查询参数非法（未知字段/操作符/值）."""


@dataclass
class RowQuery:
    """行查询编译结果：WHERE/ORDER 片段（值参数化）与分页."""

    where: str = ""
    params: list[Any] = field(default_factory=list)
    order: str = ""
    limit: int | None = None
    offset: int = 0


def bare_condition(where: str) -> str:
    """剥掉 WHERE 片段的 WHERE 关键字前缀，返回裸条件表达式."""
    condition = where.strip()
    if condition[:6].upper() == "WHERE ":
        return condition[6:].strip()
    return condition


def merge_where(base: RowQuery, extra: RowQuery | None) -> RowQuery:
    """把 extra 的 WHERE 条件以 AND 并入 base（保留 base 的排序与分页）."""
    if extra is None or not extra.where:
        return base
    if not base.where:
        return RowQuery(
            where=f" WHERE {bare_condition(extra.where)}",
            params=list(extra.params),
            order=base.order,
            limit=base.limit,
            offset=base.offset,
        )
    return RowQuery(
        where=f"{base.where} AND ({bare_condition(extra.where)})",
        params=[*base.params, *extra.params],
        order=base.order,
        limit=base.limit,
        offset=base.offset,
    )


def _fields_by_name(table: DataTable) -> dict[str, Any]:
    """字段名到元数据的映射（仅未回收字段）."""
    return {str(field.name): field for field in table.active_fields()}


def _normalize(field: Any, field_type: Any, value: Any) -> Any:
    """查询参数值先经类型解析再校验，返回数据库参数形式."""
    parsed = field_type.parse_query_value(value, field.config)  # type: ignore[bad-argument-type]
    normalized = field_type.validate_value(parsed, field.config)  # type: ignore[bad-argument-type]
    return field_type.to_db(normalized, field.config)  # type: ignore[bad-argument-type]


def _compile_condition(fields: Mapping[str, Any], field_name: str, op: str, value: Any) -> tuple[str, list[Any]]:
    """编译单个过滤条件为 SQL 片段与参数列表（is_null 无参数）."""
    target = fields.get(field_name)
    if target is None:
        raise InvalidQueryError(f"未知字段: {field_name}")
    column = quote(target.db_column_name)
    if op == "is_null":
        if str(value).lower() not in ("true", "false"):
            raise InvalidQueryError(f"is_null 的值必须是 true/false: {field_name}")
        clause = f"{column} IS NULL" if str(value).lower() == "true" else f"{column} IS NOT NULL"
        return clause, []
    if op not in _FILTER_OPS and op != "contains":
        raise InvalidQueryError(f"不支持的过滤操作符: {op}")
    field_type = get_field_type(str(target.field_type))
    if op == "contains" and str(target.field_type) not in _TEXT_LIKE_TYPES:
        raise InvalidQueryError(f"contains 仅支持文本类字段: {field_name}")
    try:
        db_value = _normalize(target, field_type, value)
    except FieldTypeError as exc:
        raise InvalidQueryError(f"字段 {field_name} 的过滤值非法: {exc}") from exc
    if op == "contains":
        return f"{column} LIKE %s", [f"%{db_value}%"]
    return f"{column} {_FILTER_OPS[op]} %s", [db_value]


def parse_filters(table: DataTable, params: Mapping[str, Any]) -> tuple[str, list[Any]]:
    """解析 filter__<字段名>__<操作符> 参数为 WHERE 片段与参数列表（多条件 AND 组合）."""
    fields = _fields_by_name(table)
    clauses: list[str] = []
    sql_params: list[Any] = []
    for key, value in params.items():
        if not key.startswith("filter__"):
            continue
        parts = key.split("__")
        if len(parts) != 3 or not parts[1] or not parts[2]:
            raise InvalidQueryError(f"非法过滤参数: {key}")
        clause, condition_params = _compile_condition(fields, parts[1], parts[2], value)
        clauses.append(clause)
        sql_params.extend(condition_params)
    if not clauses:
        return "", []
    return f" WHERE {' AND '.join(clauses)}", sql_params


def compile_filters(
    table: DataTable, filters: Sequence[Mapping[str, Any]], match: str = "AND"
) -> tuple[str, list[Any]]:
    """编译视图保存的结构化筛选规则为 WHERE 片段，match 取 AND/OR 组合多条件."""
    if not filters:
        return "", []
    if match not in MATCH_TYPES:
        raise InvalidQueryError(f"不支持的条件组合方式: {match}")
    fields = _fields_by_name(table)
    clauses: list[str] = []
    sql_params: list[Any] = []
    for rule in filters:
        clause, condition_params = _compile_condition(
            fields, str(rule.get("field", "")), str(rule.get("op", "")), rule.get("value")
        )
        clauses.append(clause)
        sql_params.extend(condition_params)
    joiner = " AND " if match == "AND" else " OR "
    return f" WHERE ({joiner.join(clauses)})", sql_params


def _order_column(fields: Mapping[str, Any], name: str, descending: bool) -> str:
    """把字段名编译为排序列片段（id 直通，未知字段拒绝）."""
    if name == "id":
        column = quote("id")
    else:
        target = fields.get(name)
        if target is None:
            raise InvalidQueryError(f"未知排序字段: {name}")
        column = quote(target.db_column_name)
    return f"{column} DESC" if descending else column


def parse_order_by(table: DataTable, order_by: str | None) -> str:
    """解析 order_by 参数为 ORDER BY 片段：逗号分隔多字段，- 前缀降序，默认按 id 升序."""
    if not order_by:
        return f" ORDER BY {quote('id')}"
    fields = _fields_by_name(table)
    columns: list[str] = []
    for part in order_by.split(","):
        name = part.strip()
        descending = name.startswith("-")
        if descending:
            name = name[1:]
        columns.append(_order_column(fields, name, descending))
    return f" ORDER BY {', '.join(columns)}"


def compile_sortings(table: DataTable, sortings: Sequence[Mapping[str, Any]]) -> str:
    """编译视图保存的结构化排序规则 [{"field","desc"}] 为 ORDER BY 片段，默认按 id 升序."""
    if not sortings:
        return f" ORDER BY {quote('id')}"
    fields = _fields_by_name(table)
    columns = [_order_column(fields, str(rule.get("field", "")), bool(rule.get("desc"))) for rule in sortings]
    return f" ORDER BY {', '.join(columns)}"
