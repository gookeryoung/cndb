"""dashboard 批量取数与服务端聚合（ADR 0023 P2）.

一次请求带上画布内多个 widget 的查询，对同一 ``(table, view.filters + 全局筛选)``
只扫描一次，多 widget 共享行集后各自聚合；单 widget 失败只回填一条 ``errors``，
不影响其它卡片。

产物与前端 ``dashboard/chart/dataset.ts`` 的 ``Dataset`` 同构（I3）：
``kind`` 为 category/pie/scatter/histogram/boxplot/radar/funnel/gauge/heatmap/treemap，
KPI 为 ``kpi``，明细为 ``table``。
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from cndb.core.cache import cache_key, dashboard_cache
from cndb.plugins.analytics.services.compute import scan_rows
from cndb.plugins.tables.models import DataTable, DataView

logger = logging.getLogger(__name__)

#: 缓存 TTL（秒）与失效口径见 ADR 0023 §4
DASHBOARD_CACHE_TTL = 60

#: 分组值缺失时的统一展示标签（与 matrixBoard 同口径）
UNGROUPED_LABEL = "未分组"
#: 未按 series 拆分时的内部系列键
SINGLE = "__single__"

#: 明细卡片列数 / 行数上限（与配置校验同口径）
TABLE_MAX_COLUMNS = 8

#: 聚合方式（与 dashboard_config.AGGREGATIONS 对齐）
_AGGREGATIONS = frozenset({"sum", "avg", "count", "min", "max", "median"})

#: 日期维度默认按月分桶（与客户端 dimKey 同口径）
_DATE_PREFIX_LEN = 10


class DashboardDataError(Exception):
    """单个 widget 无法取数（字段缺失 / 配置非法）."""


# ── 基础工具（与客户端 chartBoard / dashboardQuery 同口径）─────────────


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, str) and value.strip():
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _as_text(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return "" if value is None else str(value)


def _compare_values(a: Any, b: Any) -> int:
    """数值优先，否则字符串比较；空值恒排后."""
    blank_a, blank_b = _is_blank(a), _is_blank(b)
    if blank_a and blank_b:
        return 0
    if blank_a:
        return 1
    if blank_b:
        return -1
    na, nb = _to_number(a), _to_number(b)
    if na is not None and nb is not None:
        return -1 if na < nb else 1 if na > nb else 0
    sa, sb = str(a), str(b)
    return -1 if sa < sb else 1 if sa > sb else 0


def _matches(row: dict[str, Any], field_name: str, op: str, expected: Any) -> bool:
    actual = row.get(field_name)
    a, e = _as_text(actual), _as_text(expected)
    if op in ("eq", "="):
        return a == e
    if op in ("neq", "!="):
        return a != e
    if op in ("gt", ">"):
        return not _is_blank(actual) and _compare_values(actual, expected) > 0
    if op in ("gte", ">="):
        return not _is_blank(actual) and _compare_values(actual, expected) >= 0
    if op in ("lt", "<"):
        return not _is_blank(actual) and _compare_values(actual, expected) < 0
    if op in ("lte", "<="):
        return not _is_blank(actual) and _compare_values(actual, expected) <= 0
    if op == "contains":
        return e in a
    if op == "starts_with":
        return a.startswith(e)
    if op == "ends_with":
        return a.endswith(e)
    if op == "in":
        return isinstance(expected, list) and a in [_as_text(x) for x in expected]
    if op == "not_in":
        return isinstance(expected, list) and a not in [_as_text(x) for x in expected]
    if op in ("is_empty", "is_null"):
        return _is_blank(actual)
    if op in ("is_not_empty", "is_not_null"):
        return not _is_blank(actual)
    if op in ("contains_any", "has_any"):
        return isinstance(expected, list) and any(_as_text(x) in a for x in expected)
    if op in ("contains_all", "has_all"):
        return isinstance(expected, list) and all(_as_text(x) in a for x in expected)
    if op in ("between", "date_range"):
        if _is_blank(actual):
            return False
        if not isinstance(expected, list) or len(expected) < 2:
            return True
        return _compare_values(actual, expected[0]) >= 0 and _compare_values(actual, expected[1]) <= 0
    return True


def apply_widget_query(rows: list[dict[str, Any]], query: dict[str, Any]) -> list[dict[str, Any]]:
    """执行组件级 filters / sortings / limit（不修改入参）."""
    out = rows
    filters = query.get("filters") or []
    if filters:
        logic = query.get("filter_logic") or "AND"

        def check(row: dict[str, Any]) -> list[bool]:
            return [_matches(row, f["field_name"], f["op"], f.get("value")) for f in filters]

        if logic == "OR":
            out = [row for row in out if any(check(row))]
        else:
            out = [row for row in out if all(check(row))]
    sortings = query.get("sortings") or []
    if sortings:

        def _cmp(a: dict[str, Any], b: dict[str, Any]) -> int:
            for sorting in sortings:
                av, bv = a.get(sorting["field_name"]), b.get(sorting["field_name"])
                if _is_blank(av) != _is_blank(bv):
                    return 1 if _is_blank(av) else -1
                c = _compare_values(av, bv)
                if c:
                    return -c if sorting.get("direction") == "desc" else c
            return 0

        from functools import cmp_to_key

        out = sorted(out, key=cmp_to_key(_cmp))
    limit = query.get("limit")
    if limit is not None:
        out = out[: int(limit)]
    return out


# ── 字段与维度 ────────────────────────────────────────


class _FieldInfo:
    """字段名 / 归一类型 / select 选项（用于维度键与校验）."""

    def __init__(self, name: str, field_type: str, options: dict[str, str]) -> None:
        self.name = name
        self.field_type = field_type
        self.options = options


def _field_infos(table: DataTable) -> dict[str, _FieldInfo]:
    out: dict[str, _FieldInfo] = {}
    for field in table.active_fields():
        config = field.config or {}
        options: dict[str, str] = {}
        for item in config.get("options") or []:
            if isinstance(item, str):
                options[item] = item
            elif isinstance(item, dict):
                value = str(item.get("value", item.get("label", "")))
                options[value] = str(item.get("label", value))
        out[field.name] = _FieldInfo(field.name, field.field_type, options)
    return out


def _month_bucket(value: Any) -> str:
    """日期/时间值 → ``YYYY-MM``；空值 / 解析失败返回空串."""
    if _is_blank(value):
        return ""
    text = str(value).strip()

    def parse_iso(s: str) -> datetime:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    def parse_date(s: str) -> datetime:
        return datetime.strptime(s[:10], "%Y-%m-%d")

    def parse_slash(s: str) -> datetime:
        return datetime.strptime(s[:_DATE_PREFIX_LEN], "%Y/%m/%d")

    for parse in (parse_iso, parse_date, parse_slash):
        try:
            return parse(text).strftime("%Y-%m")
        except (ValueError, TypeError):
            continue
    return text[:7] if len(text) >= 7 else text


def _dim_key(row: dict[str, Any], info: _FieldInfo | None) -> str:
    """维度键；空值归「未分组」（与客户端 axisKeyForRow 同口径）."""
    if info is None:
        return UNGROUPED_LABEL
    value = row.get(info.name)
    if _is_blank(value):
        return UNGROUPED_LABEL
    if info.field_type in ("date", "datetime"):
        return _month_bucket(value) or UNGROUPED_LABEL
    if info.field_type == "select":
        return info.options.get(str(value), str(value))
    if info.field_type in ("multi_select", "multiselect"):
        if isinstance(value, list):
            return str(value[0]) if value else UNGROUPED_LABEL
        first = str(value).split(",")[0].strip()
        return first or UNGROUPED_LABEL
    if info.field_type == "boolean":
        return "是" if value else "否"
    if isinstance(value, list):
        return str(value[0]) if value else UNGROUPED_LABEL
    return str(value)


def _sort_keys(keys: list[str], _date_axis: bool) -> list[str]:
    """排序轴 key：日期按字典序（==时序），其它按字符串序；「未分组」恒最后."""
    grouped = [k for k in keys if k != UNGROUPED_LABEL]
    has_ungrouped = len(grouped) != len(keys)
    grouped.sort()
    if has_ungrouped:
        grouped.append(UNGROUPED_LABEL)
    return grouped


def _is_date(info: _FieldInfo | None) -> bool:
    return bool(info) and info.field_type in ("date", "datetime")


# ── 聚合 ──────────────────────────────────────────────


def _aggregate(values: list[Any], agg: str) -> float | int | None:
    if agg not in _AGGREGATIONS:
        raise DashboardDataError(f"不支持的聚合方式: {agg}")
    if not values:
        return None
    if agg == "count":
        return sum(1 for value in values if not _is_blank(value))
    nums = [n for value in values if (n := _to_number(value)) is not None]
    if not nums:
        return None
    if agg == "sum":
        return sum(nums)
    if agg == "avg":
        return sum(nums) / len(nums)
    if agg == "min":
        return min(nums)
    if agg == "max":
        return max(nums)
    ordered = sorted(nums)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _quantile(ordered: list[float], q: float) -> float:
    """线性插值分位数（R-7，与客户端 boxplot 同口径）."""
    pos = (len(ordered) - 1) * q
    low, high = math.floor(pos), math.ceil(pos)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


# ── Dataset 装配 ─────────────────────────────────────


def _require(info: dict[str, _FieldInfo], name: str | None, role: str) -> _FieldInfo:
    if name is None or name not in info:
        raise DashboardDataError(f"字段缺失: {role}={name}")
    return info[name]


def _collect(
    rows: list[dict[str, Any]],
    infos: dict[str, _FieldInfo],
    chart: dict[str, Any],
) -> tuple[list[str], dict[str, dict[str, list[Any]]]]:
    dim = _require(infos, chart.get("x"), "x")
    series_info = _require(infos, chart.get("series"), "series") if chart.get("series") else None
    series: dict[str, dict[str, list[Any]]] = {}
    categories: dict[str, None] = {}
    for row in rows:
        cat = _dim_key(row, dim)
        categories[cat] = None
        series_value = _dim_key(row, series_info) if series_info else SINGLE
        for field_name in chart["y"]:
            if len(chart["y"]) > 1:
                series_name = f"{field_name} · {series_value}" if series_info else field_name
            else:
                series_name = series_value if series_info else field_name
            bucket = series.setdefault(series_name, {})
            bucket.setdefault(cat, []).append(row.get(field_name))
    return list(categories.keys()), series


def _finalize_categories(
    dataset: dict[str, Any],
    chart: dict[str, Any],
    date_axis: bool,
) -> dict[str, Any]:
    categories = list(dataset["categories"])
    # series.data 始终按「原始 categories 顺序」排列，索引必须基于原顺序取数
    indexes = {cat: i for i, cat in enumerate(categories)}
    sort = chart.get("sort") or "none"
    if sort != "none":
        by_y = sort in ("asc", "desc", "y_asc", "y_desc")
        desc = sort in ("desc", "y_desc", "x_desc")

        def metric(cat: str) -> float:
            return sum((s["data"][indexes[cat]] or 0) for s in dataset["series"])

        if by_y:
            categories.sort(key=metric, reverse=desc)
        else:
            categories.sort(reverse=desc)
    else:
        categories = _sort_keys(categories, date_axis)

    series = dataset["series"]
    top_n = chart.get("top_n")
    if top_n and len(categories) > top_n:
        keep = categories[:top_n]
        rest = categories[top_n:]
        other = [sum((s["data"][indexes[cat]] or 0) for cat in rest) for s in series]
        categories = [*keep, "其他"]
        series = [
            {
                "name": s["name"],
                "data": [s["data"][indexes[cat]] for cat in keep] + [other[i]],
            }
            for i, s in enumerate(series)
        ]
    else:
        series = [
            {"name": s["name"], "data": [s["data"][indexes[cat]] if cat in indexes else None for cat in categories]}
            for s in series
        ]

    if chart.get("stack") == "percent":
        totals = [sum((s["data"][ci] or 0) for s in series) for ci in range(len(categories))]
        series = [
            {
                "name": s["name"],
                "data": [
                    (v / totals[ci]) * 100 if totals[ci] > 0 and v is not None else None
                    for ci, v in enumerate(s["data"])
                ],
            }
            for s in series
        ]
    return {"kind": "category", "categories": categories, "series": series}


def build_category_dataset(
    rows: list[dict[str, Any]],
    infos: dict[str, _FieldInfo],
    chart: dict[str, Any],
) -> dict[str, Any]:
    categories, buckets = _collect(rows, infos, chart)
    base = {
        "kind": "category",
        "categories": categories,
        "series": [
            {"name": name, "data": [_aggregate(by_cat.get(cat, []), chart["agg"]) for cat in categories]}
            for name, by_cat in buckets.items()
        ],
    }
    return _finalize_categories(base, chart, _is_date(infos.get(chart.get("x") or "")))


def build_pie_dataset(
    rows: list[dict[str, Any]],
    infos: dict[str, _FieldInfo],
    chart: dict[str, Any],
) -> dict[str, Any]:
    data = build_category_dataset(rows, infos, chart)
    first = data["series"][0] if data["series"] else None
    items = [
        {"name": name, "value": (first["data"][i] if first else 0) or 0} for i, name in enumerate(data["categories"])
    ]
    return {"kind": "pie", "items": [item for item in items if item["value"] != 0]}


def build_scatter_dataset(rows: list[dict[str, Any]], chart: dict[str, Any]) -> dict[str, Any]:
    x_name = chart.get("x")
    y_name = chart["y"][0]
    points: list[list[float]] = []
    row_ids: list[Any] = []
    if not x_name:
        return {"kind": "scatter", "points": points, "rowIds": row_ids}
    for row in rows:
        x, y = _to_number(row.get(x_name)), _to_number(row.get(y_name))
        if x is None or y is None:
            continue
        points.append([x, y])
        row_ids.append(row.get("id"))
    return {"kind": "scatter", "points": points, "rowIds": row_ids}


def _js_number(value: float, sig: int = 6) -> str:
    """JS ``parseFloat(v.toPrecision(sig))`` 的近似：整数原样，否则去尾零."""
    if float(value).is_integer():
        return str(int(value))
    text = f"{value:.{sig}g}"
    return str(float(text))


def _label_precision(width: float, maximum: float) -> int:
    if not math.isfinite(width) or width <= 0:
        return 6
    int_digits = max(1, math.ceil(math.log10(abs(maximum) + 1)))
    frac_digits = max(0, math.ceil(-math.log10(width)) + 1)
    return min(17, max(6, int_digits + frac_digits))


def build_histogram_dataset(rows: list[dict[str, Any]], chart: dict[str, Any]) -> dict[str, Any]:
    field_name = chart["y"][0]
    values = [n for row in rows if (n := _to_number(row.get(field_name))) is not None]
    if not values:
        return {"kind": "histogram", "bins": []}
    n = len(values)
    minimum, maximum = min(values), max(values)
    if n == 1 or minimum == maximum:
        return {
            "kind": "histogram",
            "bins": [
                {
                    "label": f"{_js_number(minimum)}~{_js_number(maximum)}",
                    "count": n,
                    "from": minimum,
                    "to": maximum,
                }
            ],
        }
    bin_count = max(1, min(math.ceil(math.sqrt(n)), n, 512))
    width = (maximum - minimum) / bin_count
    sig = _label_precision(width, maximum)
    bins = []
    for i in range(bin_count):
        start = minimum + i * width
        end = maximum if i == bin_count - 1 else minimum + (i + 1) * width
        if i == bin_count - 1:
            count = sum(1 for v in values if start <= v <= end)
        else:
            count = sum(1 for v in values if start <= v < end)
        bins.append(
            {
                "label": f"{_js_number(start, sig)}~{_js_number(end, sig)}",
                "count": count,
                "from": start,
                "to": end,
            }
        )
    return {"kind": "histogram", "bins": bins}


def build_boxplot_dataset(
    rows: list[dict[str, Any]],
    infos: dict[str, _FieldInfo],
    chart: dict[str, Any],
) -> dict[str, Any]:
    dim = infos.get(chart.get("x") or "")
    y_name = chart["y"][0]
    buckets: dict[str, list[float]] = {}
    for row in rows:
        value = _to_number(row.get(y_name))
        if value is None:
            continue
        buckets.setdefault(_dim_key(row, dim), []).append(value)
    categories = _sort_keys(list(buckets.keys()), _is_date(dim))
    boxes: list[list[float]] = []
    outliers: list[list[float]] = []
    for ci, cat in enumerate(categories):
        ordered = sorted(buckets.get(cat) or [])
        if not ordered:
            continue
        q1, med, q3 = _quantile(ordered, 0.25), _quantile(ordered, 0.5), _quantile(ordered, 0.75)
        boxes.append([ordered[0], q1, med, q3, ordered[-1]])
        iqr = q3 - q1
        low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        for value in ordered:
            if value < low or value > high:
                outliers.append([ci, value])
    return {"kind": "boxplot", "categories": categories, "boxes": boxes, "outliers": outliers}


def build_radar_dataset(
    rows: list[dict[str, Any]],
    infos: dict[str, _FieldInfo],
    chart: dict[str, Any],
) -> dict[str, Any]:
    dim = infos.get(chart.get("x") or "")
    series_info = infos.get(chart.get("series") or "") if chart.get("series") else None
    polygons: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cat = _dim_key(row, dim)
        key = f"{cat} · {_dim_key(row, series_info)}" if series_info else cat
        polygons.setdefault(key, []).append(row)
    names = _sort_keys(list(polygons.keys()), False)
    raw = [
        {
            "name": name,
            "values": [
                _aggregate([r.get(field) for r in polygons.get(name) or []], chart["agg"]) or 0 for field in chart["y"]
            ],
        }
        for name in names
    ]
    indicators = []
    for i, name in enumerate(chart["y"]):
        maximum = max([1.0, *(float(s["values"][i]) for s in raw)])
        indicators.append({"name": name, "max": math.ceil(maximum * 1.1)})
    return {"kind": "radar", "indicators": indicators, "series": raw}


def build_funnel_dataset(
    rows: list[dict[str, Any]],
    infos: dict[str, _FieldInfo],
    chart: dict[str, Any],
) -> dict[str, Any]:
    data = build_category_dataset(rows, infos, {**chart, "stack": "none"})
    first = data["series"][0] if data["series"] else None
    items = [
        {"name": name, "value": (first["data"][i] if first else 0) or 0} for i, name in enumerate(data["categories"])
    ]
    sort = chart.get("sort") if chart.get("sort") not in (None, "none") else "y_desc"
    desc = sort in ("desc", "y_desc", "x_desc")
    if sort in ("x_asc", "x_desc"):
        items.sort(key=lambda item: item["name"], reverse=desc)
    else:
        items.sort(key=lambda item: item["value"], reverse=desc)
    top_n = chart.get("top_n")
    return {"kind": "funnel", "items": items[:top_n] if top_n else items}


def build_gauge_dataset(rows: list[dict[str, Any]], chart: dict[str, Any]) -> dict[str, Any]:
    value = _aggregate([row.get(chart["y"][0]) for row in rows], chart["agg"])
    target = chart.get("target")
    if target is None:
        target = max(1, math.ceil(value * 1.2)) if value is not None else None
    return {"kind": "gauge", "name": chart["y"][0], "value": value, "target": target}


def build_heatmap_dataset(
    rows: list[dict[str, Any]],
    infos: dict[str, _FieldInfo],
    chart: dict[str, Any],
) -> dict[str, Any]:
    x_info = _require(infos, chart.get("x"), "x")
    y_info = _require(infos, chart.get("series"), "series")
    cells: dict[str, dict[str, list[Any]]] = {}
    for row in rows:
        cells.setdefault(_dim_key(row, x_info), {}).setdefault(_dim_key(row, y_info), []).append(row.get(chart["y"][0]))
    x = _sort_keys(list(cells.keys()), _is_date(x_info))
    y_keys: dict[str, None] = {}
    for by_y in cells.values():
        for key in by_y:
            y_keys[key] = None
    y = _sort_keys(list(y_keys.keys()), _is_date(y_info))
    values: list[list[float]] = []
    maximum = 0.0
    for xi, xv in enumerate(x):
        for yi, yv in enumerate(y):
            value = _aggregate(cells.get(xv, {}).get(yv, []), chart["agg"]) or 0
            values.append([xi, yi, value])
            maximum = max(maximum, float(value))
    return {"kind": "heatmap", "x": x, "y": y, "values": values, "max": maximum or 1}


def build_treemap_dataset(
    rows: list[dict[str, Any]],
    infos: dict[str, _FieldInfo],
    chart: dict[str, Any],
) -> dict[str, Any]:
    x_info = _require(infos, chart.get("x"), "x")
    s_info = _require(infos, chart.get("series"), "series")
    children: dict[str, dict[str, list[Any]]] = {}
    for row in rows:
        parent = _dim_key(row, x_info)
        child = _dim_key(row, s_info)
        children.setdefault(parent, {}).setdefault(child, []).append(row.get(chart["y"][0]))
    nodes = []
    for name, by_child in children.items():
        items = [
            {"name": child_name, "value": _aggregate(values, chart["agg"]) or 0}
            for child_name, values in by_child.items()
        ]
        nodes.append(
            {
                "name": name,
                "value": sum(item["value"] for item in items),
                "children": items,
            }
        )
    nodes.sort(key=lambda node: node["value"], reverse=True)
    return {"kind": "treemap", "nodes": nodes}


def _chart_dataset(
    rows: list[dict[str, Any]],
    infos: dict[str, _FieldInfo],
    chart: dict[str, Any],
) -> dict[str, Any]:
    chart_type = chart.get("type")
    if chart_type in ("bar", "line", "area", "stack", "combo"):
        return build_category_dataset(rows, infos, chart)
    if chart_type == "pie":
        return build_pie_dataset(rows, infos, chart)
    if chart_type == "scatter":
        return build_scatter_dataset(rows, chart)
    if chart_type == "histogram":
        return build_histogram_dataset(rows, chart)
    if chart_type == "boxplot":
        return build_boxplot_dataset(rows, infos, chart)
    if chart_type == "radar":
        return build_radar_dataset(rows, infos, chart)
    if chart_type == "funnel":
        return build_funnel_dataset(rows, infos, chart)
    if chart_type == "gauge":
        return build_gauge_dataset(rows, chart)
    if chart_type == "heatmap":
        return build_heatmap_dataset(rows, infos, chart)
    if chart_type == "treemap":
        return build_treemap_dataset(rows, infos, chart)
    raise DashboardDataError(f"不支持的图表类型: {chart_type}")


# ── 全局筛选 ──────────────────────────────────────────


def _global_filters(
    config_filters: list[dict[str, Any]],
    values: dict[str, Any],
) -> list[dict[str, Any]]:
    """把请求 ``globals`` 映射成扫描期 filters；缺值即忽略（§5-5）."""
    out: list[dict[str, Any]] = []
    for item in config_filters:
        value = values.get(str(item.get("id")))
        if value is None or value in ("", []):
            continue
        kind = item.get("kind")
        field_name = item.get("field")
        if kind == "date_range":
            if isinstance(value, dict):
                start = value.get("from") or value.get("start")
                end = value.get("to") or value.get("end")
                value = [start, end]
            if isinstance(value, list) and len(value) >= 2:
                out.append({"field_name": field_name, "op": "date_range", "value": value[:2]})
        elif kind == "select":
            if isinstance(value, list):
                out.append({"field_name": field_name, "op": "in", "value": value})
            else:
                out.append({"field_name": field_name, "op": "eq", "value": value})
        elif kind == "search":
            out.append({"field_name": field_name, "op": "contains", "value": value})
    return out


# ── 请求入口 ──────────────────────────────────────────


def _cache_key(
    workspace_id: int,
    table_id: int,
    view_id: int,
    updated_at: str,
    user_id: int,
    widget_ids: list[str],
    globals_values: dict[str, Any],
) -> str:
    digest = hashlib.sha256(
        json.dumps(globals_values, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return cache_key(
        "dashboard",
        workspace_id,
        table_id,
        view_id,
        updated_at,
        user_id,
        ",".join(widget_ids),
        digest,
    )


def _build_widget(
    widget: dict[str, Any],
    rows: list[dict[str, Any]],
    infos: dict[str, _FieldInfo],
) -> dict[str, Any]:
    """单 widget → Dataset；text 不取数（返回空 kind）."""
    widget_type = widget.get("type")
    query = widget.get("query") or {}
    widget_rows = apply_widget_query(rows, query)
    if widget_type == "chart":
        return _chart_dataset(widget_rows, infos, widget["chart"])
    if widget_type == "kpi":
        value = widget["kpi"]["value"]
        return {
            "kind": "kpi",
            "field": value["field"],
            "agg": value["agg"],
            "value": _aggregate([row.get(value["field"]) for row in widget_rows], value["agg"]),
        }
    if widget_type == "table":
        table = widget["table"]
        columns = [name for name in table.get("columns") or [] if name in infos][:TABLE_MAX_COLUMNS]
        limit = int(table.get("row_limit") or 50)
        return {
            "kind": "table",
            "columns": columns,
            "rows": [
                {**{"id": row.get("id")}, **{name: row.get(name) for name in columns}} for row in widget_rows[:limit]
            ],
            "total": len(widget_rows),
        }
    return {"kind": "none"}


def build_dashboard_data(
    db: Session,
    table: DataTable,
    view: DataView,
    user: Any,
    config: dict[str, Any],
    *,
    workspace_id: int,
    widget_ids: list[str] | None = None,
    globals_values: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """批量取数：同一行集只扫描一次，逐 widget 聚合.

    Returns:
        ``{"items": [{"widget_id", "dataset", "meta"}], "errors": [...]}``
    """
    values = globals_values or {}
    widgets = {str(w["id"]): w for w in config.get("widgets") or []}
    wanted = widget_ids or [wid for wid, w in widgets.items() if w.get("type") != "text"]

    updated_at = view.updated_at.isoformat() if view.updated_at else ""
    key = _cache_key(
        workspace_id,
        int(table.id),
        int(view.id),
        updated_at,
        int(user.id),
        list(wanted),
        values,
    )
    cached_payload = None if force else dashboard_cache.get(key)
    if cached_payload is not None:
        return {
            "items": [{**item, "meta": {**item["meta"], "cached": True}} for item in cached_payload["items"]],
            "errors": list(cached_payload["errors"]),
        }

    infos = _field_infos(table)
    scan_filters = [*(view.filters or []), *_global_filters(config.get("global_filters") or [], values)]
    rows, total, truncated = scan_rows(
        db,
        table,
        user,
        filters=scan_filters or None,
        filter_logic=view.filter_type or "AND",
    )

    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for widget_id in wanted:
        widget = widgets.get(widget_id)
        if widget is None:
            errors.append({"widget_id": widget_id, "detail": "widget 不存在"})
            continue
        try:
            dataset = _build_widget(widget, rows, infos)
        except DashboardDataError as exc:
            errors.append({"widget_id": widget_id, "detail": str(exc)})
            continue
        except Exception:  # pragma: no cover - 兜底：单卡失败不拖垮整页
            logger.warning("dashboard widget 取数失败 widget=%s", widget_id, exc_info=True)
            errors.append({"widget_id": widget_id, "detail": "取数失败"})
            continue
        items.append(
            {
                "widget_id": widget_id,
                "dataset": dataset,
                "meta": {"scanned": len(rows), "total": total, "truncated": truncated, "cached": False},
            }
        )

    payload = {"items": items, "errors": errors}
    dashboard_cache.set(key, payload, DASHBOARD_CACHE_TTL)
    return payload


__all__ = [
    "DASHBOARD_CACHE_TTL",
    "DashboardDataError",
    "apply_widget_query",
    "build_boxplot_dataset",
    "build_category_dataset",
    "build_dashboard_data",
    "build_funnel_dataset",
    "build_gauge_dataset",
    "build_heatmap_dataset",
    "build_histogram_dataset",
    "build_pie_dataset",
    "build_radar_dataset",
    "build_scatter_dataset",
    "build_treemap_dataset",
]
