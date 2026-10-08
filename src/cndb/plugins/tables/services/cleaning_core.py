"""清洗值变换纯函数 —— 导入流水线与已存表清洗共用的共享层.

只做行内值变换（trim / fill_null / coerce / drop_outliers），不触碰数据库；
统计口径（均值 / 中位数 / IQR 阈值）由调用方计算后通过 profile dict 注入：
- apply_fill_null: {"mean", "median", "fill_value"}（按 strategy 取用）
- apply_drop_outliers: {"outliers": [{"value", "type"}]}
"""

from __future__ import annotations

from typing import Any


def apply_fill_null(
    rows: list[dict[str, Any]],
    column: str,
    strategy: str | None,
    profile: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """填补空值.

    strategy: mean/median（数值列，统计值来自 profile）、
        default（填充值来自 profile.fill_value）、empty（不填）
    """
    if strategy == "empty":
        return rows, 0
    fill_value: Any = None
    if strategy == "mean":
        fill_value = profile.get("mean")
    elif strategy == "median":
        if "median" in profile:
            fill_value = profile["median"]
        else:
            # 用 profile 里没有 median 时从 distribution_bins 粗略估
            bins = profile.get("distribution_bins", [])
            if bins:
                total = sum(b["count"] for b in bins)
                target = total / 2
                cum = 0
                for b in bins:
                    cum += b["count"]
                    if cum >= target:
                        fill_value = (b["low"] + b["high"]) / 2
                        break
    elif strategy == "default":
        fill_value = profile.get("fill_value")

    if fill_value is None:
        return rows, 0

    affected = 0
    for r in rows:
        if r.get(column) is None or (isinstance(r.get(column), str) and r[column].strip() == ""):
            r[column] = fill_value
            affected += 1
    return rows, affected


def apply_trim(rows: list[dict[str, Any]], column: str) -> tuple[list[dict[str, Any]], int]:
    """对字符串列做 strip."""
    affected = 0
    for r in rows:
        v = r.get(column)
        if isinstance(v, str):
            stripped = v.strip()
            if stripped != v:
                r[column] = stripped
                affected += 1
    return rows, affected


def apply_coerce(
    rows: list[dict[str, Any]],
    column: str,
    target_type: str | None,
    on_fail: str,
) -> tuple[list[dict[str, Any]], int]:
    """强制把列值转为目标类型，失败时按 on_fail 处理（nullify / reject）."""
    if not target_type:
        return rows, 0

    def _coerce_value(v: Any, t: str) -> tuple[Any, bool]:
        """返回 (新值, 是否成功)."""
        if v is None:
            return None, True
        if t in ("number", "float", "percentage"):
            try:
                from cndb.plugins.tables.services.transfer import _normalize_numeric

                norm = _normalize_numeric(str(v))
                if norm is None:
                    return None, False
                num = float(norm)
                return int(num) if t == "number" and num.is_integer() else num, True
            except (ValueError, TypeError):
                return None, False
        if t == "boolean":
            low = str(v).strip().lower()
            if low in ("true", "yes", "是", "1", "on"):
                return True, True
            if low in ("false", "no", "否", "0", "off"):
                return False, True
            return None, False
        if t in ("date", "datetime"):
            # 只验证能被解析，归一化交给 RowValidator
            from cndb.plugins.tables.services.transfer import (
                _CN_DATE_RE,
                _GENERIC_DATE_RE,
                _ISO_DATE_RE,
                _ISO_DATETIME_RE,
            )

            s = str(v).strip()
            if any(r.match(s) for r in (_ISO_DATE_RE, _ISO_DATETIME_RE, _CN_DATE_RE, _GENERIC_DATE_RE)):
                return s, True
            return None, False
        # text / json / 其他：直接转为字符串
        return str(v), True

    affected = 0
    rejected_rows = set()
    for idx, r in enumerate(rows):
        v = r.get(column)
        new_v, ok = _coerce_value(v, target_type)
        if not ok:
            if on_fail == "reject":
                rejected_rows.add(idx)
            else:
                r[column] = None
                affected += 1
        elif new_v != v:
            r[column] = new_v
            affected += 1

    if rejected_rows:
        rows = [r for i, r in enumerate(rows) if i not in rejected_rows]
    return rows, affected


def apply_drop_outliers(
    rows: list[dict[str, Any]],
    column: str,
    profile: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """把数值列的异常值置空（异常值列表从 profile 读取）."""
    outliers = profile.get("outliers", [])
    if not outliers:
        return rows, 0
    # 从 outliers 取异常值列表，置空行中的对应值
    outlier_values = {o["value"] for o in outliers if o.get("type") == "numeric"}
    affected = 0
    for r in rows:
        v = r.get(column)
        try:
            if v is not None and float(v) in outlier_values:
                r[column] = None
                affected += 1
        except (ValueError, TypeError):
            continue
    return rows, affected


__all__ = [
    "apply_coerce",
    "apply_drop_outliers",
    "apply_fill_null",
    "apply_trim",
]
