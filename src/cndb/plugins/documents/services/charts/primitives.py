"""图表共享图元与几何工具（ADR 0048 / 需求卡片 0070）.

从 ``render`` 下沉的共享层：``Prim`` / ``ChartDocument`` 图元模型、文本宽度
估算、数值格式化、刻度步长与通用图例绘制。``render``（整幅组装）与
``layouts``（模板布局）共同依赖，写端（SVG / PNG）只认 ``Prim``。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# ── 语义色令牌（SVG 带 CSS 变量回退；PNG 解析回退值） ──

PAPER = "var(--cn-bg-container, #FBFAF5)"
INK = "var(--cn-text-primary, #17181A)"
MUTED = "var(--cn-text-muted, #6E7276)"
RULE = "var(--cn-border, #D8D2C1)"

#: 品牌红（图号 / 图注边线，两主题一致）
BRAND_RED = "#8E2318"
INK2 = "var(--cn-text-primary, #33363B)"
AXIS_LINE = "#B9B1A0"

FONT_FAMILY = "'SimHei', '黑体', 'Noto Sans SC', 'Microsoft YaHei', sans-serif"


@dataclass
class Prim:
    """共享图元：两个写端（SVG / PNG）的唯一绘制指令."""

    kind: str  # rect | line | circle | path | text
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    rx: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    cx: float = 0.0
    cy: float = 0.0
    r: float = 0.0
    d: str = ""
    #: 文本基线锚点（text 图元专用）
    tx: float = 0.0
    ty: float = 0.0
    content: str = ""
    size: float = 13.0
    fill: str = ""
    stroke: str | None = None
    stroke_width: float = 1.0
    dash: str | None = None
    opacity: float | None = None
    weight: int = 400
    anchor: str = "start"  # start | middle | end
    #: 文本背景片 (x, y, w, h)，先于文本绘制（深柱内标签，对齐参考 HTML）
    plate: tuple[float, float, float, float] | None = None
    #: 文本描边留白（图面空白处的标签，对齐 paint-order: stroke）
    halo: bool = False
    #: 等宽字体（图号），其余用黑体族
    mono: bool = False


@dataclass
class ChartDocument:
    """整幅图：fig-sheet 形态（图头 meta / 标题 / 图区 / 图注）."""

    width: float
    height: float
    label: str
    elements: list[Prim] = field(default_factory=list)


def text_width(content: str, size: float) -> float:
    """估算文本渲染宽度（CJK 按一字宽、ASCII 按 0.55 字宽，对齐帮助图示口径）."""
    total = 0.0
    for ch in content:
        total += size * (1.0 if ord(ch) > 0x2E7F else 0.55)
    return total


def fmt_number(value: float) -> str:
    """数值文本化：一位小数内四舍五入，去掉多余的 .0（对齐参考 HTML fmt）."""
    n = round(value * 10) / 10
    if n == int(n):
        return str(int(n))
    return f"{n:g}"


def nice_step(max_value: float) -> float:
    """取 1/2/5×10^k 的「好看」刻度步长，使轴上约 4–8 个刻度."""
    if max_value <= 0:
        return 1.0
    raw = max_value / 5
    mag = 10.0 ** math.floor(math.log10(raw))
    for m in (1.0, 2.0, 5.0, 10.0):
        if raw <= m * mag:
            return m * mag
    return 10.0 * mag


def nice_ceil(max_value: float) -> float:
    """轴上限自动扩展：向上取整到好看步长的整数倍（≥ 一个步长）."""
    if max_value <= 0:
        return nice_step(1.0)
    step = nice_step(max_value)
    return max(step, math.ceil(max_value / step) * step)


def hex_or(value: str, fallback: str) -> str:
    """调色板取色：越界 / 非法回退."""
    if isinstance(value, str) and value.startswith("#") and len(value) == 7:
        return value
    return fallback


def rgba_fill(hex_color: str, alpha: float) -> str:
    """十六进制色 → 半透明填充（面积 / 雷达；PNG 写端按纸色混合回退）."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def series_color(palette: list[str], index: int, default: str = "#1E3D57") -> str:
    """系列取色：按索引循环调色板，非法回退默认色."""
    if not palette:
        return default
    return hex_or(palette[index % len(palette)], default)


def draw_legend(
    prims: list[Prim],
    items: list[tuple[str, str, str]],
    w: float,
    ly: float = 32.0,
) -> None:
    """居中图例：``items`` 为 (rect|line, 颜色, 文案)，追加进 ``prims``.

    各模板布局共用（需求卡片 0070：新模板统一图例口径，旧布局保持原实现）。
    """
    widths = [(20.0 if t == "rect" else 27.0) + text_width(lbl, 13.5) for t, _, lbl in items]
    total_w = sum(widths) + 34.0 * max(0, len(items) - 1)
    cursor = (w - total_w) / 2
    for idx, (kind, color, lbl) in enumerate(items):
        if kind == "rect":
            prims.append(Prim("rect", x=cursor, y=ly - 9, w=13, h=9, rx=1, fill=color))
            cursor += 20.0
        else:
            prims.append(
                Prim("line", x1=cursor, y1=ly - 4.5, x2=cursor + 20, y2=ly - 4.5, stroke=color, stroke_width=2)
            )
            cursor += 27.0
        prims.append(Prim("text", tx=cursor, ty=ly, content=lbl, size=13.5, fill=MUTED))
        cursor += text_width(lbl, 13.5) + (0 if idx == len(items) - 1 else 34.0)


def nice_axis(max_value: float) -> tuple[float, float]:
    """数值轴 (步长, 上限)：均按好看步长取整."""
    step = nice_step(max_value)
    return step, nice_ceil(max_value)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(v, hi))


#: M/L 折线路径解析（命令字母与坐标之间的空格可选，兼容粘连形态）
_PATH_POINT = re.compile(r"([ML])\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")


def parse_path_points(d: str) -> list[tuple[float, float]]:
    """解析 ``M x y L x y …`` 形式的折线路径 → 坐标点列.

    历史上 ``_translate_path`` 曾输出 ``M366.0 467.0``（命令与坐标粘连），
    PNG 写端按空格分词解析会整段丢失；此解析器兼容两种形态（需求卡片 0070 C5）。
    """
    return [(float(m.group(2)), float(m.group(3))) for m in _PATH_POINT.finditer(d)]


__all__ = [
    "AXIS_LINE",
    "BRAND_RED",
    "FONT_FAMILY",
    "INK",
    "INK2",
    "MUTED",
    "PAPER",
    "RULE",
    "ChartDocument",
    "Prim",
    "clamp",
    "draw_legend",
    "fmt_number",
    "hex_or",
    "nice_axis",
    "nice_ceil",
    "nice_step",
    "parse_path_points",
    "rgba_fill",
    "series_color",
    "text_width",
]
