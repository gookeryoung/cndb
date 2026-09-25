"""引用查找字段（lookup）的实时值解析.

语义：lookup 字段通过本表的 link 字段（外键角色）关联到源表行，
读取源表某字段的值 —— 类似 SQL 多表关联后的投影列。

- 值实时查询、只读、不落物理列，源表更新零同步成本；
- link 字段 multiple=True 时输出聚合列表，否则输出首个关联行的值（无关联为 None）；
- 源字段/link 字段缺失（被删/进回收站/config.broken）时回退 None，不抛错。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cndb.plugins.tables.models import DataField, DataTable

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

from sqlalchemy import select

from cndb.plugins.tables.services.core.links import load_links

logger = logging.getLogger(__name__)

LOOKUP_FIELD_TYPE = "lookup"


def is_lookup_field(field: DataField) -> bool:
    """判断字段是否为引用查找字段."""
    return field.field_type == LOOKUP_FIELD_TYPE


def lookup_fields(table: DataTable) -> list[DataField]:
    """返回表中全部未回收的 lookup 字段."""
    return [f for f in table.active_fields() if is_lookup_field(f)]


def mark_dependent_lookups_broken(db: Session, source_field_id: int) -> int:
    """把引用了某源字段的全部 lookup 字段标记为 broken（源字段被删/改类型时调用）.

    Returns:
        被标记的 lookup 字段数量.
    """
    candidates = (
        db.query(DataField)
        .filter(DataField.field_type == LOOKUP_FIELD_TYPE, DataField.trashed == False)  # noqa: E712
        .all()
    )
    marked = 0
    for f in candidates:
        config = f.config or {}
        if config.get("source_field_id") != source_field_id or config.get("broken"):
            continue
        new_config = dict(config)
        new_config["broken"] = True
        f.config = new_config
        marked += 1
    if marked:
        db.commit()
        logger.info("[lookups] 源字段 %d 失效，已标记 %d 个 lookup 字段为 broken", source_field_id, marked)
    return marked


def attach_lookup_values(
    engine: Engine,
    table: DataTable,
    rows: list[dict[str, Any]],
    db: Session | None = None,
) -> list[dict[str, Any]]:
    """为行响应附加 lookup 字段的实时解析值；无 lookup 字段或空结果时原样返回.

    db 为 None 时无法解析源表元数据，lookup 字段回退 None。
    """
    fields = lookup_fields(table)
    if not fields or not rows or db is None:
        return rows

    row_ids = [int(row["id"]) for row in rows]
    for field in fields:
        config = field.config or {}
        values_by_row = _resolve_lookup_values(engine, db, table, config, row_ids)
        for row in rows:
            row[str(field.name)] = values_by_row.get(int(row["id"]))
    return rows


def _resolve_lookup_values(
    engine: Engine,
    db: Session,
    table: DataTable,
    config: dict[str, Any],
    row_ids: list[int],
) -> dict[int, Any]:
    """解析一批行的 lookup 值：row_id -> 聚合列表 / 标量 / None."""
    # 失效回退：config.broken 或配置缺失
    if config.get("broken"):
        return {}

    link_field = _find_link_field(table, config.get("via_link_field_id"))
    source_field = _find_source_field(db, config)
    if link_field is None or source_field is None:
        return {}

    multiple = bool((link_field.config or {}).get("multiple", True))
    mapping = load_links(engine, link_field, row_ids)
    if not mapping:
        return {}

    all_targets = [tid for ids in mapping.values() for tid in ids]
    source_values = _read_source_values(engine, source_field, all_targets)
    if source_values is None:
        return {}

    result: dict[int, Any] = {}
    for row_id in row_ids:
        target_ids = mapping.get(row_id, [])
        values = [source_values[tid] for tid in target_ids if tid in source_values]
        if multiple:
            result[row_id] = values
        else:
            result[row_id] = values[0] if values else None
    return result


def lookup_field_names(table: DataTable) -> set[str]:
    """返回表中全部未回收 lookup 字段的名称集合（用户可见名）."""
    return {f.name for f in lookup_fields(table)}


_GROUP_KEYS = ("__or__", "__and__", "__query_or__")


def _group_items(value: Any) -> list[dict[str, Any]]:
    """把嵌套分组的值归一为标准条件列表（支持 list 或 dict 形式）."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        items: list[dict[str, Any]] = []
        for key, val in value.items():
            if key in ("__or__", "__and__"):
                items.append({key: val})
            elif isinstance(val, dict) and "op" in val and "value" in val:
                items.append({"field_name": key, **val})
            else:
                items.append({"field_name": key, "op": "=", "value": val})
        return items
    return []


