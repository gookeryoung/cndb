"""求值与统计：按公式计算派生列 + 描述统计 + 可选分组汇总.

取数口径：
- 走 tables 插件的 ``list_rows``（复用行级权限 / 字段隐藏 / 软删除过滤），
  一次扫描最多 ``MAX_SCAN_ROWS`` 行；
- 描述统计与分组汇总基于**全部扫描到的行**，返回的行数据受请求 ``limit`` /
  ``top_n`` 限制。
"""

from __future__ import annotations

from statistics import fmean, stdev, variance
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.analytics.services.formula import FormulaError, _to_number, evaluate_column
from cndb.plugins.tables.models import DataTable

# 单次扫描行数上限（保护内存；超出时响应 truncated=True）
MAX_SCAN_ROWS = 20000

# 聚合方式 → 中文标签（前端列标题与统计标签共用口径）
AGG_LABELS: dict[str, str] = {
    "sum": "求和",
    "avg": "平均",
    "count": "计数",
    "min": "最小",
    "max": "最大",
}
AGG_ORDER: tuple[str, ...] = tuple(AGG_LABELS)

# 分组值缺失时的统一展示标签
EMPTY_GROUP_LABEL = "（空）"
# 不分组时唯一分组的展示标签
TOTAL_GROUP_LABEL = "全部"


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
            "variance": variance(nums) if len(nums) >= 2 else None,
            "min": ordered[0],
            "max": ordered[-1],
            "range": ordered[-1] - ordered[0],
            "q1": _quantile(ordered, 0.25),
            "median": _quantile(ordered, 0.5),
            "q3": _quantile(ordered, 0.75),
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


def _check_filter_fields(table: DataTable, filters: Any) -> None:
    """过滤字段必须存在.

    列表接口对未知字段只记 warning 后跳过；在分析场景里这等于「静默退化成全表扫描」，
    正好把 filters 想解决的 ``MAX_SCAN_ROWS`` 截断又带回来，所以这里直接报错。
    """
    if not filters:
        return
    known = {field.name for field in table.active_fields()}
    for item in filters:
        name = str((item or {}).get("field_name") or "").strip()
        if not name:
            raise FormulaError("过滤条件缺少 field_name")
        if name not in known:
            raise FormulaError(f"过滤字段不存在: {name}")


def scan_limit() -> int:
    """单次扫描行数上限（``settings.ANALYTICS_MAX_SCAN_ROWS``，非法值回退常量）."""
    from cndb.core.config import settings

    try:
        value = int(settings.ANALYTICS_MAX_SCAN_ROWS)
    except (TypeError, ValueError):  # pragma: no cover - 配置层已保证是 int
        return MAX_SCAN_ROWS
    return value if value > 0 else MAX_SCAN_ROWS


def scan_rows(
    db: Session,
    table: DataTable,
    user: Any,
    *,
    filters: list[dict[str, Any]] | None = None,
    filter_logic: str = "AND",
) -> tuple[list[dict[str, Any]], int, bool]:
    """扫描表数据（含行级权限 / 字段隐藏），返回 (rows, total, truncated).

    Args:
        filters: 表过滤条件（与 ``GET /tables/{id}/rows`` 同语法：``{field_name, op, value}``）。
            时序表用「时间区间 + 标的等值」把扫描面压到区间内，是对付
            ``MAX_SCAN_ROWS`` 的首选手段（这也是 ADR 0006 D7 的口径）。
        filter_logic: ``AND`` / ``OR``，多条件组合方式。
    """
    from cndb.plugins.tables.services.core.records import list_rows

    rows, total = list_rows(
        db.get_bind(),
        table,
        filters=filters or None,
        filter_logic=filter_logic,
        limit=scan_limit(),
        offset=0,
        include_trashed=False,
        db=db,
        user=user,
    )
    truncated = int(total or 0) > len(rows)
    return rows, int(total or 0), truncated


# ── 分组汇总 ──────────────────────────────────────────


def metric_key(agg: str, field: str) -> str:
    """分组汇总指标列的唯一键（前后端 / 模板校验共用同一口径）."""
    return f"{agg}({field})"


def metric_label(agg: str, field: str, label: str = "") -> str:
    """指标列展示名：优先自定义 label，否则「聚合方式(来源)」."""
    return label or f"{AGG_LABELS.get(agg, agg)}({field})"


def _is_blank(value: Any) -> bool:
    """分组 / 计数用的空值判定：None 与纯空白字符串视为空."""
    return value is None or (isinstance(value, str) and not value.strip())


def _aggregate(values: list[Any], agg: str) -> float | None:
    """对一组原始值做聚合：count 计非空值个数，其余按数值口径（非数值剔除）."""
    if agg == "count":
        return float(sum(1 for value in values if not _is_blank(value)))
    nums: list[float] = []
    for value in values:
        number = _to_number(value)
        if number is not None:
            nums.append(number)
    if not nums:
        return None
    if agg == "sum":
        return sum(nums)
    if agg == "avg":
        return fmean(nums)
    if agg == "min":
        return min(nums)
    if agg == "max":
        return max(nums)
    raise FormulaError(f"不支持的聚合方式: {agg}")


def _group_label(value: Any) -> str:
    """分组值 → 展示标签（空值统一为「（空）」）."""
    if _is_blank(value):
        return EMPTY_GROUP_LABEL
    return str(value).strip()


