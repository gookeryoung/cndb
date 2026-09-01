"""DDL 引擎：元数据驱动物理表的创建与结构变更.

核心安全设计：物理表名/列名均由系统生成（table_/field_ + 随机十六进制），
用户输入永不进入 DDL；列类型来自注册的字段类型系统（封闭集合），从根源杜绝注入。
PostgreSQL 与 SQLite 的方言差异在本模块内消化。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.db import connection

from cndb.tables.field_types import FieldType, get_field_type
from cndb.tables.models import DataField, DataTable
from cndb.tables.sql import quote as _quote

# SQLite 不支持的列类型到等价类型的映射
_SQLITE_TYPE_MAP = {"jsonb": "text"}


def _column_type(field_type: FieldType, config: object) -> str:
    """返回当前方言下的列类型."""
    column_type = field_type.db_column_type(config)  # type: ignore[bad-argument-type]
    if connection.vendor == "sqlite":
        column_type = _SQLITE_TYPE_MAP.get(column_type, column_type)
    return column_type


def _id_column_ddl() -> str:
    """主键列 DDL：PostgreSQL 用 bigserial，SQLite 用自增整数."""
    if connection.vendor == "postgresql":
        return f"{_quote('id')} bigserial PRIMARY KEY"
    return f"{_quote('id')} integer PRIMARY KEY AUTOINCREMENT"


def _timestamp_column_ddl(name: str) -> str:
    """时间戳列 DDL：行级创建/更新时间，两方言各自提供默认值."""
    if connection.vendor == "postgresql":
        return f"{_quote(name)} timestamptz NOT NULL DEFAULT now()"
    # current_timestamp 等价 datetime('now')，且无括号便于 Django 内省解析
    return f"{_quote(name)} text NOT NULL DEFAULT current_timestamp"


def _column_ddl(field: DataField) -> str:
    """单个业务列的 DDL 片段."""
    field_type = get_field_type(str(field.field_type))
    return f"{_quote(field.db_column_name)} {_column_type(field_type, field.config)}"


def _execute(sql: str, params: Sequence[Any] | None = None) -> None:
    """在当前连接上执行原生 SQL."""
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


def create_physical_table(table: DataTable) -> None:
    """按当前元数据创建物理表：id 主键 + 时间戳列 + 全部未回收字段."""
    columns = [_id_column_ddl(), _timestamp_column_ddl("created_on"), _timestamp_column_ddl("updated_on")]
    columns.extend(_column_ddl(field) for field in table.active_fields())
    _execute(f"CREATE TABLE {_quote(table.db_table_name)} ({', '.join(columns)})")


def drop_physical_table(table: DataTable) -> None:
    """删除物理表."""
    _execute(f"DROP TABLE IF EXISTS {_quote(table.db_table_name)}")


def add_physical_column(field: DataField) -> None:
    """为物理表新增一列."""
    _execute(f"ALTER TABLE {_quote(field.table.db_table_name)} ADD COLUMN {_column_ddl(field)}")


def drop_physical_column(field: DataField) -> None:
    """从物理表删除一列."""
    _execute(f"ALTER TABLE {_quote(field.table.db_table_name)} DROP COLUMN {_quote(field.db_column_name)}")


def alter_physical_column_type(field: DataField) -> None:
    """修改列类型：统一走重建表（改名旧表 → 按新元数据建同名表 → 带转换拷贝 → 删旧表）.

    SQLite 不支持修改列类型；PostgreSQL 虽支持 ALTER TYPE，但统一重建可让两方言行为
    一致并顺带处理精度收缩等场景。调用方须处于事务中以保证失败可整体回滚，
    并保证调用前新旧列类型字符串确已不同（仅结构变化的列才会触发 CAST 转换）。
    """
    table = field.table
    old_name = f"{table.db_table_name}_old"
    _execute(f"ALTER TABLE {_quote(table.db_table_name)} RENAME TO {_quote(old_name)}")
    create_physical_table(table)
    field_type = get_field_type(str(field.field_type))
    new_type = _column_type(field_type, field.config)
    column_names = ["id", "created_on", "updated_on"]
    column_names.extend(str(item.db_column_name) for item in table.active_fields())
    select_parts = [
        f"CAST({_quote(field.db_column_name)} AS {new_type})" if name == field.db_column_name else _quote(name)
        for name in column_names
    ]
    _execute(
        f"INSERT INTO {_quote(table.db_table_name)} ({', '.join(_quote(name) for name in column_names)}) "
        f"SELECT {', '.join(select_parts)} FROM {_quote(old_name)}"
    )
    _execute(f"DROP TABLE {_quote(old_name)}")
    if connection.vendor == "postgresql":
        # 重建后序列停在初始位置，须同步到当前最大 id，否则后续插入主键冲突
        _execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
            f"COALESCE((SELECT MAX({_quote('id')}) FROM {_quote(table.db_table_name)}), 0) + 1, false)",
            [table.db_table_name],
        )
