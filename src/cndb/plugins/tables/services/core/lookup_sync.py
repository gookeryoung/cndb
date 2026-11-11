"""lookup 冗余列的写入同步、级联重算与历史数据回填（ADR 0131）.

设计要点：
- 冗余列由「写入时同事务维护」为主（create/update/delete/bulk 与字段 DDL）；
  迁移 / CLI 只为历史数据补一次回填；
- 源表字段值变更、目标行删除时级联重算消费方（消费方 = 持有 lookup 字段的表）；
- 编码在本模块收敛：多值用 U+001F 拼接，单值保留原始类型；
  ``first`` / ``max`` 存原生类型（SQLite BLOB 列无亲和性），供排序与比较下推。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any

from sqlalchemy import LargeBinary, select, text

from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core.ddl import get_reflected_table
from cndb.plugins.tables.services.core.lookup_columns import (
    LOOKUP_SEP,
    lookup_column_names,
)
from cndb.plugins.tables.services.core.lookups import _find_link_field, _resolve_lookup_values

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── 开关与列存在性 ────────────────────────────────────


def lookup_columns_enabled() -> bool:
    """冗余列同步 / 下推开关（配置关闭时为回滚路径）."""
    from cndb.core.config import settings

    return bool(getattr(settings, "LOOKUP_COLUMNS_ENABLED", True))


def lookup_columns_present(sa_table: Any, fields: Iterable[DataField]) -> bool:
    """判断物理表是否已具备可用的 lookup 冗余列（未迁移 / 非 SQLite 类型返回 False）.

    BLOB 列（SQLite）无类型亲和性，才能同时容纳原生数字与文本并按原生语义比较；
    PostgreSQL 的 TEXT 列暂不下推（回退旧内存路径，行为与改造前一致）。
    """
    for field in fields:
        for name in lookup_column_names(field):
            column = sa_table.c.get(name)
            if column is None or not isinstance(column.type, LargeBinary):
                return False
    return True


def lookup_fields_with_columns(table: DataTable, sa_table: Any) -> list[DataField]:
    """返回可下推的 lookup 字段（未回收且冗余列齐全）."""
    result: list[DataField] = []
    for field in table.active_fields():
        if field.field_type != "lookup":
            continue
        if lookup_columns_present(sa_table, [field]):
            result.append(field)
    return result


def lookup_pushdown_available(table: DataTable, sa_table: Any) -> bool:
    """当前表是否可以用 SQL 下推处理 lookup 过滤 / 排序."""
    if not lookup_columns_enabled():
        return False
    fields = [f for f in table.active_fields() if f.field_type == "lookup"]
    if not fields:
        return False
    return lookup_columns_present(sa_table, fields)


# ── 值编码 ───────────────────────────────────────────


def _storage_value(value: Any) -> Any:
    """把解析值转为可写入 BLOB 列的原生值（数字 / 文本保持原类型）.

    SQLite 的 BLOB 列无类型亲和性，绑定 int/float 时按对应存储类落库，
    因此比较与排序仍是原生语义；日期等其它对象转 ISO 字符串（字典序即时间序）。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str, bytes)):
        return value
    return str(value)


def _multi_text(value: Any) -> str:
    """多值元素的文本表示（与旧内存实现 ``str(v)`` 的 contains 语义一致）."""
    return str(value)


def encode_lookup_values(multiple: bool, values: Any) -> tuple[Any, Any, Any]:
    """把一行某 lookup 字段的解析值编码为 (joined, first, max).

    - multiple=True：``values`` 为列表；joined 用 U+001F 拼接（无值为 ``''``），
      first/max 取非 None 元素的极小 / 极大值（无值均 None）；
    - multiple=False：``values`` 为标量或 None；joined/first/max 同值（无值均 None）。
    """
    if multiple:
        items: list[Any] = values if isinstance(values, list) else ([] if values is None else [values])
        joined = LOOKUP_SEP.join(_multi_text(v) for v in items)
        non_null = [v for v in items if v is not None]
        if not non_null:
            return joined, None, None
        try:
            first, last = min(non_null), max(non_null)
        except TypeError:
            ordered = sorted(non_null, key=str)
            first, last = ordered[0], ordered[-1]
        return joined, _storage_value(first), _storage_value(last)

    scalar = values
    stored = _storage_value(scalar)
    return stored, stored, stored


