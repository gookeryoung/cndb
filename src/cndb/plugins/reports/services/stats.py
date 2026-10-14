"""模板内可直接调用的统计函数（注册到 Jinja 沙箱 globals）。

输入 records 是 list[dict]、field 是字段名，返回纯数据结构（dict / list[dict]），
方便 Jinja2 用 .sum/.count 之类的属性访问。"""

from __future__ import annotations

from typing import Any

# ── 统计函数 ──────────────────────────────────
# 这两个函数在 SandboxedEnvironment.globals 注册，模板内可直接调用。
# 输入 records 是 list[dict]，field 是字段名。返回的都是纯数据结构（dict / list[dict]），
# 方便 Jinja2 用 .sum/.count 之类的属性访问。


def _coerce_numeric(value: Any) -> float | None:
    """把字段值强转为数字；None / 非数字 / 空串返回 None."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stats(records: list[dict[str, Any]], field: str) -> dict[str, Any]:
    """对 records 的 field 列做聚合，返回 {count, sum, avg, min, max, non_empty}.

    count/sum/avg/min/max 只统计可解析为数值的行；
    non_empty 统计原始值非空（非 None 且非空串）的行数，可用于文本字段计数。
    """
    raw_values = [r.get(field) for r in records]
    nums = [v for v in (_coerce_numeric(x) for x in raw_values) if v is not None]
    non_empty = sum(1 for v in raw_values if v is not None and v != "")
    if not nums:
        return {"count": 0, "sum": 0, "avg": 0, "min": None, "max": None, "non_empty": non_empty}
    total = sum(nums)
    return {
        "count": len(nums),
        "sum": total,
        "avg": total / len(nums),
        "min": min(nums),
        "max": max(nums),
        "non_empty": non_empty,
    }


def _group_stats(
    records: list[dict[str, Any]],
    key_field: str,
    value_field: str,
) -> list[dict[str, Any]]:
    """按 key_field 分组，对 value_field 做聚合，返回 list[dict with key + stats]."""
    groups: dict[Any, list[Any]] = {}
    for r in records:
        k = r.get(key_field)
        if k not in groups:
            groups[k] = []
        groups[k].append(r.get(value_field))
    result: list[dict[str, Any]] = []
    for key, vals in groups.items():
        nums = [v for v in (_coerce_numeric(v) for v in vals) if v is not None]
        if nums:
            total = sum(nums)
            result.append(
                {
                    "key": key,
                    "count": len(nums),
                    "sum": total,
                    "avg": total / len(nums),
                    "min": min(nums),
                    "max": max(nums),
                }
            )
        else:
            result.append({"key": key, "count": 0, "sum": 0, "avg": 0, "min": None, "max": None})
    return result
