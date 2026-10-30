"""图表模板注册表（ADR 0048 D3）：类别 → 模板两级，代码内置唯一真相源.

- 类别 / 模板只在本模块登记一次；接口、设计器 schema、渲染分派全部读注册表；
- 用户自定义 = ``documents_chart`` 实例行（``template_key + config``），不开放自建模板；
- ``normalize_config`` 宽松归一（缺键回退默认、未知键忽略，I6），``validate_config``
  供保存前的严格校验（结构性错误返回 400）。
"""

from __future__ import annotations

import copy
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
    #: 行结构类型（归一 / 校验 / 设计器分派，需求卡片 0070）：
    #: dual-axis（label+value+growth）| series（label+values[]）
    #: | value（label+value）| xy（x+y）
    row_kind: str = "series"
    #: labels 归一按 default_config 声明回退（标准类型模板）；旧模板走兼容分支
    labels_from_default: bool = False
    #: 保存前需要用户填写的文案键（labels）
    label_fields: tuple[dict[str, str], ...] = field(default=())
    #: 样式开关声明（设计器按此生成样式表单，需求卡片 0070 C3）
    style_fields: tuple[dict[str, Any], ...] = field(default=())
    default_config: dict[str, Any] = field(default_factory=dict)
    #: 模板代码指纹：布局 / schema 变更时递增，驱动 ETag 失效（D10）
    version: int = 1


