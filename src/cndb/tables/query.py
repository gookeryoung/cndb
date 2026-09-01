"""查询编译：把过滤/排序查询参数安全编译为 SQL 片段.

安全设计：字段名经元数据白名单映射为系统生成的物理列名，操作符走封闭集合，
值全部参数化传参；用户输入永不拼接进 SQL 标识符位置。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from cndb.tables.field_types import FieldTypeError, get_field_type
from cndb.tables.models import DataTable
from cndb.tables.sql import quote

# 过滤操作符到 SQL 比较符的映射（contains/is_null 单独处理）
_FILTER_OPS = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
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


def _fields_by_name(table: DataTable) -> dict[str, Any]:
    """字段名到元数据的映射（仅未回收字段）."""
    return {str(field.name): field for field in table.active_fields()}


def _normalize(field: Any, field_type: Any, value: Any) -> Any:
    """查询参数值先经类型解析再校验，返回数据库参数形式."""
    parsed = field_type.parse_query_value(value, field.config)  # type: ignore[bad-argument-type]
    normalized = field_type.validate_value(parsed, field.config)  # type: ignore[bad-argument-type]
    return field_type.to_db(normalized, field.config)  # type: ignore[bad-argument-type]


def parse_filters(table: DataTable, params: Mapping[str, Any]) -> tuple[str, list[Any]]:
    """解析 filter__<字段名>__<操作符> 参数为 WHERE 片段与参数列表.

    支持的操作符：eq/ne/gt/gte/lt/lte/contains（仅文本类字段）/is_null（值为 true/false）。
    多个过滤条件以 AND 组合。
    """
    fields = _fields_by_name(table)
    clauses: list[str] = []
    sql_params: list[Any] = []
    for key, value in params.items():
        if not key.startswith("filter__"):
            continue
        parts = key.split("__")
        if len(parts) != 3 or not parts[1] or not parts[2]:
            raise InvalidQueryError(f"非法过滤参数: {key}")
        _, field_name, op = parts
        field = fields.get(field_name)
        if field is None:
            raise InvalidQueryError(f"未知字段: {field_name}")
        column = quote(field.db_column_name)
        if op == "is_null":
            if str(value).lower() not in ("true", "false"):
                raise InvalidQueryError(f"is_null 的值必须是 true/false: {key}")
            clauses.append(f"{column} IS NULL" if str(value).lower() == "true" else f"{column} IS NOT NULL")
            continue
        if op not in _FILTER_OPS and op != "contains":
            raise InvalidQueryError(f"不支持的过滤操作符: {op}")
        field_type = get_field_type(str(field.field_type))
        if op == "contains":
            if str(field.field_type) not in _TEXT_LIKE_TYPES:
                raise InvalidQueryError(f"contains 仅支持文本类字段: {field_name}")
            try:
                db_value = _normalize(field, field_type, value)
            except FieldTypeError as exc:
                raise InvalidQueryError(f"字段 {field_name} 的过滤值非法: {exc}") from exc
            clauses.append(f"{column} LIKE %s")
            sql_params.append(f"%{db_value}%")
            continue
        try:
            db_value = _normalize(field, field_type, value)
        except FieldTypeError as exc:
            raise InvalidQueryError(f"字段 {field_name} 的过滤值非法: {exc}") from exc
        clauses.append(f"{column} {_FILTER_OPS[op]} %s")
        sql_params.append(db_value)
    if not clauses:
        return "", []
    return f" WHERE {' AND '.join(clauses)}", sql_params


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
        if name == "id":
            column = quote("id")
        else:
            field = fields.get(name)
            if field is None:
                raise InvalidQueryError(f"未知排序字段: {name}")
            column = quote(field.db_column_name)
        columns.append(f"{column} DESC" if descending else column)
    return f" ORDER BY {', '.join(columns)}"