# ── 单表行同步 ───────────────────────────────────────


def _updatable_fields(sa_table: Any, fields: list[DataField]) -> list[DataField]:
    """过滤出冗余列已就绪的 lookup 字段（旧库未迁移时跳过，不影响写入）."""
    return [f for f in fields if lookup_columns_present(sa_table, [f])]


def sync_lookup_columns(
    engine: Engine,
    table: DataTable,
    row_ids: Iterable[int],
    *,
    db: Session | None,
    conn: Connection | None = None,
    fields: list[DataField] | None = None,
    bind: Any = None,
) -> int:
    """同步一批行的 lookup 冗余列（同一事务内执行，调用方决定提交/回滚）.

    Args:
        engine: SQLAlchemy Engine.
        table: 持有 lookup 字段的（消费方）表元数据.
        row_ids: 需要重算的行 id.
        db: 元数据库会话；为 None 时无法解析源字段元数据，直接跳过.
        conn: 复用调用方事务连接；为 None 时自开事务.
        fields: 限定只同步的 lookup 字段（默认全部未回收 lookup 字段）.
        bind: 反射使用的连接（迁移中复用同一事务连接，默认 engine）.

    Returns:
        实际同步的行数（0 表示没有可用的冗余列或字段）.
    """
    ids = sorted({int(r) for r in row_ids})
    if db is None or not ids:
        return 0
    if not lookup_columns_enabled():
        return 0

    targets = fields if fields is not None else [f for f in table.active_fields() if f.field_type == "lookup"]
    targets = [f for f in targets if f.field_type == "lookup" and not f.trashed]
    if not targets:
        return 0

    try:
        sa_table = get_reflected_table(bind if bind is not None else engine, table.db_table_name)
    except RuntimeError:
        return 0
    targets = _updatable_fields(sa_table, targets)
    if not targets:
        return 0

    links_cache: dict[int, dict[int, list[int]]] = {}
    columns: list[str] = []
    payload: dict[int, dict[str, Any]] = {row_id: {"_rid": row_id} for row_id in ids}

    def _collect(active: Any) -> None:
        for field in targets:
            config = field.config or {}
            joined, first, max_col = lookup_column_names(field)
            for name in (joined, first, max_col):
                if name not in columns:
                    columns.append(name)
            link_field = _find_link_field(table, config.get("via_link_field_id"))
            multiple = bool(((link_field.config or {}) if link_field is not None else {}).get("multiple", True))
            values_by_row = _resolve_lookup_values(engine, db, table, config, ids, conn=active, links_cache=links_cache)
            for row_id in ids:
                enc_joined, enc_first, enc_max = encode_lookup_values(multiple, values_by_row.get(row_id))
                payload[row_id][joined] = enc_joined
                payload[row_id][first] = enc_first
                payload[row_id][max_col] = enc_max

    def _write(active: Any) -> None:
        _collect(active)
        # 用 text() 直接绑定：列类型是 BLOB，SQLAlchemy 的 LargeBinary 处理器
        # 只接受 bytes，会把 str/int 误转 memoryview；这里由 SQLite 按存储类落库。
        assignments = ", ".join(f'"{name}" = :{name}' for name in columns)
        statement = text(f'UPDATE "{table.db_table_name}" SET {assignments} WHERE "id" = :_rid')
        active.execute(statement, list(payload.values()))

    if conn is not None:
        _write(conn)
    else:
        with engine.begin() as active_conn:
            _write(active_conn)
    return len(ids)


# ── 级联重算 ─────────────────────────────────────────


def _active_lookup_fields(db: Session) -> list[DataField]:
    return (
        db.query(DataField)
        .filter(DataField.field_type == "lookup", DataField.trashed == False)  # noqa: E712
        .all()
    )


