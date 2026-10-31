"""dashboard 视图配置（``view_options``）的校验与白名单归一（ADR 0023 P0）.

该模块是 dashboard 契约的后端唯一入口：

- ``normalize_dashboard_config`` 校验并裁剪未知键，返回可直接落库的嵌套配置；
- 与前端 ``frontend/src/pages/grid/views/dashboard/dashboardModel.ts``
  由 ``tests/fixtures/dashboard/schema_cases.json`` 的同一组用例驱动，防止口径漂移。

P0 只做单表（``query.table_id`` 禁止）、客户端聚合所需的结构校验；
跨表 / 服务端聚合在 P2/P3 再扩展。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, cast

from cndb.plugins.tables.field_types.registry import normalize_field_type

#: widget 数量上限（ADR 0023 §1）
MAX_WIDGETS = 32
#: 画布固定 12 列
CANVAS_COLS = 12
#: widget 高度上限（格）
MAX_WIDGET_H = 20
#: widget 纵坐标上限
MAX_WIDGET_Y = 200
#: P0 支持的 widget 类型
WIDGET_TYPES = frozenset({"chart", "kpi", "table", "text"})
#: P0-P2 支持的图表类型（与 dashboard/chart/chartRegistry.ts 对齐）
CHART_TYPES = frozenset(
    {
        "bar",
        "line",
        "pie",
        "scatter",
        "histogram",
        "boxplot",
        "area",
        "stack",
        "combo",
        "radar",
        "funnel",
        "gauge",
        "heatmap",
        "treemap",
    }
)
#: 聚合方式（median 为 P2 新增）
AGGREGATIONS = frozenset({"sum", "avg", "count", "min", "max", "median"})
#: 类目排序口径（asc/desc 为 P0 兼容值，语义等同 y_asc/y_desc）
SORT_VALUES = frozenset({"none", "asc", "desc", "x_asc", "x_desc", "y_asc", "y_desc"})
#: 阈值配色条目上限
MAX_THRESHOLDS = 5
#: 全局筛选类型
GLOBAL_FILTER_KINDS = frozenset({"date_range", "select", "search"})
#: 过滤操作符（与 services/core/query.py 实际支持的正名对齐）
FILTER_OPS = frozenset(
    {
        "eq",
        "=",
        "neq",
        "!=",
        "gt",
        ">",
        "gte",
        ">=",
        "lt",
        "<",
        "lte",
        "<=",
        "in",
        "not_in",
        "contains",
        "starts_with",
        "ends_with",
        "is_empty",
        "is_not_empty",
        "is_null",
        "is_not_null",
        "contains_any",
        "contains_all",
        "between",
        "date_range",
        "has_any",
        "has_all",
    }
)
#: 数值类字段（归一化后的 registry 名）
NUMERIC_FIELD_TYPES = frozenset({"number", "float", "percentage", "timestamp"})
#: 日期类字段
DATE_FIELD_TYPES = frozenset({"date", "datetime"})
#: KPI 对比周期
COMPARE_MODES = frozenset({"prev_period", "prev_year"})
#: 时间粒度
GRANULARITIES = frozenset({"day", "week", "month", "quarter", "year"})
#: id 规则（widget / 全局筛选）
_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


def _is_int(value: Any) -> bool:
    """是否为真正的整数（排除 bool）."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number_type(field_type: str) -> bool:
    return normalize_field_type(field_type) in NUMERIC_FIELD_TYPES


def _is_date_type(field_type: str) -> bool:
    return normalize_field_type(field_type) in DATE_FIELD_TYPES


