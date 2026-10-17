"""求值与统计：按公式计算派生列 + 描述统计.

取数口径：
- 走 tables 插件的 ``list_rows``（复用行级权限 / 字段隐藏 / 软删除过滤），
  一次扫描最多 ``MAX_SCAN_ROWS`` 行；
- 描述统计基于**全部扫描到的行**，返回的行数据受请求 ``limit`` 限制。
"""

from __future__ import annotations

from statistics import fmean, stdev
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.analytics.services.formula import _to_number, evaluate_column
from cndb.plugins.tables.models import DataTable

# 单次扫描行数上限（保护内存；超出时响应 truncated=True）
MAX_SCAN_ROWS = 20000


def _quantile(sorted_values: list[float], p: float) -> float | None:
    """线性插值分位数（R-7，与前端 simple-statistics 口径一致）."""
    n = len(sorted_values)
    if n == 0:
        return None
    if n == 1:
        return sorted_values[0]
    idx = p * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _stat_block(key: str, label: str, kind: str, values: list[float | None]) -> dict[str, Any]:
    """一列的描述统计（空 / 非数值剔除后计算）."""
    nums = [float(v) for v in values if v is not None]
    stat: dict[str, Any] = {
        "key": key,
        "label": label or key,
        "kind": kind,
        "count": len(nums),
        "missing": len(values) - len(nums),
    }
    if not nums:
        return stat
    ordered = sorted(nums)
    stat.update(
        {
            "mean": fmean(nums),
            "stdev": stdev(nums) if len(nums) >= 2 else None,
            "min": ordered[0],
            "q1": _quantile(ordered, 0.25),
            "median": _quantile(ordered, 0.5),
            "q3": _quantile(ordered, 0.75),
            "max": ordered[-1],
            "sum": sum(nums),
        }
    )
    return stat


def _allowed_field_names(table: DataTable, rows: list[dict[str, Any]]) -> list[str]:
    """该表可见字段（按字段顺序；实际以扫描到的行键为准，避免隐藏字段被引用）."""
    seen: set[str] = set()
    for row in rows:
        seen.update(row.keys())
    seen.discard("id")
    return [f.name for f in table.active_fields() if f.name in seen]


def scan_rows(
    db: Session,
    table: DataTable,
    user: Any,
) -> tuple[list[dict[str, Any]], int, bool]:
    """扫描表数据（含行级权限 / 字段隐藏），返回 (rows, total, truncated)."""
    from cndb.plugins.tables.services.core.records import list_rows

    rows, total = list_rows(
        db.get_bind(),
        table,
        limit=MAX_SCAN_ROWS,
        offset=0,
        include_trashed=False,
        db=db,
        user=user,
    )
    truncated = int(total or 0) > len(rows)
    return rows, int(total or 0), truncated


def compute(
    db: Session,
    table: DataTable,
    user: Any,
    *,
    formulas: list[dict[str, str]],
    fields: list[str] | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    """按公式计算派生列并返回行数据 + 描述统计.

    Args:
        formulas: [{"key","label","expr"}]，expr 已通过校验（此处仍会解析，非法即抛 FormulaError）.
        fields: 需要返回的原始字段；空 = 全部可见字段.
        limit: 返回行数上限（统计仍基于全量扫描）.
    """
    rows, total, truncated = scan_rows(db, table, user)
    field_names = _allowed_field_names(table, rows)

    wanted = [f for f in (fields or []) if f in field_names] or field_names

    computed: dict[str, list[float | None]] = {}
    for spec in formulas:
        computed[spec["key"]] = evaluate_column(spec["expr"], rows, field_names)

    out_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(rows[:limit]):
        item: dict[str, Any] = {"id": row.get("id")}
        for fname in wanted:
            item[fname] = row.get(fname)
        for spec in formulas:
            item[spec["key"]] = computed[spec["key"]][idx]
        out_rows.append(item)

    columns: list[dict[str, Any]] = []
    for fname in field_names:
        nums = [_to_number(row.get(fname)) for row in rows]
        # 仅当该列存在可数值化的值时纳入统计
        if any(v is not None for v in nums):
            columns.append(_stat_block(fname, fname, "field", nums))
    for spec in formulas:
        columns.append(_stat_block(spec["key"], spec.get("label", ""), "formula", computed[spec["key"]]))

    return {
        "rows": out_rows,
        "total": total,
        "truncated": truncated,
        "table_fields": field_names,
        "columns": columns,
    }


__all__ = ["MAX_SCAN_ROWS", "compute", "scan_rows"]