def _consumer_row_ids(
    engine: Engine,
    link_field: DataField,
    target_row_ids: list[int],
    conn: Connection | None,
) -> list[int]:
    """查出关联了给定目标行 id 的消费方行 id."""
    try:
        link_table = get_reflected_table(engine, link_field.link_table_name)
    except RuntimeError:
        return []
    with nullcontext(conn) if conn is not None else engine.connect() as active:
        rows = active.execute(
            select(link_table.c.row_id).where(link_table.c.target_row_id.in_(target_row_ids)).distinct()
        ).all()
    return sorted({int(r[0]) for r in rows})


def _resync_fields(
    engine: Engine,
    db: Session,
    lookup_field_ids: Iterable[int],
    target_row_ids: list[int],
    *,
    conn: Connection | None,
) -> int:
    """按 lookup 字段集合重算消费方行（同一事务，调用方负责提交）."""
    wanted = set(lookup_field_ids)
    by_table: dict[int, dict[str, Any]] = {}
    for lookup_field in _active_lookup_fields(db):
        if lookup_field.id not in wanted:
            continue
        config = lookup_field.config or {}
        link_field = db.get(DataField, config.get("via_link_field_id"))
        owner_table = db.get(DataTable, lookup_field.table_id)
        if link_field is None or owner_table is None:
            continue
        entry = by_table.setdefault(owner_table.id, {"table": owner_table, "fields": []})
        entry["fields"].append(lookup_field)
        entry.setdefault("link_fields", {})[lookup_field.id] = link_field

    total = 0
    for entry in by_table.values():
        consumer_table: DataTable = entry["table"]
        row_ids: set[int] = set()
        for lookup_field in entry["fields"]:
            link_field = entry["link_fields"][lookup_field.id]
            row_ids.update(_consumer_row_ids(engine, link_field, target_row_ids, conn))
        if not row_ids:
            continue
        total += sync_lookup_columns(
            engine,
            consumer_table,
            row_ids,
            db=db,
            conn=conn,
            fields=entry["fields"],
        )
    return total


def resync_lookup_consumers(
    engine: Engine,
    source_table: DataTable,
    row_ids: Iterable[int],
    *,
    db: Session | None,
    conn: Connection | None = None,
    changed_field_names: Iterable[str] | None = None,
) -> int:
    """源表行数据变更后，级联重算引用这些源字段的 lookup 冗余列.

    Args:
        source_table: 被修改 / 删除行的表（作为 lookup 的源表）.
        row_ids: 变更的源行 id.
        changed_field_names: 本次变更涉及的字段（用户可见名）；None 表示整行变更
            （例如目标行被硬删除），按该表全部源字段处理.
    """
    ids = sorted({int(r) for r in row_ids})
    if db is None or not ids:
        return 0

    active_fields = source_table.active_fields()
    if changed_field_names is None:
        source_field_ids = {f.id for f in active_fields}
        field_by_id = {f.id: f for f in active_fields}
    else:
        names = set(changed_field_names)
        selected = [f for f in active_fields if f.name in names]
        source_field_ids = {f.id for f in selected}
        field_by_id = {f.id: f for f in selected}
    if not source_field_ids:
        return 0

    lookup_field_ids: list[int] = []
    for lookup_field in _active_lookup_fields(db):
        config = lookup_field.config or {}
        sid = config.get("source_field_id")
        if sid in source_field_ids and field_by_id.get(sid) is not None:
            lookup_field_ids.append(lookup_field.id)
    if not lookup_field_ids:
        return 0
    return _resync_fields(engine, db, lookup_field_ids, ids, conn=conn)


def resync_lookup_consumers_for_deleted_rows(
    engine: Engine,
    table: DataTable,
    row_ids: Iterable[int],
    *,
    db: Session | None,
    conn: Connection | None = None,
) -> int:
    """目标行被硬删除后，级联重算所有引用该表字段的 lookup 冗余列."""
    ids = sorted({int(r) for r in row_ids})
    if db is None or not ids:
        return 0
    source_field_ids = {f.id for f in table.active_fields()}
    lookup_field_ids = [
        lf.id for lf in _active_lookup_fields(db) if (lf.config or {}).get("source_field_id") in source_field_ids
    ]
    if not lookup_field_ids:
        return 0
    return _resync_fields(engine, db, lookup_field_ids, ids, conn=conn)


