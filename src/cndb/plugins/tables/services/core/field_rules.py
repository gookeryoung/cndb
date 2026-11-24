"""字段级领域校验规则（需求 0146）：模式匹配 + 条件必填.

配置都放在 `DataField.config`（不新增列，旧配置零影响）：

```json
{
  "validation": {"pattern": "^[A-Z]{2}\\d{4}$", "message": "编号格式应为 AB1234"},
  "required_when": {"field": "状态", "op": "eq", "value": "已完成"}
}
```

口径：
- 写路径统一（直编 create/update 与导入 RowValidator 共用 `validate_row_constraints`）；
- update 基于**合并后的行值**判定条件必填（补丁 + 当前值），否则"把状态改成已完成但不填完成时间"拦不住；
- 空值 / 空串不参与模式校验（由 `required` / `required_when` 负责）；
- 非法正则降级为"不校验"并记 warning（不因配置错误阻塞写入）；
- 多值字段逐项校验。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from cndb.plugins.tables.models import DataField, DataTable

logger = logging.getLogger(__name__)

#: 条件必填支持的操作符（与筛选算子对齐的子集，够用且语义明确）
REQUIRED_WHEN_OPS = ("eq", "neq", "in", "not_in", "is_empty", "is_not_empty")


def _pattern_of(field: DataField) -> tuple[re.Pattern[str] | None, str | None]:
    config = (field.config or {}).get("validation") or {}
    pattern = config.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return None, None
    try:
        return re.compile(pattern), config.get("message")
    except re.error as exc:
        logger.warning("字段 %s 的正则配置无法编译，已降级为不校验: %s", field.name, exc)
        return None, None


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _values_of(value: Any) -> list[Any]:
    """按字段值形态展开为待校验标量列表（多值逐项校验）."""
    if isinstance(value, list):
        return [item for item in value if not _is_blank(item)]
    return [] if _is_blank(value) else [value]


def check_pattern(field: DataField, value: Any) -> None:
    """模式校验；不匹配抛 ValueError（文案优先用配置的 message）."""
    pattern, message = _pattern_of(field)
    if pattern is None:
        return
    for item in _values_of(value):
        text = str(item)
        if pattern.search(text) is None:
            raise ValueError(message or f"字段「{field.name}」格式不符合要求: {text}")


def _condition_matches(condition: dict[str, Any], value: Any) -> bool:
    op = str(condition.get("op") or "eq")
    expected = condition.get("value")
    if op == "is_empty":
        return _is_blank(value)
    if op == "is_not_empty":
        return not _is_blank(value)
    if op in ("in", "not_in"):
        options = [str(v) for v in (expected if isinstance(expected, list) else [expected])]
        hit = str(value) in options
        return hit if op == "in" else not hit
    # eq / neq：字符串比较（与筛选算子口径一致）
    hit = str(value) == str(expected)
    return hit if op == "eq" else not hit


def check_required_when(field: DataField, row_values: dict[str, Any]) -> None:
    """条件必填校验；条件命中且本字段空 → ValueError."""
    condition = (field.config or {}).get("required_when")
    if not isinstance(condition, dict):
        return
    watcher = condition.get("field")
    if not isinstance(watcher, str) or not watcher:
        return
    if not _condition_matches(condition, row_values.get(watcher)):
        return
    if _is_blank(row_values.get(field.name)):
        raise ValueError(f"字段「{field.name}」在「{watcher}」满足条件时必填")


def validate_row_constraints(table: DataTable, row_values: dict[str, Any]) -> None:
    """对一行做字段级规则校验（模式 + 条件必填），冲突即抛 ValueError.

    Args:
        table: 目标表元数据（取 active_fields 的顺序，保证首个错误稳定可预期）。
        row_values: **合并后**的行值（字段名 → 值）；update 路径须传补丁 + 当前值。
    """
    for field in table.active_fields():
        if field.trashed:
            continue
        check_required_when(field, row_values)
        check_pattern(field, row_values.get(field.name))


__all__ = [
    "REQUIRED_WHEN_OPS",
    "check_pattern",
    "check_required_when",
    "validate_row_constraints",
]