CHART_CATEGORIES: tuple[ChartCategory, ...] = (
    ChartCategory("composition", "结构构成", "整体中各部分的构成与变化"),
    ChartCategory("comparison", "对比", "现状与目标的逐项对比"),
    ChartCategory("comparison-bar", "对比-柱形", "柱形类对比图", parent="comparison"),
    ChartCategory("comparison-bar-h", "对比-条形", "条形类对比图", parent="comparison"),
    # ── 标准类型分类（需求卡片 0070 C1/C2）──
    ChartCategory("trend", "趋势分析", "指标随时间或顺序的变化走势"),
    ChartCategory("trend-line", "趋势-折线", "多系列折线走势图", parent="trend"),
    ChartCategory("trend-area", "趋势-面积", "面积 / 堆叠面积走势图", parent="trend"),
    ChartCategory("composition-pie", "构成-饼图", "饼图 / 环形占比图", parent="composition"),
    ChartCategory("composition-treemap", "构成-树状图", "矩形树图面积占比", parent="composition"),
    ChartCategory("composition-funnel", "构成-漏斗", "阶段转化漏斗", parent="composition"),
    ChartCategory("distribution", "分布关联", "数值分布与两变量关联"),
    ChartCategory("distribution-scatter", "分布-散点", "两变量散点关联（可选趋势线）", parent="distribution"),
    ChartCategory("distribution-heatmap", "分布-热力", "行列矩阵热力图", parent="distribution"),
    ChartCategory("evaluation", "综合评价", "多维能力与目标达成评价"),
    ChartCategory("evaluation-radar", "评价-雷达", "多维雷达能力图", parent="evaluation"),
    ChartCategory("evaluation-gauge", "评价-仪表盘", "单指标达成仪表盘", parent="evaluation"),
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
            row_kind="dual-axis",
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
            version=9,
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

# ── 标准类型预设模板（需求卡片 0070 C1/C2）──

#: 预设调色板：商务蓝（汇报演示）/ 经典纸面（正式报告）/ 明快数据（分析与总结）
PALETTE_BUSINESS = ["#1E3D57", "#5C7283", "#8FA3B8", "#7C9A8C", "#B98A2F", "#6B4A7A"]
PALETTE_CLASSIC = ["#8E2318", "#1E3D57", "#5F6B4E", "#B98A2F", "#6B4A7A", "#3F7E8C"]
PALETTE_VIVID = ["#4E79A7", "#F28E2B", "#59A14F", "#E15759", "#76B7B2", "#EDC948"]
PAPER_BUSINESS = "#F6F8FA"
PAPER_CLASSIC = "#FBFAF5"
PAPER_VIVID = "#FFFFFF"

#: value 行结构（label + value）：饼图 / 漏斗 / 仪表盘 / 树状图
_VALUE_COLUMNS = (
    {"key": "label", "type": "text", "label": "名称"},
    {"key": "value", "type": "number", "label": "数值", "required": True},
)
#: xy 行结构：散点图
_XY_COLUMNS = (
    {"key": "x", "type": "number", "label": "横轴值", "required": True},
    {"key": "y", "type": "number", "label": "纵轴值", "required": True},
)


def _add_type(
    out: dict[str, ChartTemplate],
    *,
    type_key: str,
    category: str,
    caption: dict[str, str],
    labels: dict[str, Any],
    rows: list[dict[str, Any]],
    row_kind: str,
    row_min: int,
    row_max: int,
    row_columns: tuple[dict[str, Any], ...],
    series_min: int = 0,
    series_max: int = 0,
    label_fields: tuple[dict[str, str], ...] = (),
    style_fields: tuple[dict[str, Any], ...] = (),
    presets: tuple[dict[str, Any], ...],
) -> None:
    """按类型 schema × 预设（配色 / 纸底 / 样式）生成模板条目，登记进 ``out``.

    预设共享布局函数与示例数据（``layouts`` 按 key 分派），差异全部落在
    default_config（需求卡片 0070「口径」：预设 = 注册表条目，不引入嵌套概念）。
    """
    for preset in presets:
        key = f"{type_key}-{preset['suffix']}"
        default_config: dict[str, Any] = {
            "caption": dict(caption),
            "labels": copy.deepcopy(labels),
            "theme": {"palette": list(preset["palette"]), "paper": preset["paper"]},
            "data": {"rows": copy.deepcopy(rows)},
        }
        if preset.get("style"):
            default_config["style"] = dict(preset["style"])
        out[key] = ChartTemplate(
            key=key,
            category=category,
            name=preset["name"],
            description=preset["description"],
            row_min=row_min,
            row_max=row_max,
            row_columns=row_columns,
            series_min=series_min,
            series_max=series_max,
            row_kind=row_kind,
            labels_from_default=True,
            label_fields=label_fields,
            style_fields=style_fields,
            default_config=default_config,
            version=1,
        )


def _standard_type_templates() -> dict[str, ChartTemplate]:
    """10 类标准图表 × 3 套预设（需求卡片 0070 C1/C2）."""
    out: dict[str, ChartTemplate] = {}
    _add_type(
        out,
        type_key="line",
        category="trend-line",
        caption={
            "no": "图 5-1",
            "context": "",
            "title": "新能源汽车产量走势（2021—2026年）",
            "subtitle": "单位：万辆　｜　数据来源：示例数据",
            "note": "注：2026年为行业预测值。\n数据来源：公开统计数据整理。",
        },
        labels={"series": ["纯电动", "插电混动", "燃料电池"], "unitY": "万辆"},
        rows=[
            {"label": "2021", "values": [279, 60, 0.2]},
            {"label": "2022", "values": [411, 102, 0.3]},
            {"label": "2023", "values": [568, 158, 0.6]},
            {"label": "2024", "values": [689, 228, 1.0]},
            {"label": "2025", "values": [762, 310, 1.6]},
            {"label": "2026", "values": [820, 395, 2.4]},
        ],
        row_kind="series",
        row_min=2,
        row_max=24,
        row_columns=({"key": "label", "type": "text", "label": "横轴"}, _SERIES_COLUMNS_TPL),
        series_min=1,
        series_max=6,
        label_fields=({"key": "unitY", "label": "纵轴单位"},),
        style_fields=(
            {"key": "showMarkers", "label": "显示数据点"},
            {"key": "showValues", "label": "显示数值标签"},
        ),
        presets=(
            {
                "suffix": "business",
                "name": "折线图 · 商务蓝",
                "description": "多系列折线走势，藏蓝商务配色，适配汇报演示场景",
                "palette": PALETTE_BUSINESS,
                "paper": PAPER_BUSINESS,
                "style": {"showMarkers": True, "showValues": False},
            },
            {
                "suffix": "classic",
                "name": "折线图 · 经典纸面",
                "description": "多系列折线走势，经典红蓝纸面配色，适配正式报告文档",
                "palette": PALETTE_CLASSIC,
                "paper": PAPER_CLASSIC,
                "style": {"showMarkers": True, "showValues": False},
            },
            {
                "suffix": "vivid",
                "name": "折线图 · 明快数据",
                "description": "多系列折线走势并带数值标签，明快配色，适配数据分析与项目总结",
                "palette": PALETTE_VIVID,
                "paper": PAPER_VIVID,
                "style": {"showMarkers": True, "showValues": True},
            },
        ),
    )
    _add_type(
        out,
        type_key="area",
        category="trend-area",
        caption={
            "no": "图 5-2",
            "context": "",
            "title": "软件业务收入构成（2021—2026年）",
            "subtitle": "单位：亿元　｜　信息技术服务占比持续提升",
            "note": "注：收入构成按业务大类划分。\n数据来源：示例数据。",
        },
        labels={"series": ["软件产品", "信息技术服务", "信息安全", "嵌入式系统"], "unitY": "亿元"},
        rows=[
            {"label": "2021", "values": [2055, 5517, 310, 760]},
            {"label": "2022", "values": [2402, 6335, 380, 820]},
            {"label": "2023", "values": [2700, 7230, 450, 900]},
            {"label": "2024", "values": [2950, 8200, 520, 980]},
            {"label": "2025", "values": [3180, 9150, 600, 1060]},
            {"label": "2026", "values": [3400, 10100, 680, 1150]},
        ],
        row_kind="series",
        row_min=2,
        row_max=24,
        row_columns=({"key": "label", "type": "text", "label": "横轴"}, _SERIES_COLUMNS_TPL),
        series_min=1,
        series_max=6,
        label_fields=({"key": "unitY", "label": "纵轴单位"},),
        style_fields=(
            {"key": "stacked", "label": "堆叠面积"},
            {"key": "showValues", "label": "显示数值标签"},
        ),
        presets=(
            {
                "suffix": "business",
                "name": "面积图 · 商务蓝",
                "description": "半透明填充面积走势，藏蓝商务配色，适配汇报演示场景",
                "palette": PALETTE_BUSINESS,
                "paper": PAPER_BUSINESS,
                "style": {"stacked": False, "showValues": False},
            },
            {
                "suffix": "classic",
                "name": "面积图 · 经典纸面",
                "description": "半透明填充面积走势，经典红蓝纸面配色，适配正式报告文档",
                "palette": PALETTE_CLASSIC,
                "paper": PAPER_CLASSIC,
                "style": {"stacked": False, "showValues": False},
            },
            {
                "suffix": "stacked",
                "name": "面积图 · 堆叠强调",
                "description": "堆叠面积呈现构成变化，明快配色，适配数据分析与项目总结",
                "palette": PALETTE_VIVID,
                "paper": PAPER_VIVID,
                "style": {"stacked": True, "showValues": False},
            },
        ),
    )
    _add_type(
        out,
        type_key="bar",
        category="comparison-bar",
        caption={
            "no": "图 5-3",
            "context": "",
            "title": "各区招商项目落地数（2024年与2025年）",
            "subtitle": "单位：个　｜　2025年为全年快报数",
            "note": "注：统计口径为当年新签约并落地项目。\n数据来源：区招商局。",
        },
        labels={"series": ["2024年", "2025年"], "unitY": "个"},
        rows=[
            {"label": "高新区", "values": [42, 56]},
            {"label": "经开区", "values": [35, 48]},
            {"label": "临港新城", "values": [28, 39]},
            {"label": "科创走廊", "values": [22, 31]},
            {"label": "老城片区", "values": [15, 20]},
            {"label": "生态园区", "values": [10, 16]},
        ],
        row_kind="series",
        row_min=2,
        row_max=20,
        row_columns=({"key": "label", "type": "text", "label": "类别"}, _SERIES_COLUMNS_TPL),
        series_min=1,
        series_max=6,
        label_fields=({"key": "unitY", "label": "纵轴单位"},),
        style_fields=(
            {"key": "stacked", "label": "堆叠柱形"},
            {"key": "showValues", "label": "显示数值标签"},
        ),
        presets=(
            {
                "suffix": "business",
                "name": "柱状图 · 商务蓝",
                "description": "纵向分组柱形对比，藏蓝商务配色，适配汇报演示场景",
                "palette": PALETTE_BUSINESS,
                "paper": PAPER_BUSINESS,
                "style": {"stacked": False, "showValues": False},
            },
            {
                "suffix": "classic",
                "name": "柱状图 · 经典纸面",
                "description": "纵向分组柱形对比，经典红蓝纸面配色，适配正式报告文档",
                "palette": PALETTE_CLASSIC,
                "paper": PAPER_CLASSIC,
                "style": {"stacked": False, "showValues": False},
            },
            {
                "suffix": "stacked",
                "name": "柱状图 · 堆叠强调",
                "description": "堆叠柱形并带合计标签，明快配色，适配数据分析与项目总结",
                "palette": PALETTE_VIVID,
                "paper": PAPER_VIVID,
                "style": {"stacked": True, "showValues": True},
            },
        ),
    )
    _add_type(
        out,
        type_key="pie",
        category="composition-pie",
        caption={
            "no": "图 5-4",
            "context": "",
            "title": "产业营业收入构成（2025年）",
            "subtitle": "单位：亿元　｜　占比按营收口径计算",
            "note": "注：服务类业务包括充换电、电池租赁与检测、回收利用。\n数据来源：示例数据。",
        },
        labels={},
        rows=[
            {"label": "整车制造", "value": 1250},
            {"label": "零部件配套", "value": 480},
            {"label": "充换电服务", "value": 210},
            {"label": "电池租赁与检测", "value": 120},
            {"label": "回收利用", "value": 60},
        ],
        row_kind="value",
        row_min=2,
        row_max=12,
        row_columns=_VALUE_COLUMNS,
        label_fields=(),
        style_fields=(
            {"key": "donut", "label": "环形样式"},
            {"key": "showPercent", "label": "显示百分比"},
        ),
        presets=(
            {
                "suffix": "business",
                "name": "饼图 · 商务蓝",
                "description": "扇形占比 + 右侧图例清单，藏蓝商务配色，适配汇报演示场景",
                "palette": PALETTE_BUSINESS,
                "paper": PAPER_BUSINESS,
                "style": {"donut": False, "showPercent": True},
            },
            {
                "suffix": "classic",
                "name": "饼图 · 经典纸面",
                "description": "扇形占比 + 右侧图例清单，经典红蓝纸面配色，适配正式报告文档",
                "palette": PALETTE_CLASSIC,
                "paper": PAPER_CLASSIC,
                "style": {"donut": False, "showPercent": True},
            },
            {
                "suffix": "donut",
                "name": "环形图 · 明快数据",
                "description": "环形样式带中心合计读数，明快配色，适配数据分析与项目总结",
                "palette": PALETTE_VIVID,
                "paper": PAPER_VIVID,
                "style": {"donut": True, "showPercent": True},
            },
        ),
    )
    _add_type(
        out,
        type_key="scatter",
        category="distribution-scatter",
        caption={
            "no": "图 5-5",
            "context": "",
            "title": "研发投入与新产品收入关联分析",
            "subtitle": "单位：万元　｜　样本为12家重点企业",
            "note": "注：新产品收入为近三年立项产品累计收入。\n数据来源：企业调研。",
        },
        labels={"unitX": "研发投入（万元）", "unitY": "新产品收入（万元）"},
        rows=[
            {"x": 120, "y": 380},
            {"x": 180, "y": 520},
            {"x": 240, "y": 700},
            {"x": 300, "y": 860},
            {"x": 350, "y": 980},
            {"x": 420, "y": 1150},
            {"x": 480, "y": 1320},
            {"x": 560, "y": 1480},
            {"x": 640, "y": 1660},
            {"x": 720, "y": 1850},
            {"x": 800, "y": 2050},
            {"x": 880, "y": 2260},
        ],
        row_kind="xy",
        row_min=3,
        row_max=60,
        row_columns=_XY_COLUMNS,
        label_fields=(
            {"key": "unitX", "label": "横轴单位"},
            {"key": "unitY", "label": "纵轴单位"},
        ),
        style_fields=({"key": "showTrend", "label": "显示趋势参考线"},),
        presets=(
            {
                "suffix": "business",
                "name": "散点图 · 商务蓝",
                "description": "两变量散点关联，藏蓝商务配色，适配汇报演示场景",
                "palette": PALETTE_BUSINESS,
                "paper": PAPER_BUSINESS,
                "style": {"showTrend": False},
            },
            {
                "suffix": "classic",
                "name": "散点图 · 经典纸面",
                "description": "两变量散点关联，经典红蓝纸面配色，适配正式报告文档",
                "palette": PALETTE_CLASSIC,
                "paper": PAPER_CLASSIC,
                "style": {"showTrend": False},
            },
            {
                "suffix": "trend",
                "name": "散点图 · 趋势关联",
                "description": "散点 + 最小二乘趋势参考线，明快配色，适配数据分析与项目总结",
                "palette": PALETTE_VIVID,
                "paper": PAPER_VIVID,
                "style": {"showTrend": True},
            },
        ),
    )
    _add_type(
        out,
        type_key="radar",
        category="evaluation-radar",
        caption={
            "no": "图 5-6",
            "context": "",
            "title": "企业综合能力对标（百分制）",
            "subtitle": "对标行业标杆与行业均值",
            "note": "注：各维度得分经专家评议折算为百分制。\n数据来源：示例数据。",
        },
        labels={"series": ["本企业", "行业标杆", "行业均值"]},
        rows=[
            {"label": "研发投入", "values": [72, 90, 60]},
            {"label": "产能规模", "values": [85, 88, 70]},
            {"label": "渠道覆盖", "values": [60, 92, 62]},
            {"label": "服务能力", "values": [78, 90, 65]},
            {"label": "人才密度", "values": [66, 85, 58]},
            {"label": "数字化水平", "values": [80, 92, 63]},
        ],
        row_kind="series",
        row_min=3,
        row_max=10,
        row_columns=({"key": "label", "type": "text", "label": "维度"}, _SERIES_COLUMNS_TPL),
        series_min=1,
        series_max=4,
        style_fields=({"key": "fill", "label": "填充系列区域"},),
        presets=(
            {
                "suffix": "business",
                "name": "雷达图 · 商务蓝",
                "description": "多维能力雷达（区域填充），藏蓝商务配色，适配汇报演示场景",
                "palette": PALETTE_BUSINESS,
                "paper": PAPER_BUSINESS,
                "style": {"fill": True},
            },
            {
                "suffix": "classic",
                "name": "雷达图 · 经典纸面",
                "description": "多维能力雷达（仅描线），经典红蓝纸面配色，适配正式报告文档",
                "palette": PALETTE_CLASSIC,
                "paper": PAPER_CLASSIC,
                "style": {"fill": False},
            },
            {
                "suffix": "fill",
                "name": "雷达图 · 填充强调",
                "description": "多维能力雷达（区域填充强调），明快配色，适配数据分析与项目总结",
                "palette": PALETTE_VIVID,
                "paper": PAPER_VIVID,
                "style": {"fill": True},
            },
        ),
    )
    _add_type(
        out,
        type_key="funnel",
        category="composition-funnel",
        caption={
            "no": "图 5-7",
            "context": "",
            "title": "招商线索转化漏斗（2025年）",
            "subtitle": "单位：家　｜　签约转化率 8.0%",
            "note": "注：转化率 = 签约落地数 / 线索获取数。\n数据来源：招商系统。",
        },
        labels={},
        rows=[
            {"label": "线索获取", "value": 1200},
            {"label": "意向洽谈", "value": 640},
            {"label": "实地考察", "value": 320},
            {"label": "合同谈判", "value": 180},
            {"label": "签约落地", "value": 96},
        ],
        row_kind="value",
        row_min=3,
        row_max=8,
        row_columns=_VALUE_COLUMNS,
        style_fields=({"key": "showRates", "label": "显示阶段转化率"},),
        presets=(
            {
                "suffix": "business",
                "name": "漏斗图 · 商务蓝",
                "description": "居中递缩漏斗 + 阶段转化率，藏蓝商务配色，适配汇报演示场景",
                "palette": PALETTE_BUSINESS,
                "paper": PAPER_BUSINESS,
                "style": {"showRates": True},
            },
            {
                "suffix": "classic",
                "name": "漏斗图 · 经典纸面",
                "description": "居中递缩漏斗 + 阶段转化率，经典红蓝纸面配色，适配正式报告文档",
                "palette": PALETTE_CLASSIC,
                "paper": PAPER_CLASSIC,
                "style": {"showRates": True},
            },
            {
                "suffix": "vivid",
                "name": "漏斗图 · 明快数据",
                "description": "居中递缩漏斗 + 阶段转化率，明快配色，适配数据分析与项目总结",
                "palette": PALETTE_VIVID,
                "paper": PAPER_VIVID,
                "style": {"showRates": True},
            },
        ),
    )
    _add_type(
        out,
        type_key="gauge",
        category="evaluation-gauge",
        caption={
            "no": "图 5-8",
            "context": "",
            "title": "年度营收目标完成率",
            "subtitle": "截至2025年三季度末",
            "note": "注：完成率 = 累计营收 / 年度目标。\n数据来源：财务快报。",
        },
        labels={"max": "100", "unit": "%"},
        rows=[{"label": "年度营收目标完成率", "value": 76.5}],
        row_kind="value",
        row_min=1,
        row_max=1,
        row_columns=_VALUE_COLUMNS,
        label_fields=(
            {"key": "max", "label": "量程上限"},
            {"key": "unit", "label": "单位"},
        ),
        presets=(
            {
                "suffix": "business",
                "name": "仪表盘 · 商务蓝",
                "description": "单指标达成仪表盘（弧 + 指针 + 刻度），藏蓝商务配色，适配汇报演示场景",
                "palette": PALETTE_BUSINESS,
                "paper": PAPER_BUSINESS,
            },
            {
                "suffix": "classic",
                "name": "仪表盘 · 经典纸面",
                "description": "单指标达成仪表盘（弧 + 指针 + 刻度），经典红蓝纸面配色，适配正式报告文档",
                "palette": PALETTE_CLASSIC,
                "paper": PAPER_CLASSIC,
            },
            {
                "suffix": "vivid",
                "name": "仪表盘 · 明快数据",
                "description": "单指标达成仪表盘（弧 + 指针 + 刻度），明快配色，适配数据分析与项目总结",
                "palette": PALETTE_VIVID,
                "paper": PAPER_VIVID,
            },
        ),
    )
    _add_type(
        out,
        type_key="treemap",
        category="composition-treemap",
        caption={
            "no": "图 5-9",
            "context": "",
            "title": "产业营收结构（2025年）",
            "subtitle": "单位：亿元　｜　矩形面积按营收占比",
            "note": "注：口径与饼图一致，面积表示占比大小。\n数据来源：示例数据。",
        },
        labels={},
        rows=[
            {"label": "整车制造", "value": 1250},
            {"label": "零部件配套", "value": 480},
            {"label": "充换电服务", "value": 210},
            {"label": "汽车金融", "value": 150},
            {"label": "电池租赁与检测", "value": 120},
            {"label": "检测认证", "value": 85},
            {"label": "后市场服务", "value": 95},
            {"label": "回收利用", "value": 60},
        ],
        row_kind="value",
        row_min=3,
        row_max=24,
        row_columns=_VALUE_COLUMNS,
        style_fields=({"key": "showValues", "label": "显示数值与占比"},),
        presets=(
            {
                "suffix": "business",
                "name": "树状图 · 商务蓝",
                "description": "squarified 矩形树图（数值 + 占比），藏蓝商务配色，适配汇报演示场景",
                "palette": PALETTE_BUSINESS,
                "paper": PAPER_BUSINESS,
                "style": {"showValues": True},
            },
            {
                "suffix": "classic",
                "name": "树状图 · 经典纸面",
                "description": "squarified 矩形树图（数值 + 占比），经典红蓝纸面配色，适配正式报告文档",
                "palette": PALETTE_CLASSIC,
                "paper": PAPER_CLASSIC,
                "style": {"showValues": True},
            },
            {
                "suffix": "vivid",
                "name": "树状图 · 明快数据",
                "description": "squarified 矩形树图（仅占比），明快配色，适配数据分析与项目总结",
                "palette": PALETTE_VIVID,
                "paper": PAPER_VIVID,
                "style": {"showValues": False},
            },
        ),
    )
    _add_type(
        out,
        type_key="heatmap",
        category="distribution-heatmap",
        caption={
            "no": "图 5-10",
            "context": "",
            "title": "各部门季度目标达成率（2025年）",
            "subtitle": "单位：%　｜　颜色越深达成率越高",
            "note": "注：达成率 = 实际完成 / 季度目标。\n数据来源：绩效系统。",
        },
        labels={"series": ["一季度", "二季度", "三季度", "四季度"]},
        rows=[
            {"label": "研发部", "values": [82, 88, 91, 95]},
            {"label": "生产部", "values": [90, 86, 89, 93]},
            {"label": "市场部", "values": [70, 78, 85, 90]},
            {"label": "供应链", "values": [88, 92, 84, 89]},
            {"label": "客服部", "values": [75, 80, 83, 88]},
            {"label": "职能部门", "values": [85, 87, 90, 92]},
        ],
        row_kind="series",
        row_min=3,
        row_max=12,
        row_columns=({"key": "label", "type": "text", "label": "行"}, _SERIES_COLUMNS_TPL),
        series_min=3,
        series_max=10,
        presets=(
            {
                "suffix": "business",
                "name": "热力图 · 商务蓝",
                "description": "行列矩阵热力（色阶 + 数值），藏蓝商务配色，适配汇报演示场景",
                "palette": PALETTE_BUSINESS,
                "paper": PAPER_BUSINESS,
            },
            {
                "suffix": "classic",
                "name": "热力图 · 经典纸面",
                "description": "行列矩阵热力（色阶 + 数值），经典红蓝纸面配色，适配正式报告文档",
                "palette": PALETTE_CLASSIC,
                "paper": PAPER_CLASSIC,
            },
            {
                "suffix": "vivid",
                "name": "热力图 · 明快数据",
                "description": "行列矩阵热力（色阶 + 数值），明快配色，适配数据分析与项目总结",
                "palette": PALETTE_VIVID,
                "paper": PAPER_VIVID,
            },
        ),
    )
    return out


CHART_TEMPLATES.update(_standard_type_templates())

#: 渲染器全局指纹：管线代码变更时递增，参与 ETag（D10）
#: v2（需求卡片 0070）：标准类型布局 + path 填充写端 + 折线路径平移格式修复
#: （历史粘连形态导致 PNG 导出丢折线 / 扇形）
RENDERER_VERSION = 2


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
    """系列类模板的行归一：values 截断 / 补空到系列数."""
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


def _normalize_rows_value(raw_rows: Any) -> list[dict[str, Any]]:
    """value 行结构（label + value）归一：饼图 / 漏斗 / 仪表盘 / 树状图."""
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
            }
        )
    return rows


