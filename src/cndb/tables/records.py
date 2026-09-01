"""行数据访问层：按元数据校验用户输入，并编译为参数化 SQL 读写物理表.

对外统一"字段名 -> 值"的行表示，内部转换为"物理列名 -> 归一化值"；
所有 SQL 均参数化传值，标识符全部系统生成，杜绝注入。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from django.db import connection, transaction

from cndb.tables.field_types import FieldTypeError, get_field_type
from cndb.tables.models import DataField, DataTable
from cndb.tables.query import RowQuery
from cndb.tables.sql import now, quote


class InvalidRowError(Exception):
    """行数据非法（未知字段/值校验失败/必填缺失）."""


def clean_row(table: DataTable, row_data: Mapping[str, Any], *, partial: bool = False) -> dict[str, Any]:
    """把"字段名 -> 值"校验为"物理列名 -> 数据库参数"，非法抛 InvalidRowError.

    partial=True 用于局部更新：跳过必填校验，仅校验出现的字段。
    """
    fields_by_name = {str(field.name): field for field in table.active_fields()}
    cleaned: dict[str, Any] = {}
    for name, value in row_data.items():
        field = fields_by_name.get(name)
        if field is None:
            raise InvalidRowError(f"未知字段: {name}")
        field_type = get_field_type(str(field.field_type))
        try:
            normalized = field_type.validate_value(value, field.config)  # type: ignore[bad-argument-type]
            cleaned[str(field.db_column_name)] = field_type.to_db(normalized, field.config)  # type: ignore[bad-argument-type]
        except FieldTypeError as exc:
            raise InvalidRowError(f"字段 {name} 的值非法: {exc}") from exc
    if not partial:
        for name, field in fields_by_name.items():
            if field.required and row_data.get(name) is None:
                raise InvalidRowError(f"必填字段缺失: {name}")
    return cleaned


def insert_row(table: DataTable, cleaned: dict[str, Any]) -> int:
    """插入一行并返回主键 id."""
    if not cleaned:
        sql = f"INSERT INTO {quote(table.db_table_name)} DEFAULT VALUES RETURNING {quote('id')}"
        params: list[Any] = []
    else:
        columns = ", ".join(quote(name) for name in cleaned)
        placeholders = ", ".join(["%s"] * len(cleaned))
        sql = f"INSERT INTO {quote(table.db_table_name)} ({columns}) VALUES ({placeholders}) RETURNING {quote('id')}"
        params = list(cleaned.values())
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    assert row is not None, "INSERT ... RETURNING 必然返回一行"
    return int(row[0])


def update_row(table: DataTable, row_id: int, cleaned: dict[str, Any]) -> bool:
    """按主键更新指定列并刷新 updated_on，返回是否命中行."""
    set_clause = ", ".join(f"{quote(name)} = %s" for name in cleaned)
    sql = (
        f"UPDATE {quote(table.db_table_name)} SET {set_clause}, "
        f"{quote('updated_on')} = {now()} WHERE {quote('id')} = %s"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, [*cleaned.values(), row_id])
        return cursor.rowcount > 0


def delete_row(table: DataTable, row_id: int) -> bool:
    """按主键删除行，返回是否命中."""
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {quote(table.db_table_name)} WHERE {quote('id')} = %s", [row_id])
        return cursor.rowcount > 0


def insert_rows(table: DataTable, cleaned_rows: Sequence[dict[str, Any]]) -> list[int]:
    """批量插入多行，按插入顺序返回主键 id 列表.

    各行列集合允许不同：取列并集，缺失列写 NULL；
    单条多值 INSERT 天然原子，RETURNING 顺序与 VALUES 顺序一致。
    """
    if not cleaned_rows:
        return []
    columns: list[str] = []
    for cleaned in cleaned_rows:
        for name in cleaned:
            if name not in columns:
                columns.append(name)
    if not columns:
        # 全部为空行：退化为逐条默认值插入（同处一个调用，外部可包事务保证原子）
        with transaction.atomic():  # type: ignore[bad-context-manager]
            return [insert_row(table, {}) for _ in cleaned_rows]
    column_list = ", ".join(quote(name) for name in columns)
    values_clause = ", ".join(f"({', '.join(['%s'] * len(columns))})" for _ in cleaned_rows)
    sql = f"INSERT INTO {quote(table.db_table_name)} ({column_list}) VALUES {values_clause} RETURNING {quote('id')}"
    params: list[Any] = []
    for cleaned in cleaned_rows:
        params.extend(cleaned.get(name) for name in columns)
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return [int(row[0]) for row in cursor.fetchall()]


def update_rows(table: DataTable, updates: Mapping[int, dict[str, Any]]) -> int:
    """批量按主键更新多行，整体一个事务（全成或全败），返回命中行数."""
    with transaction.atomic():  # type: ignore[bad-context-manager]
        return sum(update_row(table, row_id, cleaned) for row_id, cleaned in updates.items())


def delete_rows(table: DataTable, row_ids: Sequence[int]) -> int:
    """按主键集合批量删除行（去重后 IN 匹配），返回删除行数."""
    ids = list(dict.fromkeys(row_ids))
    if not ids:
        return 0
    placeholders = ", ".join(["%s"] * len(ids))
    sql = f"DELETE FROM {quote(table.db_table_name)} WHERE {quote('id')} IN ({placeholders})"
    with connection.cursor() as cursor:
        cursor.execute(sql, ids)
        return int(cursor.rowcount)


def _row_to_dict(fields: Sequence[DataField], db_row: tuple[Any, ...], columns: list[str]) -> dict[str, Any]:
    """把物理行元组映射回"字段名 -> 值"，附带 id 与时间戳."""
    result: dict[str, Any] = {"id": db_row[columns.index("id")]}
    for name in ("created_on", "updated_on"):
        result[name] = db_row[columns.index(name)]
    for field in fields:
        field_type = get_field_type(str(field.field_type))
        raw = db_row[columns.index(str(field.db_column_name))]
        result[str(field.name)] = field_type.from_db(raw, field.config)  # type: ignore[bad-argument-type]
    return result


def _row_columns(fields: Sequence[DataField]) -> list[str]:
    """行读取的列集合：id/时间戳 + 全部业务列."""
    return ["id", "created_on", "updated_on", *(str(field.db_column_name) for field in fields)]


def fetch_rows(table: DataTable, spec: RowQuery) -> list[dict[str, Any]]:
    """按编译好的查询描述读取行（WHERE/ORDER 片段由 query 模块生成，值参数化）."""
    fields = table.active_fields()
    columns = _row_columns(fields)
    select = ", ".join(quote(name) for name in columns)
    order_clause = spec.order or f" ORDER BY {quote('id')}"
    sql = f"SELECT {select} FROM {quote(table.db_table_name)}{spec.where}{order_clause}"
    sql_params: list[Any] = list(spec.params)
    if spec.limit is not None:
        sql += " LIMIT %s OFFSET %s"
        sql_params.extend([spec.limit, spec.offset])
    with connection.cursor() as cursor:
        cursor.execute(sql, sql_params)
        db_rows = cursor.fetchall()
    return [_row_to_dict(fields, row, columns) for row in db_rows]


def count_rows(table: DataTable, spec: RowQuery) -> int:
    """按编译好的查询描述统计行数（忽略排序与分页）."""
    sql = f"SELECT COUNT(*) FROM {quote(table.db_table_name)}{spec.where}"
    with connection.cursor() as cursor:
        cursor.execute(sql, list(spec.params))
        row = cursor.fetchone()
    assert row is not None, "COUNT 必然返回一行"
    return int(row[0])


def fetch_row(table: DataTable, row_id: int) -> dict[str, Any] | None:
    """按主键读取单行，不存在返回 None."""
    fields = table.active_fields()
    columns = _row_columns(fields)
    select = ", ".join(quote(name) for name in columns)
    sql = f"SELECT {select} FROM {quote(table.db_table_name)} WHERE {quote('id')} = %s"
    with connection.cursor() as cursor:
        cursor.execute(sql, [row_id])
        row = cursor.fetchone()
    return None if row is None else _row_to_dict(fields, row, columns)


def fetch_rows_by_ids(table: DataTable, row_ids: Sequence[int]) -> list[dict[str, Any]]:
    """按主键集合读取行，按传入 id 顺序返回（不存在的主键跳过）."""
    ids = list(dict.fromkeys(row_ids))
    if not ids:
        return []
    fields = table.active_fields()
    columns = _row_columns(fields)
    select = ", ".join(quote(name) for name in columns)
    placeholders = ", ".join(["%s"] * len(ids))
    sql = f"SELECT {select} FROM {quote(table.db_table_name)} WHERE {quote('id')} IN ({placeholders})"
    with connection.cursor() as cursor:
        cursor.execute(sql, ids)
        rows_by_id = {int(row[columns.index("id")]): _row_to_dict(fields, row, columns) for row in cursor.fetchall()}
    return [rows_by_id[row_id] for row_id in ids if row_id in rows_by_id]
