"""图表模板注册表（ADR 0048 D3）：类别 → 模板两级，代码内置唯一真相源.

- 类别 / 模板只在本模块登记一次；接口、设计器 schema、渲染分派全部读注册表；
- 用户自定义 = ``documents_chart`` 实例行（``template_key + config``），不开放自建模板；
- ``normalize_config`` 宽松归一（缺键回退默认、未知键忽略，I6），``validate_config``
  供保存前的严格校验（结构性错误返回 400）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cndb.core.errors import BadRequestError

# ── 主题令牌（对齐参考 HTML 的纸质报表配色） ──

DEFAULT_PAPER = "#FBFAF5"
#: 三模板共用默认调色板（红 #8E2318 / 藏蓝 #1E3D57 / 橄榄 #5F6B4E）
DEFAULT_PALETTE = ["#8E2318", "#1E3D57", "#5F6B4E"]
#: bar-line-dual-axis：柱（实际 / 测算）与折线
DUAL_AXIS_PALETTE = ["#8E2318", "#5C7283", "#5F6B4E"]
#: grouped-bar-horizontal：现状（浅米）/ 目标（红）
GROUPED_PALETTE = ["#E9E4D6", "#8E2318"]

_HEX_RE = "^#[0-9A-Fa-f]{6}$"

# ── caption / labels 的默认文案 ──

_DEFAULT_CAPTION: dict[str, str] = {
    "no": "",
    "context": "",
    "title": "未命名图表",
    "subtitle": "",
    "note": "",
}

# ── 数据 schema 描述（前端设计器按此生成数据表） ──

_DUAL_AXIS_COLUMNS = [
    {"key": "label", "type": "text", "label": "年份"},
    {"key": "value", "type": "number", "label": "主值（左轴）", "required": True},
    {"key": "growth", "type": "number", "label": "次值（右轴，留空按主值推算）"},
]

_SERIES_COLUMNS_TPL = {"key": "values", "type": "number[]", "label": "系列值", "required": True}


@dataclass(frozen=True)
class ChartCategory:
    """图表类别（一级；二级分类带 parent 指向一级）：只读登记."""

    key: str
    name: str
    description: str
    #: 二级分类所属一级 key；None = 一级分类
    parent: str | None = None


@dataclass(frozen=True)
class ChartTemplate:
    """图表模板（二级）：schema + 默认配置 + 渲染指纹."""

    key: str
    category: str
    name: str
    description: str
    #: 数据 schema：行数上下限、行结构、系列数（设计器与校验共用）
    row_min: int
    row_max: int
    row_columns: tuple[dict[str, Any], ...]
    series_min: int = 0  # 0 = 无系列维度（行内带固定列）
    series_max: int = 0
    #: 保存前需要用户填写的文案键（labels）
    label_fields: tuple[dict[str, str], ...] = field(default=())
    default_config: dict[str, Any] = field(default_factory=dict)
    #: 模板代码指纹：布局 / schema 变更时递增，驱动 ETag 失效（D10）
    version: int = 1


CHART_CATEGORIES: tuple[ChartCategory, ...] = (
    ChartCategory("composition", "结构构成", "整体中各部分的构成与变化"),
    ChartCategory("comparison", "目标对比", "现状与规划目标的逐项对比"),
    ChartCategory("comparison-bar", "对比-柱形", "柱形类对比图", parent="comparison"),
    ChartCategory("comparison-bar-h", "对比-条形", "条形类对比图", parent="comparison"),
)

CHART_TEMPLATES: dict[str, ChartTemplate] = {
    tpl.key: tpl
    for tpl in (
        ChartTemplate(
            key="bar-line-dual-axis",
            category="comparison-bar",
            name="双轴柱线组合图",
            description="柱（左轴主值，实际 / 测算两色）+ 折线（右轴次值），含规划期分界带与图注增速联动",
            row_min=2,
            row_max=24,
            row_columns=tuple(_DUAL_AXIS_COLUMNS),  # type: ignore[arg-type]
            label_fields=(
                {"key": "legendActual", "label": "图例 · 主值（实际）"},
                {"key": "legendProjected", "label": "图例 · 主值（测算）"},
                {"key": "legendGrowth", "label": "图例 · 次值"},
                {"key": "bandLabel", "label": "图内标注 · 规划期"},
                {"key": "capActual", "label": "轴下说明 · 实际区间"},
                {"key": "capProjected", "label": "轴下说明 · 测算区间"},
                {"key": "unitLeft", "label": "左轴单位"},
                {"key": "unitRight", "label": "右轴单位"},
            ),
            default_config={
                "caption": {
                    "no": "图 2-1",
                    "context": "",
                    "title": "产业营业收入与增速（2020—2030年）",
                    "subtitle": "单位：亿元、%　｜　2026—2030年为规划情景测算值",
                    "note": (
                        "注：2020—2025年为统计口径实际值；2026—2030年为规划情景测算值，"
                        "2026—2030年营业收入年均增速{cagr}。\n数据来源：市统计局。"
                    ),
                },
                "labels": {
                    "legendActual": "营业收入（实际值）",
                    "legendProjected": "营业收入（测算值）",
                    "legendGrowth": "同比增速",
                    "bandLabel": "规划期（测算值）",
                    "capActual": "实际值（统计口径）",
                    "capProjected": "规划测算值",
                    "unitLeft": "亿元",
                    "unitRight": "%",
                },
                "theme": {"palette": DUAL_AXIS_PALETTE, "paper": DEFAULT_PAPER},
                "data": {
                    "actualCount": 6,
                    "rows": [
                        {"label": "2020", "value": 132, "growth": None},
                        {"label": "2021", "value": 158, "growth": None},
                        {"label": "2022", "value": 186, "growth": None},
                        {"label": "2023", "value": 218, "growth": None},
                        {"label": "2024", "value": 250, "growth": None},
                        {"label": "2025", "value": 285, "growth": None},
                        {"label": "2026", "value": 318, "growth": None},
                        {"label": "2027", "value": 358, "growth": None},
                        {"label": "2028", "value": 405, "growth": None},
                        {"label": "2029", "value": 458, "growth": None},
                        {"label": "2030", "value": 520, "growth": None},
                    ],
                },
            },
            version=7,
        ),
        ChartTemplate(
            key="stacked-bar-horizontal",
            category="comparison-bar-h",
            name="水平堆叠条形图",
            description="行 × 系列堆叠的水平条形，宽段内置白字、窄段外置标签，行尾自动合计",
            row_min=1,
            row_max=12,
            row_columns=({"key": "label", "type": "text", "label": "行"}, _SERIES_COLUMNS_TPL),
            series_min=1,
            series_max=6,
            label_fields=(),
            default_config={
                "caption": {
                    "no": "图 3-1",
                    "context": "",
                    "title": "产业营业收入结构变化（2025年与2030年）",
                    "subtitle": "单位：亿元　｜　2025年为实际值，2030年为规划目标",
                    "note": "注：服务类业务包括充换电、电池租赁与检测、回收利用、汽车金融与后市场。\n数据来源：本规划测算。",
                },
                "labels": {"series": ["整车", "零部件", "服务"], "unitX": "亿元"},
                "theme": {"palette": DEFAULT_PALETTE, "paper": DEFAULT_PAPER},
                "data": {
                    "rows": [
                        {"label": "2025年", "values": [1250, 480, 120]},
                        {"label": "2030年", "values": [2040, 800, 360]},
                    ]
                },
            },
            version=1,
        ),
        ChartTemplate(
            key="grouped-bar-horizontal",
            category="comparison-bar-h",
            name="水平分组条形图",
            description="类别 × 两系列（现状 / 目标）成组水平条，组内双条数值标签，横轴上限自动扩展",
            row_min=1,
            row_max=14,
            row_columns=({"key": "label", "type": "text", "label": "类别"}, _SERIES_COLUMNS_TPL),
            series_min=2,
            series_max=2,
            label_fields=(),
            default_config={
                "caption": {
                    "no": "图 4-1",
                    "context": "",
                    "title": "关键环节本地配套率现状与2030年目标",
                    "subtitle": "单位：%　｜　现状为2025年调研值",
                    "note": "注：本地配套率 = 本地企业配套产值 / 该环节总需求产值。\n数据来源：产业底册调研。",
                },
                "labels": {"series": ["2025年现状", "2030年目标"], "unitX": "%"},
                "theme": {"palette": GROUPED_PALETTE, "paper": DEFAULT_PAPER},
                "data": {
                    "rows": [
                        {"label": "隔膜", "values": [0, 35]},
                        {"label": "车规芯片", "values": [8, 25]},
                        {"label": "正极材料", "values": [20, 45]},
                        {"label": "一体化压铸", "values": [35, 60]},
                        {"label": "汽车电子", "values": [45, 65]},
                        {"label": "电机电控", "values": [68, 85]},
                        {"label": "电芯", "values": [75, 88]},
                    ]
                },
            },
            version=1,
        ),
    )
}

#: 渲染器全局指纹：管线代码变更时递增，参与 ETag（D10）
RENDERER_VERSION = 1


def get_template(template_key: str) -> ChartTemplate | None:
    """按 key 取模板；不存在（含已下线）返回 None."""
    return CHART_TEMPLATES.get(template_key)


def get_category(category_key: str) -> ChartCategory | None:
    """按 key 取类别."""
    for cat in CHART_CATEGORIES:
        if cat.key == category_key:
            return cat
    return None


def template_fingerprint(template_key: str) -> str:
    """模板指纹（ETag 成分）：未知模板给占位指纹，实例仍可 ETag 缓存降级图."""
    tpl = get_template(template_key)
    ver = tpl.version if tpl is not None else 0
    return f"{template_key}@{ver}+r{RENDERER_VERSION}"


# ── config 归一与校验 ──


def _coerce_str(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_str_dict(raw: Any, defaults: dict[str, str]) -> dict[str, str]:
    """字符串字典归一：非 dict 丢弃回默认；未知键忽略；缺键回默认."""
    out = dict(defaults)
    if isinstance(raw, dict):
        for key, value in defaults.items():
            if key in raw:
                out[key] = _coerce_str(raw[key], value)
    return out


def _coerce_number(value: Any) -> float | None:
    """数值归一：数字直接用；纯数字字符串转换；其余 None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_palette(raw: Any, fallback: list[str]) -> list[str]:
    """调色板归一：非法项丢弃；全非法回模板默认."""
    palette: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and len(item) == 7 and item.startswith("#"):
                try:
                    int(item[1:], 16)
                except ValueError:
                    continue
                palette.append(item)
    return palette or list(fallback)