def _normalize_rows_xy(raw_rows: Any) -> list[dict[str, Any]]:
    """xy 行结构（x + y）归一：散点图."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw_rows, list):
        return rows
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        rows.append({"x": _coerce_number(row.get("x")), "y": _coerce_number(row.get("y"))})
    return rows


def _normalize_style(template: ChartTemplate, raw: Any) -> dict[str, Any] | None:
    """样式开关归一（需求卡片 0070 C3）：按 default_config.style 声明回退.

    无 style 节的模板（旧模板 / 无样式类型）返回 None，归一输出形状不变（C4）。
    """
    defaults = template.default_config.get("style")
    if not isinstance(defaults, dict):
        return None
    out = dict(defaults)
    if isinstance(raw, dict):
        for key, default_value in defaults.items():
            if key in raw:
                if isinstance(default_value, bool):
                    # 非布尔脏值回退默认（I6：坏值回退，不做 truthy 转换）
                    out[key] = raw[key] if isinstance(raw[key], bool) else default_value
                else:
                    out[key] = _coerce_str(raw[key], str(default_value))
    return out


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
    elif template.labels_from_default:
        # 标准类型（需求卡片 0070）：按 default_config.labels 声明逐键归一；
        # series 为系列名数组，长度即系列数（布局 / 设计器均以此为准）
        declared = template.default_config.get("labels") or {}
        raw_dict: dict[str, Any] = raw if isinstance(raw, dict) else {}
        out: dict[str, Any] = {}
        for key, default_value in declared.items():
            if isinstance(default_value, list):
                raw_list = raw_dict.get(key)
                if isinstance(raw_list, list):
                    names = [
                        _coerce_str(item, f"系列{i + 1}")
                        for i, item in enumerate(raw_list[: max(template.series_max, 1)])
                    ]
                else:
                    names = [_coerce_str(item, "") for item in default_value]
                while template.series_min and len(names) < template.series_min:
                    names.append(f"系列{len(names) + 1}")
                out[key] = names
            else:
                out[key] = _coerce_str(raw_dict.get(key), str(default_value))
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
    style = _normalize_style(template, raw.get("style"))
    raw_data = raw.get("data") if isinstance(raw.get("data"), dict) else {}

    if template.row_kind == "dual-axis":
        data: dict[str, Any] = {
            "rows": _normalize_rows_dual_axis(raw_data.get("rows")),
            "actualCount": template.default_config["data"]["actualCount"],
        }
        actual_count = _coerce_number(raw_data.get("actualCount"))
        if actual_count is not None:
            data["actualCount"] = int(max(1, min(actual_count, max(len(data["rows"]), 1))))
    elif template.row_kind == "value":
        data = {"rows": _normalize_rows_value(raw_data.get("rows"))}
    elif template.row_kind == "xy":
        data = {"rows": _normalize_rows_xy(raw_data.get("rows"))}
    elif template.labels_from_default:
        # 标准类型系列模板：系列数以 labels.series 为准（缺省回退首行长度）
        named_series = labels.get("series")
        if isinstance(named_series, list) and named_series:
            series_count = max(
                template.series_min or 1, min(len(named_series), template.series_max or len(named_series))
            )
        else:
            series_count = _effective_series_count(template, raw_data)
        data = {"rows": _normalize_rows_series(raw_data.get("rows"), series_count)}
    else:
        series_count = _effective_series_count(template, raw_data)
        data = {"rows": _normalize_rows_series(raw_data.get("rows"), series_count)}

    out: dict[str, Any] = {"caption": caption, "labels": labels, "theme": theme, "data": data}
    if style is not None:
        out["style"] = style
    return out


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

    if template.row_kind == "dual-axis":
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
    elif template.row_kind == "value":
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"第 {i + 1} 行必须是对象")
                continue
            if not _coerce_str(row.get("label"), "").strip():
                errors.append(f"第 {i + 1} 行缺少行标签")
            if _coerce_number(row.get("value")) is None:
                errors.append(f"第 {i + 1} 行数值必须是数字")
    elif template.row_kind == "xy":
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"第 {i + 1} 行必须是对象")
                continue
            if _coerce_number(row.get("x")) is None:
                errors.append(f"第 {i + 1} 行横轴值必须是数字")
            if _coerce_number(row.get("y")) is None:
                errors.append(f"第 {i + 1} 行纵轴值必须是数字")
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
                "row_kind": t.row_kind,
                "label_fields": [dict(f) for f in t.label_fields],
                "style_fields": [dict(f) for f in t.style_fields],
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
