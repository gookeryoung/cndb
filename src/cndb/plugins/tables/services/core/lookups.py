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
    "lookup_fields",
    "mark_dependent_lookups_broken",
]
