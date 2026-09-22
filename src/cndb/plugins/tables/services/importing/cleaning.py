"""清洗建议生成 —— 从列级画像 + 数据质量 summary 推导可操作的清洗建议.

每条建议结构：
{
    "id": 唯一标识（column + action）,
    "column": 目标列（全局 action 时为 None）,
    "action": trim_whitespace / fill_null / coerce_type / drop_outliers
             / ignore_column / dedupe_rows,
    "strategy": 可选子策略（fill_null: mean/median/default; coerce_type: target 类型）,
    "affected_count": 预估受影响行数,
    "reason": 简短理由,
    "preview_before": 清洗前样例（3 条）,
    "preview_after": 清洗后预期样例（3 条）,
}

本模块只生成 stateless 建议，不做实际数据修改；
实际清洗在 :mod:`cndb.plugins.tables.services.importing.importer` 的 execute 阶段执行.
"""

from __future__ import annotations

from typing import Any

# 数值类型列表（fill_null 可用 mean/median）
_NUMERIC_TYPES = {"number", "float", "percentage"}


def generate_cleaning_suggestions(
    column_profiles: list[dict[str, Any]],
    data_quality_summary: dict[str, Any],
    _validation_report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """根据 analyze 输出的三份数据生成清洗建议.

    Args:
        column_profiles: 列级画像（来自 column_profiler.profile_columns）
        data_quality_summary: 整体 summary
        validation_report: DiffReporter.build 返回的主报告（可选，用于参考 errors 列表）

    Returns:
        清洗建议列表，按"建议性"从高到低排序
    """
    suggestions: list[dict[str, Any]] = []

    # ── 全局建议 ────────────────────────────────
    dup_count = data_quality_summary.get("duplicate_rows", 0)
    if dup_count > 0:
        suggestions.append(
            {
                "id": "global_dedupe",
                "column": None,
                "action": "dedupe_rows",
                "strategy": "keep_first",
                "affected_count": dup_count,
                "reason": f"检测到 {dup_count} 行疑似重复（按前 5 列 hash），可保留第一条其余删除",
                "preview_before": ["(重复行预览略)"],
                "preview_after": [],
            }
        )

    # ── 逐列建议 ────────────────────────────────
    for profile in column_profiles:
        name = profile["name"]
        inferred = profile.get("inferred_type", "text")
        confidence = profile.get("confidence", 1.0)
        null_ratio = profile.get("null_ratio", 0.0)
        null_count = profile.get("null_count", 0)
        outliers = profile.get("outliers", [])
        conflicts = profile.get("type_conflicts", [])
        sample_values = profile.get("sample_values", [])

        # 1) 高空值率 → fill_null 或 ignore_column
        if 0.2 < null_ratio < 0.95:
            strategy = "mean" if inferred in _NUMERIC_TYPES else "empty"
            suggestions.append(
                {
                    "id": f"{name}_fill_null",
                    "column": name,
                    "action": "fill_null",
                    "strategy": strategy,
                    "affected_count": null_count,
                    "reason": f"空值率 {null_ratio:.1%}，建议用 {'均值' if inferred in _NUMERIC_TYPES else '空值'} 填充",
                    "preview_before": sample_values[:3],
                    "preview_after": sample_values[:3],
                }
            )

        if null_ratio >= 0.95:
            suggestions.append(
                {
                    "id": f"{name}_ignore",
                    "column": name,
                    "action": "ignore_column",
                    "strategy": "skip",
                    "affected_count": profile.get("unique_count", 0),
                    "reason": f"空值率 {null_ratio:.1%} 几乎全空，建议忽略此列",
                    "preview_before": [],
                    "preview_after": [],
                }
            )

        # 2) 类型推断置信度低 + 存在 type_conflicts → coerce_type
        if confidence < 0.8 and conflicts:
            suggestions.append(
                {
                    "id": f"{name}_coerce",
                    "column": name,
                    "action": "coerce_type",
                    "strategy": inferred,
                    "on_fail": "nullify",
                    "affected_count": len(conflicts),
                    "reason": f"类型推断置信度 {confidence:.0%}，有 {len(conflicts)} 行与主流类型不匹配，建议强制转为 {inferred}（失败行置空）",
                    "preview_before": [c.get("value", "") for c in conflicts[:3]],
                    "preview_after": [f"(转换为 {inferred})"] * min(3, len(conflicts)),
                }
            )

        # 3) 数值列有异常值 → drop_outliers
        if outliers and inferred in _NUMERIC_TYPES:
            suggestions.append(
                {
                    "id": f"{name}_drop_outliers",
                    "column": name,
                    "action": "drop_outliers",
                    "strategy": "iqr",
                    "affected_count": len(outliers),
                    "reason": f"数值列存在 {len(outliers)} 个异常值（IQR 法检测），建议剔除或置空",
                    "preview_before": [str(o.get("value", "")) for o in outliers[:3]],
                    "preview_after": ["(删除或置空)"] * min(3, len(outliers)),
                }
            )

        # 4) 文本列有明显前后空格 → trim_whitespace
        if inferred == "text" and sample_values:
            has_whitespace = any(isinstance(v, str) and (v != v.strip() or v != v.strip()) for v in sample_values)
            if has_whitespace:
                suggestions.append(
                    {
                        "id": f"{name}_trim",
                        "column": name,
                        "action": "trim_whitespace",
                        "strategy": "both",
                        "affected_count": -1,  # -1 表示全列
                        "reason": "样本值含前后空格，建议统一 trim",
                        "preview_before": sample_values[:3],
                        "preview_after": [v.strip() for v in sample_values[:3]],
                    }
                )

    # 按"破坏性"排序：全局在前、ignore 在最前（风险最大）、trim 最保守
    _PRIORITY = {
        "ignore_column": 0,
        "dedupe_rows": 1,
        "drop_outliers": 2,
        "coerce_type": 3,
        "fill_null": 4,
        "trim_whitespace": 5,
    }
    suggestions.sort(key=lambda s: _PRIORITY.get(s["action"], 99))  # type: ignore[implicit-any-lambda]

    return suggestions


def apply_cleaning_actions(
    rows: list[dict[str, Any]],
    column_profiles: list[dict[str, Any]],
    cleaning_actions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """在解析后的原始 rows 上应用清洗动作.

    Args:
        rows: 原始行列表
        column_profiles: 列级画像（供 IQR 阈值 / 均值等计算参考）
        cleaning_actions: 用户选定的清洗动作列表（来自前端）

    Returns:
        (cleaned_rows, applied_records)
        applied_records 记录每条 action 实际处理了多少行
    """
    if not cleaning_actions:
        return rows, []

    cleaned = [dict(r) for r in rows]  # 浅拷贝，避免修改原对象
    applied: list[dict[str, Any]] = []
    profiles_by_col = {p["name"]: p for p in column_profiles}

    for action in cleaning_actions:
        act_type = action.get("action")
        column = action.get("column")
        strategy = action.get("strategy")
        on_fail = action.get("on_fail", "nullify")
        affected = 0

        if act_type == "dedupe_rows":
            cleaned, affected = _apply_dedupe(cleaned)
            applied.append({"action": act_type, "column": None, "affected_rows": affected})
            continue

        if act_type == "ignore_column" and column:
            cleaned = [{k: v for k, v in r.items() if k != column} for r in cleaned]
            applied.append({"action": act_type, "column": column, "affected_rows": len(cleaned)})
            continue

        if column is None:
            continue
        profile = profiles_by_col.get(column, {})

        if act_type == "fill_null":
            cleaned, affected = _apply_fill_null(cleaned, column, strategy, profile)
        elif act_type == "trim_whitespace":
            cleaned, affected = _apply_trim(cleaned, column)
        elif act_type == "coerce_type":
            cleaned, affected = _apply_coerce(cleaned, column, strategy, on_fail)
        elif act_type == "drop_outliers":
            cleaned, affected = _apply_drop_outliers(cleaned, column, profile)
        else:
            continue

        applied.append({"action": act_type, "column": column, "strategy": strategy, "affected_rows": affected})

    return cleaned, applied


# ── 各清洗策略的具体实现 ──────────────────────────


def _apply_dedupe(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """按全部列 hash 去重，保留第一条."""
    seen: set[tuple[Any, ...]] = set()
    kept: list[dict[str, Any]] = []
    for r in rows:
        key = tuple(sorted((k, str(v) if v is not None else "") for k, v in r.items()))
        if key in seen:
            continue
        seen.add(key)
        kept.append(r)
    dup_removed = len(rows) - len(kept)
    return kept, dup_removed


def _apply_fill_null(
    rows: list[dict[str, Any]],
    column: str,
    strategy: str | None,
    profile: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """填补空值.

    strategy: mean/median（数值列）、default（用户指定 fill_value）、empty（不填）
    """
    if strategy == "empty":
        return rows, 0
    fill_value: Any = None
    if strategy == "mean":
        fill_value = profile.get("mean")
    elif strategy == "median":
        # 用 profile 里没有 median，这里从 distribution_bins 粗略估
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

    if fill_value is None:
        return rows, 0

    affected = 0
    for r in rows:
        if r.get(column) is None or (isinstance(r.get(column), str) and r[column].strip() == ""):
            r[column] = fill_value
            affected += 1
    return rows, affected


def _apply_trim(rows: list[dict[str, Any]], column: str) -> tuple[list[dict[str, Any]], int]:
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


def _apply_coerce(
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
                from cndb.plugins.tables.transfer import _normalize_numeric

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
            from cndb.plugins.tables.transfer import (
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


def _apply_drop_outliers(
    rows: list[dict[str, Any]],
    column: str,
    profile: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """把数值列的异常值置空（IQR 阈值从 profile 计算）."""
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


__all__ = ["apply_cleaning_actions", "generate_cleaning_suggestions"]