def _normalize_theme(template: ChartTemplate, raw: Any) -> dict[str, Any]:
    theme = raw if isinstance(raw, dict) else {}
    default_palette = list((template.default_config.get("theme") or {}).get("palette") or DEFAULT_PALETTE)
    palette = _coerce_palette(theme.get("palette"), default_palette)
    paper = theme.get("paper")
    if not (isinstance(paper, str) and len(paper) == 7 and paper.startswith("#")):
        paper = DEFAULT_PAPER
    return {"palette": palette, "paper": paper}


def _normalize_rows_dual_axis(raw_rows: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(raw_rows, list):
        return rows
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "label": _coerce_str(row.get("label"), ""),
                "value": _coerce_number(row.get("value")),
                "growth": _coerce_number(row.get("growth")),
            }
        )
    return rows


def _normalize_rows_series(raw_rows: Any, series_count: int) -> list[dict[str, Any]]:
    """堆叠 / 分组模板的行归一：values 截断 / 补零到系列数."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw_rows, list):
        return rows
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        raw_values = row.get("values")
        values: list[float | None] = []
        if isinstance(raw_values, list):
            for item in raw_values[:series_count]:
                values.append(_coerce_number(item))
        while len(values) < series_count:
            values.append(None)
        rows.append({"label": _coerce_str(row.get("label"), ""), "values": values})
    return rows


def _labels_for(template: ChartTemplate, raw: Any) -> dict[str, Any]:
    """labels 归一：按模板声明回退默认；未知键忽略."""
    defaults: dict[str, Any] = {}
    if template.key == "bar-line-dual-axis":
        defaults = {
            "legendActual": "主值（实际）",
            "legendProjected": "主值（测算）",
            "legendGrowth": "次值",
            "bandLabel": "规划期",
            "capActual": "实际值",
            "capProjected": "规划测算值",
            "unitLeft": "",
            "unitRight": "",
        }
        out = _coerce_str_dict(raw, defaults)
    else:
        raw_dict = raw if isinstance(raw, dict) else {}
        series = raw_dict.get("series")
        count = (
            template.series_max
            if template.series_max and template.series_min != template.series_max
            else (template.series_max or 3)
        )
        default_series = [f"系列{i + 1}" for i in range(count)]
        names: list[str] = []
        if isinstance(series, list):
            for item in series[: max(template.series_max, count)]:
                names.append(_coerce_str(item, ""))
        while len(names) < count:
            names.append(default_series[len(names)])
        out = {"series": names, "unitX": _coerce_str(raw_dict.get("unitX"), "")}
    return out


def _effective_series_count(template: ChartTemplate, data: dict[str, Any]) -> int:
    """堆叠 / 分组模板的有效系列数：以 rows 首行长度为准（已归一到 series_max 内）."""
    rows = data.get("rows") or []
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        values = rows[0].get("values")
        if isinstance(values, list) and values:
            return max(template.series_min, min(len(values), template.series_max))
    return template.series_max or template.series_min


def normalize_config(template_key: str, config: Any) -> dict[str, Any]:
    """config 宽松归一（渲染路径，永不抛错，I6）：缺键回默认、坏值回退、未知键忽略."""
    template = get_template(template_key)
    if template is None:
        return {}
    raw = config if isinstance(config, dict) else {}
    caption = _coerce_str_dict(raw.get("caption"), _DEFAULT_CAPTION)
    labels = _labels_for(template, raw.get("labels"))
    theme = _normalize_theme(template, raw.get("theme"))
    raw_data = raw.get("data") if isinstance(raw.get("data"), dict) else {}

    if template.key == "bar-line-dual-axis":
        data: dict[str, Any] = {
            "rows": _normalize_rows_dual_axis(raw_data.get("rows")),
            "actualCount": template.default_config["data"]["actualCount"],
        }
        actual_count = _coerce_number(raw_data.get("actualCount"))
        if actual_count is not None:
            data["actualCount"] = int(max(1, min(actual_count, max(len(data["rows"]), 1))))
    else:
        series_count = _effective_series_count(template, raw_data)
        data = {"rows": _normalize_rows_series(raw_data.get("rows"), series_count)}

    return {"caption": caption, "labels": labels, "theme": theme, "data": data}


def validate_config(template_key: str, config: Any) -> list[str]:
    """保存前严格校验：结构性错误列表（空 = 通过）；渲染不受影响（I6）."""
    template = get_template(template_key)
    if template is None:
        return [f"模板 {template_key} 不存在或已下线"]
    if not isinstance(config, dict):
        return ["config 必须是对象"]

    errors: list[str] = []
    data = config.get("data")
    if not isinstance(data, dict):
        return ["data 必须是对象"]

    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        return ["data.rows 必须是非空数组"]
    if not (template.row_min <= len(rows) <= template.row_max):
        errors.append(f"行数须在 {template.row_min}–{template.row_max} 之间（当前 {len(rows)}）")

    if template.key == "bar-line-dual-axis":
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"第 {i + 1} 行必须是对象")
                continue
            if not _coerce_str(row.get("label"), "").strip():
                errors.append(f"第 {i + 1} 行缺少行标签")
            if _coerce_number(row.get("value")) is None:
                errors.append(f"第 {i + 1} 行主值必须是数字")
            growth = row.get("growth")
            if growth is not None and _coerce_number(growth) is None:
                errors.append(f"第 {i + 1} 行次值必须是数字或留空")
            elif i == 0 and _coerce_number(growth) is not None:
                errors.append("第 1 行次值不能填写（无上年基数）")
        raw_count = data.get("actualCount")
        count = template.default_config["data"]["actualCount"] if raw_count is None else _coerce_number(raw_count)
        if count is None or not (1 <= count <= len(rows)):
            errors.append("actualCount（实际值年份数）须在 1 至行数之间")
    else:
        series_count: int | None = None
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"第 {i + 1} 行必须是对象")
                continue
            if not _coerce_str(row.get("label"), "").strip():
                errors.append(f"第 {i + 1} 行缺少行标签")
            values = row.get("values")
            if not isinstance(values, list) or not values:
                errors.append(f"第 {i + 1} 行系列值必须是非空数组")
                continue
            if series_count is None:
                series_count = len(values)
            elif len(values) != series_count:
                errors.append(f"第 {i + 1} 行系列数（{len(values)}）与其他行不一致（{series_count}）")
            for j, item in enumerate(values):
                if _coerce_number(item) is None:
                    errors.append(f"第 {i + 1} 行第 {j + 1} 个系列值必须是数字")
        if series_count is not None and not (template.series_min <= series_count <= template.series_max):
            errors.append(f"系列数须在 {template.series_min}–{template.series_max} 之间（当前 {series_count}）")

    return errors


def require_valid_config(template_key: str, config: Any) -> dict[str, Any]:
    """校验失败抛 400（建 / 改实例走此入口）；成功返回归一后的 config."""
    errors = validate_config(template_key, config)
    if errors:
        raise BadRequestError("；".join(errors[:5]), code="chart_config_invalid")
    return normalize_config(template_key, config)


def templates_payload() -> dict[str, Any]:
    """`GET /charts/templates` 的载荷：一级分类含 children 二级，模板扁平数组.

    空分类不输出（一级下自身与二级均无模板、或二级无模板）。
    """
    top_level = [c for c in CHART_CATEGORIES if c.parent is None]
    children = [c for c in CHART_CATEGORIES if c.parent is not None]

    def child_entry(cat: ChartCategory) -> dict[str, Any] | None:
        if not any(t.category == cat.key for t in CHART_TEMPLATES.values()):
            return None
        return {"key": cat.key, "name": cat.name, "description": cat.description, "parent": cat.parent}

    category_entries: list[dict[str, Any]] = []
    for cat in top_level:
        children_entries = [e for e in (child_entry(c) for c in children if c.parent == cat.key) if e is not None]
        has_direct = any(t.category == cat.key for t in CHART_TEMPLATES.values())
        if not has_direct and not children_entries:
            continue
        entry: dict[str, Any] = {"key": cat.key, "name": cat.name, "description": cat.description}
        if children_entries:
            entry["children"] = children_entries
        category_entries.append(entry)

    return {
        "categories": category_entries,
        "templates": [
            {
                "key": t.key,
                "category": t.category,
                "name": t.name,
                "description": t.description,
                "row_min": t.row_min,
                "row_max": t.row_max,
                "row_columns": list(t.row_columns),
                "series_min": t.series_min,
                "series_max": t.series_max,
                "label_fields": [dict(f) for f in t.label_fields],
                "default_config": t.default_config,
            }
            for t in CHART_TEMPLATES.values()
        ],
    }


__all__ = [
    "CHART_CATEGORIES",
    "CHART_TEMPLATES",
    "DEFAULT_PALETTE",
    "DEFAULT_PAPER",
    "DUAL_AXIS_PALETTE",
    "GROUPED_PALETTE",
    "ChartCategory",
    "ChartTemplate",
    "get_category",
    "get_template",
    "normalize_config",
    "require_valid_config",
    "template_fingerprint",
    "templates_payload",
    "validate_config",
]