def _metric_defs(summary: Any) -> list[dict[str, str]]:
    """把配置里的指标展开为列定义（重复「函数+字段」时追加序号保证键唯一）."""
    defs: list[dict[str, str]] = []
    used: set[str] = set()
    for idx, metric in enumerate(summary.metrics):
        key = metric_key(metric.agg, metric.field)
        if key in used:
            key = f"{key}#{idx + 1}"
        used.add(key)
        defs.append(
            {
                "key": key,
                "label": metric_label(metric.agg, metric.field, metric.label),
                "agg": metric.agg,
                "source": metric.field,
            }
        )
    return defs


def compute_summary(
    rows: list[dict[str, Any]],
    computed: dict[str, list[float | None]],
    summary: Any,
    field_names: list[str],
) -> dict[str, Any]:
    """按配置做分组汇总（基于全量扫描行），返回可直接序列化的结果 dict.

    Args:
        rows: 扫描到的原始行（含 id）.
        computed: 公式键 → 逐行派生值.
        summary: ``SummarySpec``（或等价对象），含 group_by / metrics / sort / top_n.
        field_names: 可见字段名（与统计 / 图表同一口径）.

    Raises:
        FormulaError: 指标为空 / 引用了不存在的字段或公式键.
    """
    defs = _metric_defs(summary)
    if not defs:
        raise FormulaError("分组汇总至少需要一个指标")
    for item in defs:
        if item["agg"] not in AGG_ORDER:
            raise FormulaError(f"不支持的聚合方式: {item['agg']}")

    formula_keys = set(computed)
    group_by = summary.group_by

    if group_by is not None and group_by not in field_names:
        raise FormulaError(f"分组字段不存在: {group_by}")
    for item in defs:
        source = item["source"]
        if source not in field_names and source not in formula_keys:
            raise FormulaError(f"汇总指标引用了不存在的字段或公式: {source}")

    buckets: dict[str, dict[str, list[Any]]] = {}
    order: list[str] = []
    for idx, row in enumerate(rows):
        label = TOTAL_GROUP_LABEL if group_by is None else _group_label(row.get(group_by))
        bucket = buckets.get(label)
        if bucket is None:
            bucket = {item["key"]: [] for item in defs}
            buckets[label] = bucket
            order.append(label)
        for item in defs:
            source = item["source"]
            bucket[item["key"]].append(computed[source][idx] if source in formula_keys else row.get(source))

    out_rows: list[dict[str, Any]] = []
    for label in order:
        bucket = buckets[label]
        record: dict[str, Any] = {"group": label}
        for item in defs:
            record[item["key"]] = _aggregate(bucket[item["key"]], item["agg"])
        out_rows.append(record)

    group_count = len(out_rows)

    # 排序：sort_by 支持指标 key，也支持来源字段/公式（取首个匹配指标）
    sort_by = getattr(summary, "sort_by", None)
    if sort_by:
        sort_key = (
            sort_by
            if sort_by in {item["key"] for item in defs}
            else next(
                (item["key"] for item in defs if item["source"] == sort_by),
                None,
            )
        )
        if sort_key:
            desc = getattr(summary, "sort_order", "desc") == "desc"
            present = [row for row in out_rows if row.get(sort_key) is not None]
            absent = [row for row in out_rows if row.get(sort_key) is None]
            present.sort(key=lambda row: row[sort_key], reverse=desc)
            out_rows = present + absent

    top_n = getattr(summary, "top_n", None)
    truncated = bool(top_n and group_count > top_n)
    if top_n:
        out_rows = out_rows[:top_n]

    return {
        "group_by": group_by,
        "group_label": group_by or TOTAL_GROUP_LABEL,
        "columns": defs,
        "rows": out_rows,
        "group_count": group_count,
        "truncated": truncated,
    }


def compute(
    db: Session,
    table: DataTable,
    user: Any,
    *,
    formulas: list[dict[str, Any]],
    fields: list[str] | None = None,
    limit: int = 1000,
    summary: Any | None = None,
    filters: list[dict[str, Any]] | None = None,
    filter_logic: str = "AND",
) -> dict[str, Any]:
    """按公式计算派生列并返回行数据 + 描述统计 + 可选分组汇总.

    Args:
        formulas: [{"key","label","expr","partition_by","order_by","order_desc"}]，expr 已通过校验
            （此处仍会解析，非法即抛 FormulaError）；后三项是窗口函数的分区 / 排序上下文.
        fields: 需要返回的原始字段；空 = 全部可见字段.
        limit: 返回行数上限（统计仍基于全量扫描）.
        summary: 分组汇总配置（None = 不汇总）.
        filters / filter_logic: 扫描前的范围过滤（时间区间 / 分区等值），用于绕开
            ``MAX_SCAN_ROWS`` —— 只分析区间内的行，统计与汇总都基于过滤后的行.
    """
    _check_filter_fields(table, filters)
    rows, total, truncated = scan_rows(db, table, user, filters=filters, filter_logic=filter_logic)
    field_names = _allowed_field_names(table, rows)

    wanted = [f for f in (fields or []) if f in field_names] or field_names

    computed: dict[str, list[float | None]] = {}
    for spec in formulas:
        computed[spec["key"]] = evaluate_column(
            spec["expr"],
            rows,
            field_names,
            partition_by=spec.get("partition_by"),
            order_by=spec.get("order_by"),
            order_desc=bool(spec.get("order_desc", False)),
        )

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

    summary_result = compute_summary(rows, computed, summary, field_names) if summary is not None else None

    return {
        "rows": out_rows,
        "total": total,
        "truncated": truncated,
        "table_fields": field_names,
        "columns": columns,
        "summary": summary_result,
    }


__all__ = [
    "AGG_LABELS",
    "AGG_ORDER",
    "MAX_SCAN_ROWS",
    "compute",
    "compute_summary",
    "metric_key",
    "metric_label",
    "scan_limit",
    "scan_rows",
]
