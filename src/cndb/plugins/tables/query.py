"""查询编译 —— 把前端传来的 filter/sort 规则转为 SQLAlchemy where/order_by.

前端过滤条件格式：
[
    {"field_name": "age", "op": ">", "value": 18},
    {"field_name": "status", "op": "in", "value": ["active", "pending"]},
    {"field_name": "name", "op": "contains", "value": "张"},
]

filter_logic: "AND" | "OR" 控制多条件组合.

支持的操作符（op）：
- = / eq          等于
- != / neq        不等于
- > / gte / lt    比较
- in              值在列表中
- contains        文本包含
- starts_with     文本前缀
- ends_with       文本后缀
- is_empty        空值/空串
- is_not_empty    非空
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import String, Table, Text, and_, exists, func, or_, select
from sqlalchemy import column as sa_column
from sqlalchemy import table as sa_table_fn

from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.models import DataField, DataTable

logger = logging.getLogger(__name__)


# ── 操作符表 ──────────────────────────────────────────


def _is_link_field(table: DataTable, field_name: str) -> DataField | None:
    """若字段为关联字段则返回字段对象，否则 None."""
    field_map: dict[str, DataField] = {f.name: f for f in table.fields if not f.trashed}
    f = field_map.get(field_name)
    if f is None:
        return None
    ft = default_registry.get(f.field_type)
    if ft is not None and not ft.has_physical_column:
        return f
    return None


def _compile_link_condition(
    sa_table: Table,
    field: DataField,
    field_name: str,
    op: str,
    value: Any,
) -> Any:
    """编译关联字段的过滤条件为 EXISTS 子查询（is_null/has_any/has_all，其余拒绝）."""
    op_lower = op.lower()
    if op_lower not in ("is_null", "has_any", "has_all"):
        raise ValueError(f"关联字段仅支持 is_null/has_any/has_all 过滤: {field_name}")

    link_table = sa_table_fn(
        field.link_table_name,
        sa_column("row_id"),
        sa_column("target_row_id"),
    )
    exists_base = select(1).select_from(link_table).where(link_table.c.row_id == sa_table.c.id)

    if op_lower == "is_null":
        return ~exists(exists_base)

    ids = value
    ft = default_registry.get(field.field_type)
    if ft is not None:
        ids = ft.parse_query_value(value, field.config)
    if not isinstance(ids, (list, tuple)) or not ids:
        raise ValueError(f"has_any/has_all 的值必须是非空 id 集合: {field_name}")

    if op_lower == "has_any":
        return exists(exists_base.where(link_table.c.target_row_id.in_([int(i) for i in ids])))
    # has_all：逐 id EXISTS 后 AND 组合
    return and_(*[exists(exists_base.where(link_table.c.target_row_id == int(i))) for i in ids])


def _build_condition(  # noqa: PLR0911, PLR0912
    table: DataTable,
    sa_table: Table,
    field_name: str,
    op: str,
    value: Any,
) -> Any:
    """把 {field_name, op, value} 转为 SQLAlchemy column expression.

    field_name 是用户可见名（DataField.name），内部映射到 db_column_name.
    """
    field_map: dict[str, DataField] = {f.name: f for f in table.fields}
    f = field_map.get(field_name)
    if f is None:
        logger.warning("未知过滤字段 %s，跳过", field_name)
        return None

    link_field = _is_link_field(table, field_name)
    if link_field is not None:
        return _compile_link_condition(sa_table, link_field, field_name, op, value)
    if op.lower() in ("has_any", "has_all"):
        raise ValueError(f"has_any/has_all 仅支持关联字段: {field_name}")

    col = getattr(sa_table.c, f.db_column_name, None)
    if col is None:
        logger.warning("物理列 %s 不存在，跳过", f.db_column_name)
        return None

    op_lower = op.lower()

    if op_lower in ("=", "eq"):
        return col == value
    if op_lower in ("!=", "neq"):
        return col != value
    if op_lower == ">":
        return col > value
    if op_lower == ">=":
        return col >= value
    if op_lower == "<":
        return col < value
    if op_lower == "<=":
        return col <= value
    if op_lower == "in":
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"in 操作符需要 list/tuple 值，收到 {type(value).__name__}")
        return col.in_(list(value))
    if op_lower == "not_in":
        if not isinstance(value, (list, tuple)):
            raise ValueError("not_in 操作符需要 list/tuple 值")
        return ~col.in_(list(value))
    if op_lower == "contains":
        return col.contains(value)
    if op_lower == "starts_with":
        return col.startswith(value)
    if op_lower == "ends_with":
        return col.endswith(value)
    if op_lower == "is_empty":
        return or_(col.is_(None), col == "")
    if op_lower == "is_not_empty":
        return and_(col.isnot(None), col != "")
    if op_lower == "is_null":
        return col.is_(None)
    if op_lower == "is_not_null":
        return col.isnot(None)
    # multiselect 专用：逗号分隔字符串的包含判断
    # - contains_any: 值中包含列表任一（任一匹配即 true）
    # - contains_all: 值中包含列表全部
    # - exactly: 值精确等于某个字符串（逗号分隔整体匹配）
    if op_lower == "contains_any":
        if not isinstance(value, (list, tuple)):
            raise ValueError("contains_any 需要 list/tuple 值")
        # col LIKE '%val1%' OR col LIKE '%val2%' ...
        return or_(*[col.contains(str(v)) for v in value]) if value else None
    if op_lower == "contains_all":
        if not isinstance(value, (list, tuple)):
            raise ValueError("contains_all 需要 list/tuple 值")
        return and_(*[col.contains(str(v)) for v in value]) if value else None
    # date range: 值为 [start, end]，两端闭区间
    if op_lower in ("between", "date_range"):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError(f"{op_lower} 需要 [start, end] 二元组")
        start_val, end_val = value
        return and_(col >= start_val, col <= end_val)

    raise ValueError(f"未知操作符: {op}")


# ── 入口函数 ─────────────────────────────────────────


def _normalize_filters(  # noqa: PLR0912
    table: DataTable,
    filters: Any,
) -> list[dict[str, Any]]:
    """把 dict / list 统一归一成 list[dict[str, Any]].

    接受三种形状：
    1. list[dict]       —— 已经是标准格式，直接返回.
    2. dict {k: v}      —— 每个条目视为 {field_name: k, op: "=", value: v}.
    3. dict 含 $query   —— $query 值对所有文本字段做 OR contains 匹配.
    """
    if filters is None:
        return []

    # 已是 list
    if isinstance(filters, list):
        result: list[dict[str, Any]] = []
        for item in filters:
            if isinstance(item, dict):
                result.append(item)
            else:
                logger.warning("忽略非 dict filter 项: %r", item)
        return result

    # dict 形式
    if isinstance(filters, dict):
        normalized: list[dict[str, Any]] = []
        for key, value in filters.items():
            # 特殊操作符 $query / __query__: 对所有可搜索文本字段做 OR contains
            if key in ("$query", "__query__"):
                # 可搜索文本字段 —— 遍历 registry 找 String/Text 基础列（排除 link/attachment 等无物理列或非文本类型）
                text_fields: list[DataField] = []
                for f in table.fields:
                    if f.trashed:
                        continue
                    ft = default_registry.get(f.field_type)
                    if ft is None or not ft.has_physical_column:
                        continue
                    if ft.sqlalchemy_type in (String, Text):
                        text_fields.append(f)
                if text_fields and value:
                    contains_list: list[dict[str, Any]] = [
                        {"field_name": f.name, "op": "contains", "value": value} for f in text_fields
                    ]
                    # 用 OR 逻辑 —— 通过 marker key __query_or__ 提示 compile_filters
                    normalized.append({"__query_or__": contains_list})
                continue

            # 嵌套分组 key: __or__ / __and__ —— 原样保留，值可以是 list[dict] 或 dict
            if key in ("__or__", "__and__"):
                normalized.append({key: value})
                continue

            # 值本身是 dict，视为 {field_name, op, value} 或 {op: ..., value: ...}
            if isinstance(value, dict) and "op" in value and "value" in value:
                normalized.append({"field_name": key, **value})
            # 常规形式: {field_name: value} → {field_name, op: "=", value}
            else:
                normalized.append({"field_name": key, "op": "=", "value": value})
        return normalized

    logger.warning("filters 类型不支持: %r", type(filters))
    return []


def _compile_filter_item(  # noqa: PLR0911 - filter item 分支多属正常
    table: DataTable,
    sa_table: Table,
    flt: dict[str, Any],
) -> Any | None:
    """编译单个 filter dict（支持递归处理 __or__ / __and__ 嵌套组）."""
    # __or__ / __and__ 嵌套组
    if "__or__" in flt:
        return _compile_group(table, sa_table, flt["__or__"], logic="OR")
    if "__and__" in flt:
        return _compile_group(table, sa_table, flt["__and__"], logic="AND")

    # $query 展开的 OR 组
    if "__query_or__" in flt:
        return _compile_group(table, sa_table, flt["__query_or__"], logic="OR")

    field_name = flt.get("field_name") or flt.get("field")
    if not field_name:
        return None
    op = flt.get("op") or flt.get("operator") or "="
    value = flt.get("value")

    # list 形式里 __query__ / $query —— 对所有可搜索文本字段做 OR contains
    if field_name in ("__query__", "$query"):
        from sqlalchemy import String, Text

        from cndb.plugins.tables.field_types import default_registry

        text_fields: list[DataField] = []
        for f in table.fields:
            if f.trashed:
                continue
            ft = default_registry.get(f.field_type)
            if ft is None or not ft.has_physical_column:
                continue
            if ft.sqlalchemy_type in (String, Text):
                text_fields.append(f)
        if text_fields and value:
            contains_list: list[dict[str, Any]] = [
                {"field_name": f.name, "op": "contains", "value": value} for f in text_fields
            ]
            return _compile_group(table, sa_table, contains_list, logic="OR")
        return None

    return _build_condition(table, sa_table, field_name, op, value)


def _compile_group(
    table: DataTable,
    sa_table: Table,
    items: Any,
    logic: str,
) -> Any | None:
    """编译一组条件，用指定逻辑连接."""
    if not items:
        return None
    if isinstance(items, dict):
        items = _normalize_filters(table, items)
    sub_clauses: list[Any] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        clause = _compile_filter_item(table, sa_table, item)
        if clause is not None:
            sub_clauses.append(clause)
    if not sub_clauses:
        return None
    if len(sub_clauses) == 1:
        return sub_clauses[0]
    return or_(*sub_clauses) if logic.upper() == "OR" else and_(*sub_clauses)


def compile_filters(
    table: DataTable,
    sa_table: Table,
    filters: Any,
    logic: str = "AND",
) -> Any | None:
    """编译过滤条件，返回单个 SQLAlchemy where clause（或 None 表示无有效条件）.

    filters 支持：
    - list[dict]: 标准格式
    - dict {k: v}: 简易格式
    - dict 含 $query / __query__: 全局关键词搜索
    - dict 含 __or__ / __and__: 嵌套分组（值为 list[dict] 或 dict）
    """
    normalized = _normalize_filters(table, filters)
    return _compile_group(table, sa_table, normalized, logic=logic)


def compile_sorts(
    table: DataTable,
    sa_table: Table,
    sorts: list[dict[str, str]],
) -> list[Any]:
    """编译排序条件，返回 SQLAlchemy order_by expression 列表."""
    field_map: dict[str, DataField] = {f.name: f for f in table.fields}
    order_clauses: list[Any] = []

    for s in sorts:
        if not isinstance(s, dict):
            logger.warning("跳过非 dict sort 项: %r", s)
            continue
        field_name = s.get("field_name") or s.get("field")
        if not field_name:
            continue
        direction = (s.get("direction") or s.get("dir") or "asc").lower()

        f = field_map.get(field_name)
        if f is None:
            logger.warning("未知排序字段 %s，跳过", field_name)
            continue

        col = getattr(sa_table.c, f.db_column_name, None)
        if col is None:
            continue

        order_clauses.append(col.desc() if direction == "desc" else col.asc())

    return order_clauses


def count_rows(_table: DataTable, sa_table: Table, where_clauses: list[Any]) -> Any:
    """编译 COUNT 查询（由 records.list_rows 间接调用；此处提供独立入口供外部使用）."""
    query = select(func.count(sa_table.c.id))
    if where_clauses:
        query = query.where(*where_clauses)
    return query


__all__ = [
    "compile_filters",
    "compile_sorts",
    "count_rows",
]
