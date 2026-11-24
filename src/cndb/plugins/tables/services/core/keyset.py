"""keyset（游标）分页（需求 0148）.

问题：列表用 `LIMIT/OFFSET`，深翻页时 SQLite 要顺序跳过前 N 行（10 万偏移实测秒级），
大表上第 1000 页几乎不可用。keyset 用「上一页最后一行的排序键」作为游标，
直接 `WHERE (sort_key, id) > (v1, v2)`，翻页成本与页码无关。

口径：
- 无排序 → 按 `id` 升序（唯一、永不为空），游标 = `[id]`；
- 有排序 → 排序键 + `id` 兜底（保证唯一），游标 = `[sort1, ..., sortN, id]`；
- **NULL 排序键不支持游标**：SQLite 下 NULL 的先后位置让"大于某个 NULL"没有稳定语义，
  游标里出现 NULL 直接 400（提示改用 offset 或加筛选），不静默跳行 / 重复行；
- 游标是 base64 的 JSON（客户端当不透明串回传），解码失败 → 400。
"""

from __future__ import annotations

import base64
import json
from typing import Any

from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.models import DataTable

#: 游标解码失败 / 形状不符的错误文案（路由直接转 400）
CURSOR_INVALID = "分页游标无效（请从上一页响应的 next_cursor 原样回传）"
CURSOR_NULL_KEY = "游标里含空排序值，暂不支持 keyset 翻页；请改用 offset 或补充筛选条件"
CURSOR_TOO_LONG = "游标长度超出上限（可能是伪造或超长排序链）"

#: 排序链最大长度（列数 + id）
MAX_CURSOR_VALUES = 8


def encode_cursor(values: list[Any]) -> str:
    """把一行的排序键值编码成不透明游标（base64 JSON）."""
    raw = json.dumps({"v": values}, ensure_ascii=False, separators=(",", ":"), default=str)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> list[Any]:
    """解码游标；形状非法 / 超长抛 ValueError（由调用方转 400）."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
    except Exception as exc:
        raise ValueError(CURSOR_INVALID) from exc
    values = payload.get("v") if isinstance(payload, dict) else None
    if not isinstance(values, list) or not values:
        raise ValueError(CURSOR_INVALID)
    if len(values) > MAX_CURSOR_VALUES:
        raise ValueError(CURSOR_TOO_LONG)
    return values


def build_keyset_where(
    table: DataTable,
    sa_table: Any,
    sorts: list[dict[str, str]] | None,
    cursor_values: list[Any],
) -> Any:
    """按游标构造 ``WHERE``（OR 链：前缀相等 + 当前列严格大于/小于）.

    Args:
        sorts: 与列表查询同一份排序声明（缺省 = 按 id）。
        cursor_values: ``decode_cursor`` 的结果（长度必须等于 排序键数 + 1）。
    """
    from sqlalchemy import and_, or_

    columns: list[tuple[Any, str]] = []
    for item in sorts or []:
        if not isinstance(item, dict):
            raise ValueError("排序声明必须是对象")
        name = item.get("field_name") or item.get("field")
        field = next((f for f in table.active_fields() if f.name == name), None)
        if field is None:
            raise ValueError(f"排序字段不存在: {name}")
        ft = default_registry.get(field.field_type)
        if ft is None or not ft.has_physical_column:
            raise ValueError(f"字段「{name}」没有物理列，不支持 keyset 翻页")
        direction = "desc" if str(item.get("direction", "asc")).lower() == "desc" else "asc"
        columns.append((sa_table.c[field.db_column_name], direction))
    columns.append((sa_table.c.id, "asc"))

    if len(cursor_values) != len(columns):
        raise ValueError(CURSOR_INVALID)
    # 排序键出现 NULL 就没有稳定的"大于/小于"语义 → 明确拒绝（不静默跳行 / 重复行）
    if any(value is None for value in cursor_values[:-1]):
        raise ValueError(CURSOR_NULL_KEY)

    clauses: list[Any] = []
    for index, (column, direction) in enumerate(columns):
        prefix = [columns[i][0] == cursor_values[i] for i in range(index)]
        compare = column < cursor_values[index] if direction == "desc" else column > cursor_values[index]
        clauses.append(and_(*prefix, compare) if prefix else compare)
    return or_(*clauses)


__all__ = [
    "CURSOR_INVALID",
    "CURSOR_NULL_KEY",
    "CURSOR_TOO_LONG",
    "MAX_CURSOR_VALUES",
    "build_keyset_where",
    "decode_cursor",
    "encode_cursor",
]
