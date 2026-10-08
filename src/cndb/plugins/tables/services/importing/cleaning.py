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

# 值变换纯函数已抽取到 cleaning_core 共享层（导入与已存表清洗共用），此处导入复用
from cndb.plugins.tables.services.cleaning_core import (
    apply_coerce as _apply_coerce,
)
from cndb.plugins.tables.services.cleaning_core import (
    apply_drop_outliers as _apply_drop_outliers,
)
from cndb.plugins.tables.services.cleaning_core import (
    apply_fill_null as _apply_fill_null,
)
from cndb.plugins.tables.services.cleaning_core import (
    apply_trim as _apply_trim,
)

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
            has_whitespace = any(isinstance(v, str) and v != v.strip() for v in sample_values)
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
            fill_profile = _build_fill_profile(cleaned, column, strategy, action, profile)
            cleaned, affected = _apply_fill_null(cleaned, column, strategy, fill_profile)
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


def _build_fill_profile(
    rows: list[dict[str, Any]],
    column: str | None,
    strategy: str | None,
    action: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """为 fill_null 构建统计口径 profile.

    列画像中只有数值样本 >= 4 时才含 mean / distribution_bins，样本不足时缺失，
    直接透传画像会导致填充静默失效。因此：
    - default: 填充值取自动作配置 fill_value（画像中不存在该键）；
    - mean/median: 优先取画像统计值，缺失时回退为对当前行实时计算
      （rows 为内存全量数据，统计口径全局一致）。
    """
    if strategy == "default":
        return {"fill_value": action.get("fill_value")}
    if strategy == "mean":
        if profile.get("mean") is not None:
            return {"mean": profile["mean"]}
        values = _numeric_values(rows, column)
        return {"mean": sum(values) / len(values)} if values else {}
    if strategy == "median":
        if profile.get("median") is not None:
            return {"median": profile["median"]}
        if profile.get("distribution_bins"):
            return {"distribution_bins": profile["distribution_bins"]}
        values = sorted(_numeric_values(rows, column))
        if values:
            n = len(values)
            mid = n // 2
            median = values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2
            return {"median": median}
        return {}
    return {}


def _numeric_values(rows: list[dict[str, Any]], column: str | None) -> list[float]:
    """收集某列的可解析数值（跳过 None / 布尔 / 不可解析值）."""
    if not column:
        return []
    values: list[float] = []
    for r in rows:
        v = r.get(column)
        if v is None or isinstance(v, bool):
            continue
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            continue
    return values


def _apply_dedupe(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """按全部列 hash 去重，保留第一条.

    key 用 repr(v) 而非 str(v)，避免不同类型值（如 int 5 与 str "5"、
    bool True 与 str "True"）被误判为相同而静默丢弃。
    """
    seen: set[tuple[Any, ...]] = set()
    kept: list[dict[str, Any]] = []
    for r in rows:
        key = tuple(sorted((k, repr(v)) for k, v in r.items()))
        if key in seen:
            continue
        seen.add(key)
        kept.append(r)
    dup_removed = len(rows) - len(kept)
    return kept, dup_removed


__all__ = ["apply_cleaning_actions", "generate_cleaning_suggestions"]
