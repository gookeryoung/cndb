"""列级数据质量画像 —— 为导入 analyze 阶段补充 per-column 统计.

职责：接收解析后的 ``rows`` + ``file_columns``，按列计算数据质量画像
（空值率、唯一值数、类型推断与 confidence、混合类型冲突、异常值、数值列
分布直方图、离散列 Top N），以及整体 summary（重复行预估、空列、高空值列）。

为避免大文件 O(n) 扫描，所有统计均在前 ``sample_limit`` 行上进行，
不追求全量精确，只需足够好的启发式信号。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from cndb.plugins.tables.transfer import (
    _classify_date_like,
    _infer_single_value,
    _pick_inferred_type,
    promote_inferred_column_type,
)

# 只在 sample_limit 行上做统计，避免大文件 O(n) 扫描
DEFAULT_SAMPLE_LIMIT = 10000

# type_conflicts 最多记录多少条冲突样本
MAX_CONFLICT_SAMPLES = 10

# 异常值（outliers）最多记录多少条
MAX_OUTLIER_SAMPLES = 10

# 数值分布直方图段数
HISTOGRAM_BINS = 10

# 离散列 value_counts 最多返回
TOP_VALUE_COUNTS = 10

# confidence 阈值：低于此值认为类型推断"不够有把握"
CONFIDENCE_WARN_THRESHOLD = 0.8


def _try_float(v: Any) -> float | None:
    """尝试把值转成 float，失败返回 None."""
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    # 去掉千分位逗号和货币符号
    s = s.replace(",", "").replace("¥", "").replace("$", "").replace("￥", "")
    try:
        return float(s)
    except ValueError:
        return None


def _iqr_outliers(values: list[float]) -> list[float]:
    """用 IQR 法检测异常值：超出 [Q1-1.5*IQR, Q3+1.5*IQR] 的值."""
    if len(values) < 4:
        return []
    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def _q(p: float) -> float:
        # 线性插值分位数
        pos = (n - 1) * p
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

    q1 = _q(0.25)
    q3 = _q(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return []
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return [v for v in sorted_vals if v < lower or v > upper]


def _rare_text_values(texts: list[str], threshold_ratio: float = 0.02) -> list[str]:
    """文本列异常值：出现频次 < 阈值占比 的值."""
    if not texts:
        return []
    counter = Counter(texts)
    total = len(texts)
    threshold_count = max(1, int(total * threshold_ratio))
    rare = [v for v, c in counter.items() if c <= threshold_count]
    # 按出现次数升序
    rare.sort(key=lambda v: counter[v])  # type: ignore[implicit-any-lambda]
    return rare[:MAX_OUTLIER_SAMPLES]


def _build_histogram(values: list[float]) -> list[dict[str, Any]]:
    """把数值列表转为 10 段直方图 [{bin_label, count, low, high}]."""
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if lo == hi:
        return [{"bin_label": f"{lo}", "count": len(values), "low": lo, "high": hi}]
    bin_width = (hi - lo) / HISTOGRAM_BINS
    bins: list[dict[str, Any]] = []
    counts = [0] * HISTOGRAM_BINS
    for v in values:
        idx = min(int((v - lo) / bin_width), HISTOGRAM_BINS - 1)
        counts[idx] += 1
    for i, cnt in enumerate(counts):
        bl = lo + i * bin_width
        bh = lo + (i + 1) * bin_width if i < HISTOGRAM_BINS - 1 else hi
        label = f"{bl:.2f}–{bh:.2f}"
        bins.append({"bin_label": label, "count": cnt, "low": round(bl, 4), "high": round(bh, 4)})
    return bins


def profile_columns(
    rows: list[dict[str, Any]],
    file_columns: list[str],
    *,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """对传入行按列生成数据质量画像.

    Args:
        rows: 已解析的行列表
        file_columns: 文件原始列名顺序
        sample_limit: 最多扫描多少行做统计

    Returns:
        (column_profiles, data_quality_summary)
    """
    if not file_columns:
        return [], {"total_rows": len(rows), "total_columns": 0}

    sample_rows = rows[:sample_limit]
    total_rows = len(rows)

    column_profiles: list[dict[str, Any]] = []
    empty_columns: list[str] = []
    high_null_columns: list[str] = []

    for col in file_columns:
        profile = _profile_single_column(sample_rows, col, total_rows)
        column_profiles.append(profile)
        if profile["null_ratio"] >= 1.0:
            empty_columns.append(col)
        elif profile["null_ratio"] > 0.5:
            high_null_columns.append(col)

    # 重复行预估（只在前 min(5, ncols) 列做 hash，避免大集合）
    dup_rows = _estimate_duplicate_rows(sample_rows, file_columns)

    summary = {
        "total_rows": total_rows,
        "total_columns": len(file_columns),
        "duplicate_rows": dup_rows,
        "empty_columns": empty_columns,
        "high_null_columns": high_null_columns,
    }

    return column_profiles, summary


def _profile_single_column(
    rows: list[dict[str, Any]],
    col: str,
    total_rows: int,
) -> dict[str, Any]:
    """单列画像."""
    null_count = 0
    non_null_values: list[Any] = []
    type_counts: dict[str, int] = {}
    conflicts: list[dict[str, Any]] = []
    numeric_values: list[float] = []
    text_values: list[str] = []

    for _i, row in enumerate(rows):
        raw = row.get(col)
        if raw is None:
            null_count += 1
            continue
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                null_count += 1
                continue
            non_null_values.append(s)
            t = _infer_single_value(s)
            if t == "empty":
                null_count += 1
                non_null_values.pop()
                continue
            type_counts[t] = type_counts.get(t, 0) + 1
            # 混合类型记录
            if t not in ("text", "number", "float", "boolean"):
                text_values.append(s)
            else:
                # number/float 可能也需要进 numeric
                f = _try_float(s)
                if f is not None:
                    numeric_values.append(f)
                else:
                    text_values.append(s)
        elif isinstance(raw, bool):
            non_null_values.append(raw)
            type_counts["boolean"] = type_counts.get("boolean", 0) + 1
        elif isinstance(raw, (int, float)):
            non_null_values.append(raw)
            t = "number" if isinstance(raw, int) else "float"
            type_counts[t] = type_counts.get(t, 0) + 1
            numeric_values.append(float(raw))
        elif isinstance(raw, (list, dict)):
            non_null_values.append(raw)
            type_counts["json"] = type_counts.get("json", 0) + 1
        else:
            non_null_values.append(raw)
            # date/datetime 对象（xlsx 日期单元格）按推断层同款规则分类，
            # 否则落 text 后会被低基数启发式误提升为 select
            t = _classify_date_like(raw) or "text"
            type_counts[t] = type_counts.get(t, 0) + 1

    non_null_count = total_rows - null_count
    null_ratio = round(null_count / total_rows, 4) if total_rows > 0 else 0.0

    # 类型推断 + confidence
    inferred = _pick_inferred_type(type_counts) if type_counts else "text"
    # 完整提升链统一收口：timestamp → longtext → multiselect → select（与 analyze_csv_columns 一致）
    inferred, promote_opts = promote_inferred_column_type(inferred, [str(v) for v in non_null_values])
    max_type_count = max(type_counts.values()) if type_counts else 0
    confidence = round(max_type_count / non_null_count, 3) if non_null_count > 0 else 1.0
    fallback_type = "text" if confidence < CONFIDENCE_WARN_THRESHOLD and inferred != "text" else None

    # type_conflicts: 最常见类型 vs 其他类型的行号样本
    if confidence < 1.0:
        dominant_type = inferred
        for t, _cnt in type_counts.items():
            if t in (dominant_type, "empty"):
                continue
            # 从 rows 里找属于该 t 的样本行（最多 MAX_CONFLICT_SAMPLES）
            found = 0
            for _i, row in enumerate(rows):
                raw = row.get(col)
                if raw is None or (isinstance(raw, str) and not raw.strip()):
                    continue
                actual_t = (
                    _infer_single_value(raw.strip())
                    if isinstance(raw, str)
                    else (
                        "boolean"
                        if isinstance(raw, bool)
                        else "number"
                        if isinstance(raw, int)
                        else "float"
                        if isinstance(raw, float)
                        else "json"
                        if isinstance(raw, (list, dict))
                        else _classify_date_like(raw) or "text"
                    )
                )
                if actual_t == t and found < MAX_CONFLICT_SAMPLES:
                    conflicts.append(
                        {
                            "row_number": _i + 1,  # 1-based
                            "value": str(raw)[:80],
                            "conflicting_type": t,
                        }
                    )
                    found += 1
            if len(conflicts) >= MAX_CONFLICT_SAMPLES:
                break

    # unique_count + sample_values
    seen_unique: set[Any] = set()
    unique_count = 0
    sample_values: list[str] = []
    for v in non_null_values:
        key = v if not isinstance(v, (list, dict)) else str(v)
        if key not in seen_unique:
            seen_unique.add(key)
            unique_count += 1
        if len(sample_values) < 5:
            sv = str(v) if not isinstance(v, str) else v
            sample_values.append(sv[:80])

    # outliers + distribution（仅数值列） / value_counts（离散列）
    outliers: list[dict[str, Any]] = []
    distribution_bins: list[dict[str, Any]] = []
    value_counts: list[dict[str, Any]] = []
    numeric_stats: dict[str, Any] | None = None

    _NUMERIC_TYPES = {"number", "float", "percentage"}
    _DISCRETE_TYPES = {"select", "boolean"}

    if inferred in _NUMERIC_TYPES and len(numeric_values) >= 4:
        nums = sorted(numeric_values)
        mean_v = sum(nums) / len(nums)
        variance = sum((x - mean_v) ** 2 for x in nums) / len(nums)
        std_v = variance**0.5
        numeric_stats = {
            "min": round(nums[0], 6),
            "max": round(nums[-1], 6),
            "mean": round(mean_v, 6),
            "std": round(std_v, 6),
        }
        distribution_bins = _build_histogram(nums)
        outlier_vals = _iqr_outliers(nums)
        for v in outlier_vals[:MAX_OUTLIER_SAMPLES]:
            outliers.append({"value": round(v, 6), "type": "numeric", "row_number": None})

    elif inferred in _DISCRETE_TYPES or (inferred == "text" and unique_count > 0 and unique_count <= 20):
        # 离散列或低基数文本列 → value_counts
        counter: Counter[str] = Counter()
        for v in non_null_values:
            counter[str(v)] += 1
        for val, cnt in counter.most_common(TOP_VALUE_COUNTS):
            value_counts.append({"value": val[:80], "count": cnt})
        # 稀有值作 outliers
        rare = _rare_text_values([str(v) for v in non_null_values])
        for v in rare[:MAX_OUTLIER_SAMPLES]:
            outliers.append({"value": v[:80], "type": "text"})

    # 组装 profile
    profile: dict[str, Any] = {
        "name": col,
        "inferred_type": inferred,
        "confidence": confidence,
        "fallback_type": fallback_type,
        "null_count": null_count,
        "null_ratio": null_ratio,
        "unique_count": unique_count,
        "sample_values": sample_values,
        "type_conflicts": conflicts,
        "outliers": outliers,
    }
    if promote_opts:
        # 键名沿用 select_options（历史兼容）：现承载 select/multiselect 提升命中的 options
        profile["select_options"] = promote_opts
    if numeric_stats:
        profile.update(numeric_stats)  # min/max/mean/std
        profile["distribution_bins"] = distribution_bins
    if value_counts:
        profile["value_counts"] = value_counts

    return profile


def _estimate_duplicate_rows(
    rows: list[dict[str, Any]],
    file_columns: list[str],
) -> int:
    """按前 min(5, ncols) 列做 hash 预估重复行数量."""
    if len(rows) < 2 or not file_columns:
        return 0
    key_cols = file_columns[: min(5, len(file_columns))]
    seen: set[tuple[Any, ...]] = set()
    dup_count = 0
    for row in rows:
        # 把不可 hash 的值（list/dict）序列化为 str
        key: list[Any] = []
        for c in key_cols:
            v = row.get(c) or ""
            if isinstance(v, (list, dict)):
                key.append(str(v))
            else:
                key.append(v)
        key_tup = tuple(key)
        if key_tup in seen:
            dup_count += 1
        else:
            seen.add(key_tup)
    return dup_count


__all__ = ["profile_columns"]