def _contains_lookup(names: set[str], value: Any) -> bool:
    """递归判断条件子树中是否含 lookup 字段条件."""
    for item in _group_items(value):
        for group_key in _GROUP_KEYS:
            if group_key in item:
                if _contains_lookup(names, item[group_key]):
                    return True
                break
        else:
            if (item.get("field_name") or item.get("field")) in names:
                return True
    return False


def split_lookup_filters(
    table: DataTable,
    filters: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把过滤条件拆为 (SQL 端条件, lookup 内存条件).

    递归处理：含 lookup 条件的嵌套分组（__or__/__and__）整体留在内存侧
    （含组内物理列条件，由 match_row_filters 统一求值）；纯物理条件的
    子树留在 SQL 端下推。
    filters 为 None 或 dict 时原样交给 SQL 端（由调用方归一）。
    """
    if not isinstance(filters, list) or not filters:
        return filters, []
    names = lookup_field_names(table)
    if not names:
        return filters, []
    sql_items: list[dict[str, Any]] = []
    lookup_items: list[dict[str, Any]] = []
    for item in filters:
        if not isinstance(item, dict):
            sql_items.append(item)
            continue
        for group_key in _GROUP_KEYS:
            if group_key in item:
                (lookup_items if _contains_lookup(names, item[group_key]) else sql_items).append(item)
                break
        else:
            field_name = item.get("field_name") or item.get("field")
            if field_name in names:
                lookup_items.append(item)
            else:
                sql_items.append(item)
    return sql_items, lookup_items


def match_lookup_value(value: Any, op: str, expected: Any) -> bool:
    """对已解析的 lookup 行值做内存条件匹配.

    行值可能是聚合列表（multiple link）、标量或 None（无关联）。
    """
    op = (op or "=").lower()
    vals: list[Any] = value if isinstance(value, list) else [value] if value is not None else []

    if op in ("is_empty", "is_null"):
        return not vals
    if op in ("is_not_empty", "is_not_null"):
        return bool(vals)
    if op in ("=", "eq"):
        return value == expected
    if op in ("!=", "neq"):
        return value != expected
    if op == "in":
        return value in list(expected or [])
    if op == "not_in":
        return value not in list(expected or [])
    if op == "contains":
        return any(str(expected) in str(v) for v in vals)
    if op == "starts_with":
        return any(str(v).startswith(str(expected)) for v in vals)
    if op == "ends_with":
        return any(str(v).endswith(str(expected)) for v in vals)
    if op == "contains_any":
        return any(v in list(expected or []) for v in vals)
    if op == "contains_all":
        return all(e in vals for e in (expected or []))
    if op == ">":
        return any(v is not None and v > expected for v in vals)
    if op == ">=":
        return any(v is not None and v >= expected for v in vals)
    if op == "<":
        return any(v is not None and v < expected for v in vals)
    if op == "<=":
        return any(v is not None and v <= expected for v in vals)
    logger.warning("lookup 过滤不支持操作符 %s，按不匹配处理", op)
    return False


def _match_physical_value(value: Any, op: str, expected: Any) -> bool:
    """对物理列行值做内存条件匹配（语义与 query._build_condition 的 SQL 端一致）.

    类型不可直接比较时回退字符串比较；无法求值的操作符按不匹配处理。
    """
    op = (op or "=").lower()
    if op in ("is_empty",):
        return value is None or value == ""
    if op in ("is_not_empty",):
        return not (value is None or value == "")
    if op in ("is_null",):
        return value is None
    if op in ("is_not_null",):
        return value is not None
    if value is None:
        return False
    if op in ("=", "eq"):
        return value == expected
    if op in ("!=", "neq"):
        return value != expected
    if op == "in":
        return value in list(expected or [])
    if op == "not_in":
        return value not in list(expected or [])
    if op == "contains":
        return str(expected) in str(value)
    if op == "starts_with":
        return str(value).startswith(str(expected))
    if op == "ends_with":
        return str(value).endswith(str(expected))
    if op == "contains_any":
        return any(str(v) in str(value) for v in (expected or []))
    if op == "contains_all":
        return all(str(v) in str(value) for v in (expected or []))
    if op in (">", ">=", "<", "<="):
        try:
            if op == ">":
                return value > expected
            if op == ">=":
                return value >= expected
            if op == "<":
                return value < expected
            return value <= expected
        except TypeError:
            try:
                s1, s2 = str(value), str(expected)
                return s1 > s2 if op == ">" else s1 >= s2 if op == ">=" else s1 < s2 if op == "<" else s1 <= s2
            except Exception:  # 防御性：无法比较即不匹配
                return False
    if op in ("between", "date_range"):
        if not isinstance(expected, (list, tuple)) or len(expected) != 2:
            return False
        start_val, end_val = expected
        return _match_physical_value(value, ">=", start_val) and _match_physical_value(value, "<=", end_val)
    logger.warning("内存过滤不支持操作符 %s，按不匹配处理", op)
    return False


def _match_link_value(value: Any, op: str, expected: Any) -> bool:
    """对 attach 后的 link 行值（[{id, value}] 摘要列表）做内存条件匹配."""
    op = (op or "=").lower()
    ids: list[Any] = (
        [d.get("id") for d in value if isinstance(d, dict) and d.get("id") is not None]
        if isinstance(value, list)
        else []
    )
    if op in ("is_null", "is_empty"):
        return not ids
    if op in ("is_not_null", "is_not_empty"):
        return bool(ids)
    if op in ("has_any",):
        try:
            id_set = {int(i) for i in ids}
            return any(int(t) in id_set for t in (expected or []))
        except (TypeError, ValueError):
            return False
    if op in ("has_all",):
        try:
            id_set = {int(i) for i in ids}
            return all(int(t) in id_set for t in (expected or []))
        except (TypeError, ValueError):
            return False
    logger.warning("link 字段内存过滤不支持操作符 %s，按不匹配处理", op)
    return False


def match_row_filters(
    table: DataTable,
    row: dict[str, Any],
    filters: Any,
    logic: str = "AND",
) -> bool:
    """对已 attach 的行递归求值过滤条件（lookup / 物理列 / link 混合，支持嵌套分组）.

    语义与 SQL 端编译（query.compile_filters）对齐：
    - lookup 叶子走 match_lookup_value（聚合列表语义）；
    - 物理列叶子走 _match_physical_value；
    - link 叶子走 _match_link_value（is_null/has_any/has_all）；
    - __or__ / __and__ / __query_or__ 嵌套分组递归求值。
    """
    names = lookup_field_names(table)
    link_names = {f.name for f in table.active_fields() if f.field_type == "link"}

    def _eval(items: list[dict[str, Any]], group_logic: str) -> bool:
        all_mode = str(group_logic).upper() != "OR"
        results: list[bool] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            for group_key, group_logic_key in (("__or__", "OR"), ("__and__", "AND"), ("__query_or__", "OR")):
                if group_key in item:
                    results.append(_eval(_group_items(item[group_key]), group_logic_key))
                    break
            else:
                field_name = item.get("field_name") or item.get("field")
                op = str(item.get("op") or item.get("operator") or "=")
                expected = item.get("value")
                if field_name in names:
                    results.append(match_lookup_value(row.get(str(field_name)), op, expected))
                elif field_name in link_names:
                    results.append(_match_link_value(row.get(str(field_name)), op, expected))
                else:
                    results.append(_match_physical_value(row.get(str(field_name)), op, expected))
        if not results:
            return True
        return all(results) if all_mode else any(results)

    return _eval(
        _group_items(filters) if not isinstance(filters, list) else [i for i in filters if isinstance(i, dict)], logic
    )


def _lookup_sort_rank(value: Any, is_desc: bool = False) -> Any:
    """把 lookup 行值转为排序键：None 恒最后；列表按方向取极值（asc 取最小、desc 取最大）."""
    if value is None:
        return None
    if isinstance(value, list):
        if not value:
            return None
        return max(value, key=str) if is_desc else min(value, key=str)
    return value


def sort_rows_in_memory(rows: list[dict[str, Any]], sorts: list[dict[str, str]]) -> list[dict[str, Any]]:
    """按 sorts 列表顺序对已解析行做内存排序（物理列与 lookup 字段通用）.

    None 值恒排最后（与 asc/desc 无关）；多级排序按列表顺序依次比较；
    类型不可直接比较时回退字符串比较，避免整个查询崩溃。
    """
    import functools

    specs: list[tuple[str, bool]] = []
    for s in sorts or []:
        if not isinstance(s, dict):
            continue
        field_name = s.get("field_name") or s.get("field")
        if not field_name:
            continue
        direction = (s.get("direction") or s.get("dir") or "asc").lower()
        specs.append((field_name, direction == "desc"))
    if not specs:
        return rows

    def _cmp(r1: dict[str, Any], r2: dict[str, Any]) -> int:
        for field_name, is_desc in specs:
            k1 = _lookup_sort_rank(r1.get(field_name), is_desc)
            k2 = _lookup_sort_rank(r2.get(field_name), is_desc)
            if k1 is None and k2 is None:
                continue
            if k1 is None:
                return 1  # None 恒最后，不随方向反转
            if k2 is None:
                return -1
            if k1 == k2:
                continue
            try:
                c = -1 if k1 < k2 else 1
            except TypeError:
                c = -1 if str(k1) < str(k2) else 1
            return -c if is_desc else c
        return 0

    return sorted(rows, key=functools.cmp_to_key(_cmp))


def _find_link_field(table: DataTable, via_link_field_id: Any) -> DataField | None:
    """在本表中查找 via_link_field_id 对应的未回收 link 字段."""
    if not isinstance(via_link_field_id, int):
        return None
    return next(
        (f for f in table.active_fields() if f.id == via_link_field_id and f.field_type == "link"),
        None,
    )


def _find_source_field(db: Session, config: dict[str, Any]) -> DataField | None:
    """解析 config 指向的源字段（不存在或已回收返回 None）."""
    source_field_id = config.get("source_field_id")
    if not isinstance(source_field_id, int):
        return None
    f = db.get(DataField, source_field_id)
    if f is None or f.trashed:
        return None
    return f


def _read_source_values(
    engine: Engine,
    source_field: DataField,
    target_row_ids: list[int],
) -> dict[int, Any] | None:
    """从源物理表批量读取字段值：源行 id -> 值；物理表缺列时返回 None."""
    from sqlalchemy import MetaData, inspect

    source_table = source_field.table
    if source_table is None:
        return None
    insp = inspect(engine)
    if source_table.db_table_name not in insp.get_table_names():
        return None
    col_names = {c["name"] for c in insp.get_columns(source_table.db_table_name)}
    if source_field.db_column_name not in col_names:
        return None

    metadata = MetaData()
    metadata.reflect(bind=engine, only=[source_table.db_table_name])
    sa_table = metadata.tables[source_table.db_table_name]
    col = sa_table.c.get(source_field.db_column_name)
    if col is None:
        return None
    with engine.connect() as conn:
        rows = conn.execute(select(sa_table.c.id, col).where(sa_table.c.id.in_(list(target_row_ids)))).all()
    return {int(r[0]): r[1] for r in rows}


__all__ = [
    "LOOKUP_FIELD_TYPE",
    "attach_lookup_values",
    "is_lookup_field",
    "lookup_field_names",
    "lookup_fields",
    "mark_dependent_lookups_broken",
    "match_lookup_value",
    "match_row_filters",
    "sort_rows_in_memory",
    "split_lookup_filters",
]
