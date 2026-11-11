"""lookup 冗余列的命名与基础定义（ADR 0131）.

lookup 字段本身是虚拟字段（无物理列），为了让过滤 / 排序 / 分页下推 SQL，
在持有该 lookup 字段的物理表上维护三列：

- ``_lk_<db_column_name>``         拼接值：多值用 U+001F 连接；单值为原始值；
                                   多值无关联时为 ``''``，单值无关联时为 NULL
- ``_lk_<db_column_name>_first``   最小解析值（排序 ASC / contains_all 的最小值语义）
- ``_lk_<db_column_name>_max``     最大解析值（排序 DESC）

三列在 SQLite 上使用 BLOB（无类型亲和性），以保留源字段原始类型（数字按数字排序、
日期/文本按文本排序）；PostgreSQL 使用 TEXT（已知限制：数字源字段排序按文本）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cndb.plugins.tables.models import DataField, DataTable

LOOKUP_SEP = "\x1f"
LOOKUP_PREFIX = "_lk_"

INFIX_OR, INFIX_AND, INFIX_QUERY_OR = "__or__", "__and__", "__query_or__"
GROUP_KEYS = (INFIX_OR, INFIX_AND, INFIX_QUERY_OR)


def lookup_column_names_for(db_column_name: str) -> tuple[str, str, str]:
    """按物理列名返回 (拼接值列, 最小值列, 最大值列)（迁移等无 ORM 对象场景使用）."""
    base = f"{LOOKUP_PREFIX}{db_column_name}"
    return base, f"{base}_first", f"{base}_max"


def lookup_column_names(field: DataField) -> tuple[str, str, str]:
    """返回 (拼接值列, 最小值列, 最大值列) 的物理列名."""
    return lookup_column_names_for(field.db_column_name)


def lookup_fields(table: DataTable) -> list[DataField]:
    """表中全部未回收 lookup 字段."""
    return [f for f in table.active_fields() if f.field_type == "lookup"]