def resync_lookup_fields(
    engine: Engine,
    db: Session,
    lookup_fields: Iterable[DataField],
    *,
    batch_size: int | None = None,
) -> int:
    """重算指定 lookup 字段的全表冗余列（字段配置 / 源字段类型变化后使用）."""
    if db is None:
        return 0
    by_table: dict[int, list[DataField]] = {}
    for field in lookup_fields:
        by_table.setdefault(field.table_id, []).append(field)
    total = 0
    for table_id, fields in by_table.items():
        table = db.get(DataTable, table_id)
        if table is None:
            continue
        total += backfill_lookup_columns(engine, table, db=db, fields=fields, batch_size=batch_size)
    return total


def lookup_fields_by_source_field(db: Session, source_field_id: int) -> list[DataField]:
    """返回引用了指定源字段的全部未回收 lookup 字段（跨表）."""
    return [f for f in _active_lookup_fields(db) if (f.config or {}).get("source_field_id") == source_field_id]


def lookup_fields_by_via_link(db: Session, link_field_id: int) -> list[DataField]:
    """返回通过指定 link 字段取值的全部未回收 lookup 字段（同表）."""
    return [f for f in _active_lookup_fields(db) if (f.config or {}).get("via_link_field_id") == link_field_id]


# ── 历史数据回填 ─────────────────────────────────────


def _batch_size(explicit: int | None) -> int:
    from cndb.core.config import settings

    value = explicit if explicit is not None else getattr(settings, "LOOKUP_BACKFILL_BATCH_SIZE", 1000)
    try:
        size = int(value)
    except (TypeError, ValueError):
        return 1000
    return size if size > 0 else 1000


def iter_table_row_ids(
    engine: Engine,
    table: DataTable,
    batch_size: int,
    *,
    bind: Any = None,
) -> Iterable[list[int]]:
    """按主键游标分批读取行 id（避免一次性加载整表 id）."""
    sa_table = get_reflected_table(bind if bind is not None else engine, table.db_table_name)
    last_id = 0
    while True:
        query = select(sa_table.c.id).where(sa_table.c.id > last_id).order_by(sa_table.c.id).limit(batch_size)
        if bind is not None:
            rows = bind.execute(query).all()
        else:
            with engine.connect() as conn:
                rows = conn.execute(query).all()
        ids = [int(r[0]) for r in rows]
        if not ids:
            return
        yield ids
        last_id = ids[-1]


def backfill_lookup_columns(
    engine: Engine,
    table: DataTable,
    *,
    db: Session | None,
    fields: list[DataField] | None = None,
    batch_size: int | None = None,
    conn: Connection | None = None,
    bind: Any = None,
) -> int:
    """分批回填（或重算）一张表的 lookup 冗余列，幂等可重入.

    Args:
        conn / bind: 迁移场景复用同一事务连接（SQLite 下新列对其它连接不可见）.

    Returns:
        处理的行数.
    """
    if db is None:
        return 0
    size = _batch_size(batch_size)
    processed = 0
    for ids in iter_table_row_ids(engine, table, size, bind=bind):
        processed += sync_lookup_columns(engine, table, ids, db=db, conn=conn, fields=fields, bind=bind)
    return processed


__all__ = [
    "backfill_lookup_columns",
    "encode_lookup_values",
    "iter_table_row_ids",
    "lookup_columns_enabled",
    "lookup_columns_present",
    "lookup_fields_by_source_field",
    "lookup_fields_by_via_link",
    "lookup_fields_with_columns",
    "lookup_pushdown_available",
    "resync_lookup_consumers",
    "resync_lookup_consumers_for_deleted_rows",
    "resync_lookup_fields",
    "sync_lookup_columns",
]
