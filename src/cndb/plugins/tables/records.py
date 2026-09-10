"""行 CRUD 引擎 —— 基于动态 sa.Table 的数据读写.

核心职责：
- create_row / get_row / update_row / delete_row（单行）
- list_rows（列表查询，支持筛选/排序/分页）
- bulk_create / bulk_update / bulk_delete（批量）
- trash_row / restore_row（软删除/恢复）

所有写入值都经过 field_types 的 validate_value 规范化后才入库.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import MetaData, Table, and_, or_

from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.models import DataField, DataTable

logger = logging.getLogger(__name__)


# ── 值规范化 ──────────────────────────────────────────


def _normalize_values(
    table: DataTable,
    values: dict[str, Any],
    *,
    for_update: bool = False,
) -> dict[str, Any]:
    """把前端传入的 {field_name: raw_value} 转为 {db_column_name: normalized_value}.

    - 根据 DataField.field_type 调用 validate_value 做类型强转和校验
    - 跳过 None（除非 required 字段）
    - 字段不存在于 table.fields 时忽略（安全起见不报错）
    """
    field_map: dict[str, DataField] = {f.name: f for f in table.fields}
    result: dict[str, Any] = {}

    for field_name, raw in values.items():
        f = field_map.get(field_name)
        if f is None:
            logger.debug("未知字段 %s，跳过", field_name)
            continue
        if raw is None:
            if f.required and not for_update:
                raise ValueError(f"必填字段 {field_name} 不能为空")
            continue
        ft = default_registry.get(f.field_type)
        if ft is None:
            raise ValueError(f"未知字段类型: {f.field_type}")
        try:
            result[f.db_column_name] = ft.validate_value(raw, f.config)
        except Exception as exc:
            raise ValueError(f"字段 {field_name}({f.field_type}) 值校验失败: {exc}") from exc

    # 检查缺失的必填字段
    if not for_update:
        for f in table.fields:
            if f.trashed or not f.required:
                continue
            if f.db_column_name not in result:
                raise ValueError(f"必填字段 {f.name} 不能为空")

    return result


# ── 单表 sa.Table 获取（带缓存） ─────────────────────


def _get_sa_table(engine: Any, table: DataTable) -> Table:
    """获取已存在的物理表 sa.Table 对象.

    优先从 engine.dialect 反射；不存在则抛异常（create_table 应先被调用）.
    """
    metadata = MetaData()
    metadata.reflect(bind=engine, only=[table.db_table_name])
    if table.db_table_name not in metadata.tables:
        raise RuntimeError(f"物理表 {table.db_table_name} 不存在，请先调用 create_table()")
    return metadata.tables[table.db_table_name]


# ── CREATE ───────────────────────────────────────────


def create_row(engine: Any, table: DataTable, values: dict[str, Any]) -> dict[str, Any] | None:
    """创建一行，返回完整行数据（含自增 id 和默认值字段）."""
    sa_table = _get_sa_table(engine, table)
    normalized = _normalize_values(table, values)

    with engine.begin() as conn:
        result = conn.execute(sa_table.insert().values(**normalized))
        row_id = result.lastrowid

    return get_row(engine, table, row_id)


# ── READ ─────────────────────────────────────────────


def get_row(engine: Any, table: DataTable, row_id: int) -> dict[str, Any] | None:
    """按主键读取单行，返回 dict；不存在返回 None（含软删除过滤）."""
    sa_table = _get_sa_table(engine, table)
    with engine.connect() as conn:
        row = conn.execute(
            sa_table.select().where(
                sa_table.c.id == row_id,
                sa_table.c._trashed.is_(False),
            )
        ).first()
    if row is None:
        return None
    return _row_to_dict(table, sa_table, row)


def list_rows(  # noqa: PLR0913
    engine: Any,
    table: DataTable,
    *,
    filters: list[dict[str, Any]] | None = None,
    filter_logic: str = "AND",
    sorts: list[dict[str, str]] | None = None,
    limit: int = 100,
    offset: int = 0,
    include_trashed: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """列表查询，返回 (rows, total_count).

    Args:
        filters: 过滤条件列表，每项 {field_name, op, value}. op 见 query.py.
        filter_logic: "AND" 或 "OR"，多条件组合方式.
        sorts: 排序列表，每项 {field_name, direction}，direction="asc"|"desc".
        limit / offset: 分页.
        include_trashed: 是否包含软删除行.
    """
    from cndb.plugins.tables.query import compile_filters, compile_sorts

    sa_table = _get_sa_table(engine, table)

    # 基础 where
    where_clauses: list[Any] = []
    if not include_trashed:
        where_clauses.append(sa_table.c._trashed.is_(False))

    # 业务过滤
    if filters:
        compiled = compile_filters(table, sa_table, filters, filter_logic)
        if compiled is not None:
            where_clauses.append(compiled)

    # 构建 base query
    query = sa_table.select()
    if where_clauses:
        if len(where_clauses) == 1:
            query = query.where(where_clauses[0])
        else:
            combined = and_(*where_clauses) if filter_logic.upper() == "AND" else or_(*where_clauses)
            query = query.where(combined)

    # total count
    with engine.connect() as conn:
        total = conn.execute(
            sa_table.select()
            .with_only_columns(__import__("sqlalchemy", fromlist=["func"]).func.count(sa_table.c.id))
            .where(*where_clauses)
            if where_clauses
            else sa_table.select().with_only_columns(
                __import__("sqlalchemy", fromlist=["func"]).func.count(sa_table.c.id)
            )
        ).scalar()

        # 排序
        if sorts:
            query = query.order_by(*compile_sorts(table, sa_table, sorts))

        # 分页
        query = query.limit(limit).offset(offset)

        rows = conn.execute(query).all()

    return [_row_to_dict(table, sa_table, r) for r in rows], total or 0


# ── UPDATE ───────────────────────────────────────────


def update_row(
    engine: Any,
    table: DataTable,
    row_id: int,
    values: dict[str, Any],
) -> dict[str, Any] | None:
    """更新一行，返回更新后的完整数据；行不存在或已软删除返回 None."""
    sa_table = _get_sa_table(engine, table)
    normalized = _normalize_values(table, values, for_update=True)

    if not normalized:
        return get_row(engine, table, row_id)

    with engine.begin() as conn:
        result = conn.execute(
            sa_table.update()
            .where(
                sa_table.c.id == row_id,
                sa_table.c._trashed.is_(False),
            )
            .values(**normalized)
        )
        if result.rowcount == 0:
            return None

    return get_row(engine, table, row_id)


# ── DELETE ───────────────────────────────────────────


def delete_row(engine: Any, table: DataTable, row_id: int) -> bool:
    """硬删除单行，返回是否成功."""
    sa_table = _get_sa_table(engine, table)
    with engine.begin() as conn:
        result = conn.execute(
            sa_table.delete().where(
                sa_table.c.id == row_id,
                sa_table.c._trashed.is_(False),
            )
        )
        return result.rowcount > 0


# ── 软删除 / 恢复 ────────────────────────────────────


def trash_row(engine: Any, table: DataTable, row_id: int) -> bool:
    """软删除（标记 _trashed=True）."""
    sa_table = _get_sa_table(engine, table)
    with engine.begin() as conn:
        result = conn.execute(
            sa_table.update()
            .where(sa_table.c.id == row_id)
            .values(
                _trashed=True,
                _trashed_at=datetime.now(UTC),
            )
        )
        return result.rowcount > 0


def restore_row(engine: Any, table: DataTable, row_id: int) -> bool:
    """从回收站恢复."""
    sa_table = _get_sa_table(engine, table)
    with engine.begin() as conn:
        result = conn.execute(
            sa_table.update()
            .where(sa_table.c.id == row_id)
            .values(
                _trashed=False,
                _trashed_at=None,
            )
        )
        return result.rowcount > 0


# ── BULK ─────────────────────────────────────────────


def bulk_create(
    engine: Any,
    table: DataTable,
    rows: list[dict[str, Any]],
) -> list[int]:
    """批量创建，返回新行 id 列表."""
    sa_table = _get_sa_table(engine, table)
    normalized_list = [_normalize_values(table, r) for r in rows]

    ids: list[int] = []
    with engine.begin() as conn:
        for values in normalized_list:
            result = conn.execute(sa_table.insert().values(**values))
            ids.append(result.lastrowid)

    return ids


def bulk_update(
    engine: Any,
    table: DataTable,
    row_ids: list[int],
    values: dict[str, Any],
) -> int:
    """批量更新，返回影响行数."""
    sa_table = _get_sa_table(engine, table)
    normalized = _normalize_values(table, values, for_update=True)
    if not normalized:
        return 0

    with engine.begin() as conn:
        result = conn.execute(
            sa_table.update()
            .where(
                sa_table.c.id.in_(row_ids),
                sa_table.c._trashed.is_(False),
            )
            .values(**normalized)
        )
        return result.rowcount


def bulk_delete(engine: Any, table: DataTable, row_ids: list[int]) -> int:
    """批量硬删除，返回影响行数."""
    sa_table = _get_sa_table(engine, table)
    with engine.begin() as conn:
        result = conn.execute(
            sa_table.delete().where(
                sa_table.c.id.in_(row_ids),
                sa_table.c._trashed.is_(False),
            )
        )
        return result.rowcount


# ── 内部辅助 ─────────────────────────────────────────


def _row_to_dict(table: DataTable, _sa_table: Table, row: Any) -> dict[str, Any]:
    """把 Row 对象转为前端友好的 dict（用 field_name 作为 key，不是 db_column_name）."""
    field_map_rev: dict[str, DataField] = {f.db_column_name: f for f in table.fields}
    result: dict[str, Any] = {}

    for col_name, value in row._mapping.items():
        if col_name == "id":
            result["id"] = value
            continue
        if col_name in ("_trashed", "_trashed_at"):
            continue
        f = field_map_rev.get(col_name)
        if f is not None:
            result[f.name] = value
        else:
            result[col_name] = value

    return result


__all__ = [
    "bulk_create",
    "bulk_delete",
    "bulk_update",
    "create_row",
    "delete_row",
    "get_row",
    "list_rows",
    "restore_row",
    "trash_row",
    "update_row",
]