def _normalize_filters(
    raw: Any,
    path: str,
    fields: Mapping[str, str],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """校验并裁剪 filters 数组."""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, f"{path}: 必须是数组"
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        item_path = f"{path}[{i}]"
        if not isinstance(item, dict):
            return None, f"{item_path}: 必须是对象"
        field_name = item.get("field_name")
        if not isinstance(field_name, str) or not field_name:
            return None, f"{item_path}.field_name: 必须是非空字符串"
        if field_name not in fields:
            return None, f"{item_path}.field_name: 字段不存在 ({field_name})"
        op = item.get("op")
        if not isinstance(op, str) or op not in FILTER_OPS:
            return None, f"{item_path}.op: 不支持的操作符 ({op})"
        out.append({"field_name": field_name, "op": op, "value": item.get("value")})
    return out, None


def _normalize_sortings(
    raw: Any,
    path: str,
    fields: Mapping[str, str],
) -> tuple[list[dict[str, str]] | None, str | None]:
    """校验并裁剪 sortings 数组."""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, f"{path}: 必须是数组"
    out: list[dict[str, str]] = []
    for i, item in enumerate(raw):
        item_path = f"{path}[{i}]"
        if not isinstance(item, dict):
            return None, f"{item_path}: 必须是对象"
        field_name = item.get("field_name")
        if not isinstance(field_name, str) or not field_name:
            return None, f"{item_path}.field_name: 必须是非空字符串"
        if field_name not in fields:
            return None, f"{item_path}.field_name: 字段不存在 ({field_name})"
        direction = item.get("direction", "asc")
        if direction not in ("asc", "desc"):
            return None, f"{item_path}.direction: 必须是 asc/desc"
        out.append({"field_name": field_name, "direction": direction})
    return out, None


def _normalize_query(
    raw: Any,
    path: str,
    fields: Mapping[str, str],
) -> tuple[dict[str, Any] | None, str | None]:
    """校验 widget.query."""
    if raw is None:
        return {"filters": [], "filter_logic": "AND", "sortings": []}, None
    if not isinstance(raw, dict):
        return None, f"{path}: 必须是对象"
    if "table_id" in raw:
        return None, f"{path}.table_id: P0-P2 禁止跨表"
    filters, err = _normalize_filters(raw.get("filters"), f"{path}.filters", fields)
    if err:
        return None, err
    sortings, err = _normalize_sortings(raw.get("sortings"), f"{path}.sortings", fields)
    if err:
        return None, err
    logic = raw.get("filter_logic", "AND")
    if logic not in ("AND", "OR"):
        return None, f"{path}.filter_logic: 必须是 AND/OR"
    query: dict[str, Any] = {"filters": filters, "filter_logic": logic, "sortings": sortings}
    limit = raw.get("limit")
    if limit is not None:
        if not _is_int(limit) or not (1 <= limit <= 5000):
            return None, f"{path}.limit: 必须是 1..5000 的整数"
        query["limit"] = limit
    return query, None


def _validate_field_ref(
    value: Any,
    path: str,
    fields: Mapping[str, str],
) -> tuple[str | None, str | None]:
    """校验单个字段引用存在."""
    if not isinstance(value, str) or not value:
        return None, f"{path}: 必须是非空字段名"
    if value not in fields:
        return None, f"{path}: 字段不存在 ({value})"
    return value, None


def _normalize_chart(
    raw: Any,
    path: str,
    fields: Mapping[str, str],
) -> tuple[dict[str, Any] | None, str | None]:
    """校验 widget.chart（P0 六类图表的角色声明）."""
    if not isinstance(raw, dict):
        return None, f"{path}: 必须是对象"
    chart_type = raw.get("type")
    if chart_type not in CHART_TYPES:
        return None, f"{path}.type: 不支持的图表类型 ({chart_type})"
    agg = raw.get("agg", "sum")
    if agg not in AGGREGATIONS:
        return None, f"{path}.agg: 不支持的聚合方式 ({agg})"

    x_field: str | None = None
    # gauge 是单值卡：不需要类目轴（x 可省略）
    if chart_type not in ("histogram", "gauge"):
        x_field, err = _validate_field_ref(raw.get("x"), f"{path}.x", fields)
        if err:
            return None, err

    y_raw = raw.get("y")
    if not isinstance(y_raw, list) or not y_raw:
        return None, f"{path}.y: 必须是非空数组"
    if len(y_raw) > 8:
        return None, f"{path}.y: 度量最多 8 个"
    y_fields: list[str] = []
    for i, value in enumerate(y_raw):
        field_name, err = _validate_field_ref(value, f"{path}.y[{i}]", fields)
        if err or field_name is None:
            return None, err or f"{path}.y[{i}]: 必须是非空字段名"
        field_type = fields[field_name]
        if agg != "count" and not _is_number_type(field_type):
            return None, f"{path}.y[{i}]: 非数值字段不能用于 {agg}"
        if chart_type == "scatter" and not _is_number_type(field_type):
            return None, f"{path}.y[{i}]: 散点图 Y 轴必须是数值字段"
        if chart_type == "histogram" and not _is_number_type(field_type):
            return None, f"{path}.y[{i}]: 直方图度量必须是数值字段"
        y_fields.append(field_name)

    if chart_type == "scatter" and not _is_number_type(fields[x_field or ""]):
        return None, f"{path}.x: 散点图 X 轴必须是数值字段"

    series = raw.get("series")
    if series is not None:
        series, err = _validate_field_ref(series, f"{path}.series", fields)
        if err:
            return None, err
    # 二维分布 / 层级占比必须给出第二维（series）
    if chart_type in ("heatmap", "treemap") and series is None:
        return None, f"{path}.series: {chart_type} 必须指定第二维字段"

    stack = raw.get("stack", "none")
    if stack not in ("none", "stack", "percent"):
        return None, f"{path}.stack: 必须是 none/stack/percent"
    sort = raw.get("sort", "none")
    if sort not in SORT_VALUES:
        return None, f"{path}.sort: 必须是 none/asc/desc/x_asc/x_desc/y_asc/y_desc"
    top_n = raw.get("top_n")
    if top_n is not None and (not _is_int(top_n) or not (1 <= top_n <= 100)):
        return None, f"{path}.top_n: 必须是 1..100 的整数"
    dual_axis = raw.get("dual_axis", False)
    if not isinstance(dual_axis, bool):
        return None, f"{path}.dual_axis: 必须是布尔值"
    target = raw.get("target")
    if target is not None and (isinstance(target, bool) or not isinstance(target, (int, float))):
        return None, f"{path}.target: 必须是数值"

    fmt_raw = raw.get("format")
    fmt: dict[str, Any] = {}
    if fmt_raw is not None:
        if not isinstance(fmt_raw, dict):
            return None, f"{path}.format: 必须是对象"
        unit = fmt_raw.get("unit")
        if unit is not None:
            if not isinstance(unit, str) or len(unit) > 16:
                return None, f"{path}.format.unit: 必须是长度 ≤16 的字符串"
            fmt["unit"] = unit
        decimals = fmt_raw.get("decimals")
        if decimals is not None:
            if not _is_int(decimals) or not (0 <= decimals <= 6):
                return None, f"{path}.format.decimals: 必须是 0..6 的整数"
            fmt["decimals"] = decimals

    return {
        "type": chart_type,
        "x": x_field,
        "y": y_fields,
        "series": series,
        "agg": agg,
        "stack": stack,
        "sort": sort,
        "top_n": top_n,
        "dual_axis": dual_axis,
        "target": target,
        "format": fmt,
    }, None


def _validate_agg_field(
    value: Any,
    path: str,
    fields: Mapping[str, str],
    *,
    require_numeric_when_not_count: bool = True,
) -> tuple[dict[str, str] | None, str | None]:
    """校验 KPI / sparkline 的 {field, agg} 组合."""
    if not isinstance(value, dict):
        return None, f"{path}: 必须是对象"
    field_name = value.get("field")
    agg = value.get("agg", "count")
    if agg not in AGGREGATIONS:
        return None, f"{path}.agg: 不支持的聚合方式 ({agg})"
    field_name, err = _validate_field_ref(field_name, f"{path}.field", fields)
    if err or field_name is None:
        return None, err or f"{path}.field: 必须是非空字段名"
    if require_numeric_when_not_count and agg != "count" and not _is_number_type(fields[field_name]):
        return None, f"{path}.field: 非数值字段不能用于 {agg}"
    return {"field": field_name, "agg": agg}, None


def _normalize_kpi(
    raw: Any,
    path: str,
    fields: Mapping[str, str],
) -> tuple[dict[str, Any] | None, str | None]:
    """校验 widget.kpi."""
    if not isinstance(raw, dict):
        return None, f"{path}: 必须是对象"
    value, err = _validate_agg_field(raw.get("value"), f"{path}.value", fields)
    if err:
        return None, err
    kpi: dict[str, Any] = {"value": value}

    compare = raw.get("compare")
    if compare is not None:
        if not isinstance(compare, dict):
            return None, f"{path}.compare: 必须是对象"
        mode = compare.get("mode")
        if mode not in COMPARE_MODES:
            return None, f"{path}.compare.mode: 必须是 prev_period/prev_year"
        date_field, err = _validate_field_ref(compare.get("date_field"), f"{path}.compare.date_field", fields)
        if err or date_field is None:
            return None, err or f"{path}.compare.date_field: 必须是非空字段名"
        if not _is_date_type(fields[date_field]):
            return None, f"{path}.compare.date_field: 必须是日期/时间字段"
        granularity = compare.get("granularity", "month")
        if granularity not in GRANULARITIES:
            return None, f"{path}.compare.granularity: 必须是 day/week/month/quarter/year"
        kpi["compare"] = {"mode": mode, "date_field": date_field, "granularity": granularity}

    sparkline = raw.get("sparkline")
    if sparkline is not None:
        if not isinstance(sparkline, dict):
            return None, f"{path}.sparkline: 必须是对象"
        spark_value, err = _validate_agg_field(
            {"field": sparkline.get("field"), "agg": sparkline.get("agg", "count")},
            f"{path}.sparkline",
            fields,
        )
        if err or spark_value is None:
            return None, err or f"{path}.sparkline: 必须是非空字段名"
        points = sparkline.get("points", 12)
        if not _is_int(points) or not (1 <= points <= 24):
            return None, f"{path}.sparkline.points: 必须是 1..24 的整数"
        kpi["sparkline"] = {**spark_value, "points": points}
    return kpi, None


def _normalize_table_widget(
    raw: Any,
    path: str,
    fields: Mapping[str, str],
) -> tuple[dict[str, Any] | None, str | None]:
    """校验 widget.table（P2 才渲染，P0 先允许配置往返）."""
    if not isinstance(raw, dict):
        return None, f"{path}: 必须是对象"
    columns_raw = raw.get("columns", [])
    if not isinstance(columns_raw, list):
        return None, f"{path}.columns: 必须是数组"
    if len(columns_raw) > 8:
        return None, f"{path}.columns: 最多 8 列"
    columns: list[str] = []
    for i, column in enumerate(columns_raw):
        field_name, err = _validate_field_ref(column, f"{path}.columns[{i}]", fields)
        if err or field_name is None:
            return None, err or f"{path}.columns[{i}]: 必须是非空字段名"
        columns.append(field_name)
    row_limit = raw.get("row_limit", 50)
    if not _is_int(row_limit) or not (1 <= row_limit <= 50):
        return None, f"{path}.row_limit: 必须是 1..50 的整数"
    return {"columns": columns, "row_limit": row_limit}, None


def _normalize_global_filters(
    raw: Any,
    fields: Mapping[str, str],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """校验 global_filters."""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "global_filters: 必须是数组"
    if len(raw) > 12:
        return None, "global_filters: 最多 12 项"
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        path = f"global_filters[{i}]"
        if not isinstance(item, dict):
            return None, f"{path}: 必须是对象"
        filter_id = item.get("id")
        if not isinstance(filter_id, str) or not _ID_RE.fullmatch(filter_id):
            return None, f"{path}.id: 必须是 1..32 位字母数字/下划线/短横线"
        if filter_id in seen:
            return None, f"{path}.id: 重复 ({filter_id})"
        seen.add(filter_id)
        kind = item.get("kind")
        if kind not in GLOBAL_FILTER_KINDS:
            return None, f"{path}.kind: 必须是 date_range/select/search"
        field_name, err = _validate_field_ref(item.get("field"), f"{path}.field", fields)
        if err or field_name is None:
            return None, err or f"{path}.field: 必须是非空字段名"
        if kind == "date_range" and not _is_date_type(fields[field_name]):
            return None, f"{path}.field: date_range 必须引用日期/时间字段"
        label = item.get("label")
        if label is not None and (not isinstance(label, str) or len(label) > 80):
            return None, f"{path}.label: 必须是长度 ≤80 的字符串"
        out.append({"id": filter_id, "kind": kind, "field": field_name, "label": label})
    return out, None


def _normalize_canvas(raw: dict[str, Any]) -> tuple[dict[str, int], str | None]:
    """校验 canvas；兼容 P0 表单写入的扁平 row_height/gap 键."""
    raw_canvas: Any = raw.get("canvas")
    if raw_canvas is None:
        raw_canvas = dict[str, Any]()
    if not isinstance(raw_canvas, dict):
        return {}, "canvas: 必须是对象"
    canvas: dict[str, int] = {}
    cols = raw_canvas.get("cols", CANVAS_COLS)
    if not _is_int(cols) or cols != CANVAS_COLS:
        return {}, "canvas.cols: P0 固定 12 列"
    canvas["cols"] = cols
    specs = (
        ("row_height", 40, 20, 80, "canvas.row_height"),
        ("gap", 12, 0, 32, "canvas.gap"),
        ("padding", 16, 0, 48, "canvas.padding"),
    )
    for key, default, low, high, path in specs:
        # canvas 优先；兼容现有 ViewOptionSchema 直接写顶层键的形态
        value = raw_canvas.get(key, raw.get(key, default))
        if not _is_int(value) or not (low <= value <= high):
            return {}, f"{path}: 必须是 {low}..{high} 的整数"
        canvas[key] = value
    return canvas, None


def _normalize_widget(
    raw: Any,
    index: int,
    fields: Mapping[str, str],
    seen_ids: set[str],
) -> tuple[dict[str, Any] | None, str | None]:
    """校验单个 widget 并裁剪未知键."""
    path = f"widgets[{index}]"
    if not isinstance(raw, dict):
        return None, f"{path}: 必须是对象"
    widget_id = raw.get("id")
    if not isinstance(widget_id, str) or not _ID_RE.fullmatch(widget_id):
        return None, f"{path}.id: 必须是 1..32 位字母数字/下划线/短横线"
    if widget_id in seen_ids:
        return None, f"{path}.id: 重复 ({widget_id})"
    seen_ids.add(widget_id)

    widget_type = raw.get("type")
    if widget_type not in WIDGET_TYPES:
        return None, f"{path}.type: 必须是 chart/kpi/table/text"

    layout = raw.get("layout")
    if not isinstance(layout, dict):
        return None, f"{path}.layout: 必须是对象"
    nums: dict[str, int] = {}
    for key in ("x", "y", "w", "h"):
        value = layout.get(key)
        if not _is_int(value):
            return None, f"{path}.layout.{key}: 必须是整数"
        nums[key] = cast(int, value)
    if not (1 <= nums["w"] <= CANVAS_COLS):
        return None, f"{path}.layout.w: 必须是 1..{CANVAS_COLS}"
    if not (1 <= nums["h"] <= MAX_WIDGET_H):
        return None, f"{path}.layout.h: 必须是 1..{MAX_WIDGET_H}"
    if not (0 <= nums["x"] <= CANVAS_COLS - nums["w"]):
        return None, f"{path}.layout.x: 必须是 0..{CANVAS_COLS - nums['w']}"
    if not (0 <= nums["y"] <= MAX_WIDGET_Y):
        return None, f"{path}.layout.y: 必须是 0..{MAX_WIDGET_Y}"

    title = raw.get("title")
    if title is not None and (not isinstance(title, str) or len(title) > 200):
        return None, f"{path}.title: 必须是长度 ≤200 的字符串"

    query, err = _normalize_query(raw.get("query"), f"{path}.query", fields)
    if err:
        return None, err

    widget: dict[str, Any] = {
        "id": widget_id,
        "type": widget_type,
        "title": title,
        "layout": nums,
        "query": query,
    }
    if widget_type == "chart":
        chart, err = _normalize_chart(raw.get("chart"), f"{path}.chart", fields)
        if err:
            return None, err
        widget["chart"] = chart
    elif widget_type == "kpi":
        kpi, err = _normalize_kpi(raw.get("kpi"), f"{path}.kpi", fields)
        if err:
            return None, err
        widget["kpi"] = kpi
    elif widget_type == "table":
        table, err = _normalize_table_widget(raw.get("table"), f"{path}.table", fields)
        if err:
            return None, err
        widget["table"] = table
    else:
        text = raw.get("text")
        content = text.get("content") if isinstance(text, dict) else None
        if not isinstance(content, str) or not content.strip() or len(content) > 20000:
            return None, f"{path}.text.content: 必须是长度 1..20000 的字符串"
        widget["text"] = {"content": content}

    display = raw.get("display")
    if display is not None:
        if not isinstance(display, dict):
            return None, f"{path}.display: 必须是对象"
        clean_display: dict[str, Any] = {}
        show_legend = display.get("show_legend")
        if show_legend is not None:
            if not isinstance(show_legend, bool):
                return None, f"{path}.display.show_legend: 必须是布尔值"
            clean_display["show_legend"] = show_legend
        palette = display.get("palette")
        if palette is not None:
            if not isinstance(palette, str) or len(palette) > 32:
                return None, f"{path}.display.palette: 必须是长度 ≤32 的字符串"
            clean_display["palette"] = palette
        thresholds = display.get("thresholds")
        if thresholds is not None:
            if not isinstance(thresholds, list):
                return None, f"{path}.display.thresholds: 必须是数组"
            if len(thresholds) > MAX_THRESHOLDS:
                return None, f"{path}.display.thresholds: 最多 {MAX_THRESHOLDS} 项"
            clean_thresholds: list[dict[str, Any]] = []
            for i, item in enumerate(thresholds):
                t_path = f"{path}.display.thresholds[{i}]"
                if not isinstance(item, dict):
                    return None, f"{t_path}: 必须是对象"
                value = item.get("value")
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return None, f"{t_path}.value: 必须是数值"
                color = item.get("color")
                if not isinstance(color, str) or not color or len(color) > 32:
                    return None, f"{t_path}.color: 必须是长度 1..32 的字符串"
                clean_thresholds.append({"value": value, "color": color})
            clean_display["thresholds"] = clean_thresholds
        widget["display"] = clean_display
    return widget, None


def normalize_dashboard_config(
    raw: Any,
    fields: Mapping[str, str],
) -> tuple[dict[str, Any] | None, str | None]:
    """校验并归一 dashboard 配置.

    Args:
        raw: 视图 ``view_options`` 原始值（可能来自种子 / API / 旧配置）。
        fields: 表字段名 -> 字段类型（类型用 registry 原名或历史别名均可）。

    Returns:
        ``(归一配置, None)`` 或 ``(None, 错误详情)``；错误详情以
        ``widgets[i].xxx`` 形式定位，供 API ``detail`` 直接返回。
    """
    raw: Any = raw if raw is not None else {}
    if not isinstance(raw, dict):
        return None, "dashboard 配置必须是对象"

    version = raw.get("schema_version", 1)
    if not _is_int(version) or version != 1:
        return None, "schema_version: P0 仅支持 1"

    canvas, err = _normalize_canvas(raw)
    if err:
        return None, err

    raw_widgets = raw.get("widgets", [])
    if not isinstance(raw_widgets, list):
        return None, "widgets: 必须是数组"
    if len(raw_widgets) > MAX_WIDGETS:
        return None, f"widgets: 最多 {MAX_WIDGETS} 个"

    widgets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_widgets):
        widget, err = _normalize_widget(item, index, fields, seen_ids)
        if err or widget is None:
            return None, err or f"widgets[{index}]: 未知错误"
        widgets.append(widget)

    global_filters, err = _normalize_global_filters(raw.get("global_filters"), fields)
    if err:
        return None, err

    settings_raw = raw.get("settings")
    settings: dict[str, Any] = {"refresh_interval": 0, "theme": "inherit"}
    if settings_raw is not None:
        if not isinstance(settings_raw, dict):
            return None, "settings: 必须是对象"
        refresh = settings_raw.get("refresh_interval", 0)
        if not _is_int(refresh) or not (0 <= refresh <= 3600):
            return None, "settings.refresh_interval: 必须是 0..3600 的整数"
        theme = settings_raw.get("theme", "inherit")
        if theme not in ("inherit", "light", "dark"):
            return None, "settings.theme: 必须是 inherit/light/dark"
        settings = {"refresh_interval": refresh, "theme": theme}

    return {
        "schema_version": 1,
        "canvas": canvas,
        "widgets": widgets,
        "global_filters": global_filters,
        "settings": settings,
    }, None
