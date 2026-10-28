"""图表唯一渲染入口（ADR 0048 I1）.

管线：``render_chart``（校验 / 归一 → 模板 layout 产出共享图元 → 整幅图组装）
→ ``to_svg``（Web / Markdown 导出资产）/ ``to_png``（DOCX / PDF 导出，见 raster.py）。

- 图元层是两个写端的共享中间表示；写端只做序列化，不做几何计算；
- 轴上限自动扩展、派生值（增速 / 合计 / ``{cagr}``）在 layout 内计算，不落库（C7）；
- 中性色用 ``var(--cn-*, #hex)`` 令牌（SVG 跟随前端明暗主题），PNG 写端解析
  回退十六进制（固定浅色纸底，边界 6）。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from cndb.plugins.documents.services.charts.registry import (
    get_template,
    normalize_config,
)

# ── 语义色令牌（SVG 带 CSS 变量回退；PNG 解析回退值） ──

PAPER = "var(--cn-bg-container, #FBFAF5)"
INK = "var(--cn-text-primary, #17181A)"
MUTED = "var(--cn-text-muted, #6E7276)"
RULE = "var(--cn-border, #D8D2C1)"

#: 品牌红（图号 / 图注边线，两主题一致）
BRAND_RED = "#8E2318"
INK2 = "var(--cn-text-primary, #33363B)"
AXIS_LINE = "#B9B1A0"
YEAR_PROJECTED = "#8C8578"
BAND_DIVIDER = "#8FA0B0"
BAND_FILL = "rgba(30,61,87,.045)"
BAND_LABEL = "#41647C"
OLIVE_DERIVED = "#7A8570"

FONT_FAMILY = "'SimHei', '黑体', 'Noto Sans SC', 'Microsoft YaHei', sans-serif"

#: 整幅图（fig-sheet）横向几何
SHEET_PAD_X = 36.0
SHEET_WIDTH = 1052.0
META_Y = 44.0
META_RULE_Y = 56.0
TITLE_Y = 94.0
SUBTITLE_Y = 122.0
PLOT_TOP = 142.0


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


def _nice_step(max_value: float) -> float:
    """取 1/2/5×10^k 的「好看」刻度步长，使轴上约 4–8 个刻度."""
    if max_value <= 0:
        return 1.0
    raw = max_value / 5
    mag = 10.0 ** math.floor(math.log10(raw))
    for m in (1.0, 2.0, 5.0, 10.0):
        if raw <= m * mag:
            return m * mag
    return 10.0 * mag


def _hex_or(value: str, fallback: str) -> str:
    """调色板取色：越界 / 非法回退."""
    if isinstance(value, str) and value.startswith("#") and len(value) == 7:
        return value
    return fallback


# ══ 模板 1：柱线组合图（双轴 · 含规划期） ══


def _dual_axis_prims(cfg: dict[str, Any]) -> tuple[float, list[Prim]]:
    """柱线双轴布局；返回 (画布高, 图元)."""
    palette = cfg["theme"]["palette"]
    c_actual = _hex_or(palette[0] if palette else "", BRAND_RED)
    c_projected = _hex_or(palette[1] if len(palette) > 1 else "", "#5C7283")
    c_line = _hex_or(palette[2] if len(palette) > 2 else "", "#5F6B4E")
    c_projected_edge = c_projected
    c_line_derived = OLIVE_DERIVED
    labels = cfg["labels"]
    data = cfg["data"]
    rows: list[dict[str, Any]] = data["rows"]
    actual_count = int(data.get("actualCount") or len(rows))
    actual_count = max(1, min(actual_count, len(rows)))

    w, h = 980.0, 600.0
    pad_l, pad_r, pad_t, pad_b = 66.0, 74.0, 90.0, 84.0
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    plot_bottom = pad_t + plot_h
    n = len(rows)
    slot = plot_w / n
    bar_w = 40.0

    values = [float(row["value"] or 0.0) for row in rows]
    max_rev = max(values) if values else 0.0
    step_rev = _nice_step(max_rev)
    y_max_rev = max(step_rev, math.ceil(max_rev / step_rev) * step_rev) if max_rev > 0 else step_rev

    def growth_at(i: int) -> float | None:
        if i <= 0:
            return None
        provided = rows[i].get("growth")
        if provided is not None:
            return provided
        # 次值留空按主值自动推算（ADR 0056：实际段与测算段口径一致，增长曲线不缺段）
        a, b = values[i - 1], values[i]
        if not a or a <= 0:
            return None
        return round((b / a - 1) * 1000) / 10

    growth_vals = [growth_at(i) for i in range(1, n)]
    numeric_growth = [g for g in growth_vals if g is not None]
    max_g = max(numeric_growth) if numeric_growth else 0.0
    step_g = _nice_step(max_g) if max_g > 0 else 5.0
    y_max_g = max(step_g, math.ceil(max_g / step_g) * step_g) if max_g > 0 else step_g

    def x_center(i: int) -> float:
        return pad_l + slot * (i + 0.5)

    def y_rev(v: float) -> float:
        return plot_bottom - (v / y_max_rev) * plot_h

    def y_grow(v: float) -> float:
        return plot_bottom - (v / y_max_g) * plot_h

    boundary = pad_l + slot * actual_count
    prims: list[Prim] = []

    # 背景由整幅图统一画（sheet paper）
    # 规划期底色与分界线
    prims.append(Prim("rect", x=boundary, y=pad_t, w=w - pad_r - boundary, h=plot_h, fill=BAND_FILL, rx=0))
    prims.append(
        Prim(
            "line",
            x1=boundary,
            y1=pad_t - 6,
            x2=boundary,
            y2=plot_bottom,
            stroke=BAND_DIVIDER,
            dash="4 4",
            opacity=0.8,
        )
    )
    prims.append(
        Prim(
            "text",
            tx=boundary + 10,
            ty=pad_t + 16,
            content=str(labels.get("bandLabel", "")),
            size=12.5,
            fill=BAND_LABEL,
        )
    )

    # 网格与左轴刻度
    v = 0.0
    while v <= y_max_rev:
        gy = y_rev(v)
        if v > 0:
            prims.append(Prim("line", x1=pad_l, y1=gy, x2=w - pad_r, y2=gy, stroke=RULE, dash="3 5", opacity=0.55))
        prims.append(Prim("text", tx=pad_l - 12, ty=gy + 5, content=fmt_number(v), size=14, fill=MUTED, anchor="end"))
        v += step_rev
    prims.append(Prim("line", x1=pad_l, y1=plot_bottom, x2=w - pad_r, y2=plot_bottom, stroke=AXIS_LINE))
    prims.append(Prim("line", x1=pad_l, y1=pad_t - 6, x2=pad_l, y2=plot_bottom, stroke=RULE))
    prims.append(
        Prim(
            "text",
            tx=pad_l - 12,
            ty=pad_t - 18,
            content=str(labels.get("unitLeft", "")),
            size=12.5,
            fill=MUTED,
            anchor="end",
        )
    )

    # 右轴刻度
    gv = 0.0
    while gv <= y_max_g:
        prims.append(Prim("text", tx=w - pad_r + 12, ty=y_grow(gv) + 5, content=fmt_number(gv), size=14, fill=MUTED))
        gv += step_g
    prims.append(Prim("line", x1=w - pad_r, y1=pad_t - 6, x2=w - pad_r, y2=plot_bottom, stroke=RULE))
    prims.append(
        Prim("text", tx=w - pad_r + 12, ty=pad_t - 18, content=str(labels.get("unitRight", "")), size=12.5, fill=MUTED)
    )

    # 柱：主值
    for i, row in enumerate(rows):
        val = float(row["value"] or 0.0)
        is_proj = i >= actual_count
        cx = x_center(i)
        bar_h = max(0.0, (val / y_max_rev) * plot_h)
        top = plot_bottom - bar_h
        if bar_h > 0:
            prims.append(
                Prim(
                    "rect",
                    x=cx - bar_w / 2,
                    y=top,
                    w=bar_w,
                    h=bar_h,
                    rx=1.5,
                    fill=c_projected if is_proj else c_actual,
                    stroke=c_projected_edge if is_proj else None,
                    stroke_width=0.8 if is_proj else 0,
                )
            )
        else:
            prims.append(Prim("rect", x=cx - bar_w / 2, y=plot_bottom - 2, w=bar_w, h=2, fill=c_projected_edge, rx=0))
        if val > 0:
            prims.append(
                Prim(
                    "text",
                    tx=cx,
                    ty=top - 10,
                    content=fmt_number(val),
                    size=14.5,
                    weight=600,
                    fill=INK2,
                    anchor="middle",
                )
            )

    # 折线：次值（实际段实线 + 测算段按主值推算）
    pts: list[tuple[int, float, float, float, bool]] = []  # (i, v, x, y, proj)
    for i in range(1, n):
        g = growth_at(i)
        if g is not None:
            pts.append((i, g, x_center(i), y_grow(g), i >= actual_count))
    if pts:
        d = " ".join(f"{'M' if idx == 0 else 'L'} {p[2]:.1f} {p[3]:.1f}" for idx, p in enumerate(pts))
        prims.append(Prim("path", d=d, stroke=c_line, stroke_width=2))
        for _, _, px, py, proj in pts:
            prims.append(
                Prim(
                    "circle",
                    cx=px,
                    cy=py,
                    r=4 if proj else 5,
                    fill=PAPER if proj else c_line,
                    stroke=c_line,
                    stroke_width=1.8,
                )
            )

    def _rects_hit(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
        return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]

    # 增长率标签避让（用户反馈：标签压柱体 / 遮主值标签 / 压增长线看不清）。
    # 已占区域：柱体、柱顶主值标签、规划期标注、增长折线段与数据点标记；
    # 候选位按「点上方 → 更高 → 点下方」取第一个无碰撞位，
    # 全部碰撞时取最小碰撞候选并靠纸色 halo 保证可读（标签永不加底板压进柱内）。
    occupied: list[tuple[float, float, float, float]] = [
        (
            x_center(i) - bar_w / 2,
            plot_bottom - (values[i] / y_max_rev) * plot_h,
            bar_w,
            (values[i] / y_max_rev) * plot_h,
        )
        for i in range(n)
        if values[i] > 0
    ]
    for i in range(n):
        if values[i] > 0:
            tw = text_width(fmt_number(values[i]), 14.5)
            bar_top = plot_bottom - (values[i] / y_max_rev) * plot_h
            occupied.append((x_center(i) - tw / 2 - 4, bar_top - 28, tw + 8, 26))
    band_lw = text_width(str(labels.get("bandLabel", "")), 12.5)
    occupied.append((boundary + 6, pad_t + 2, band_lw + 8, 20))
    # 增长折线段（沿线近似加粗）与数据点标记也纳入占位，标签不得压线
    for j in range(1, len(pts)):
        x0, y0 = pts[j - 1][2], pts[j - 1][3]
        x1, y1 = pts[j][2], pts[j][3]
        occupied.append((min(x0, x1) - 5, min(y0, y1) - 5, abs(x1 - x0) + 10, abs(y1 - y0) + 10))
    for _, _, px, py, _proj in pts:
        occupied.append((px - 8, py - 8, 16, 16))
    # 左右轴刻度带整列占位（标签 x 平移避让时不得压进轴区）
    occupied.append((pad_l - 70, pad_t - 30, 70, plot_h + 40))
    occupied.append((w - pad_r, pad_t - 30, 80, plot_h + 40))

    def _label_bbox(px: float, py: float, lw: float, dx: float, dy: float) -> tuple[float, float, float, float]:
        cx = min(max(px + dx, pad_l + lw / 2 + 4), w - pad_r - lw / 2 - 4)
        cy = min(max(py + dy, pad_t + 6), plot_bottom - 4)
        return (cx - lw / 2 - 4, cy - 10, lw + 8, 22)

    for _, g, px, py, proj in pts:
        label = fmt_number(g) + "%"
        lw = text_width(label, 14.5)
        # 候选位：(dx, dy) 相对折线点。先近后远：点上下 → 柱侧平移 → 更高梯子。
        dodge = bar_w / 2 + lw / 2 + 8
        candidates = [
            (0.0, -20.0),
            (0.0, -34.0),
            (0.0, 30.0),
            (-dodge, 0.0),
            (dodge, 0.0),
            (-dodge, -14.0),
            (dodge, -14.0),
            (-dodge, 14.0),
            (dodge, 14.0),
            (0.0, -48.0),
            (0.0, 44.0),
            (0.0, -62.0),
            (0.0, -76.0),
            (0.0, -90.0),
            (0.0, -104.0),
            (0.0, -118.0),
            (0.0, -132.0),
        ]
        scored = [
            (
                sum(1 for occ in occupied if _rects_hit(_label_bbox(px, py, lw, dx, dy), occ)),
                idx,
                _label_bbox(px, py, lw, dx, dy),
            )
            for idx, (dx, dy) in enumerate(candidates)
        ]
        _, _, bbox = min(scored, key=lambda t: (t[0], t[1]))
        occupied.append(bbox)
        prims.append(
            Prim(
                "text",
                tx=bbox[0] + lw / 2 + 4,
                ty=bbox[1] + 15,
                content=label,
                size=14.5,
                weight=700,
                fill=c_line_derived if proj else c_line,
                anchor="middle",
                halo=True,
            )
        )

    # 横轴年份与区间说明
    for i, row in enumerate(rows):
        prims.append(
            Prim(
                "text",
                tx=x_center(i),
                ty=plot_bottom + 28,
                content=str(row["label"]),
                size=15,
                fill=INK2 if i < actual_count else YEAR_PROJECTED,
                anchor="middle",
            )
        )
    cap_y = plot_bottom + 47
    prims.append(Prim("line", x1=pad_l + 4, y1=cap_y, x2=boundary - 6, y2=cap_y, stroke=RULE))
    prims.append(
        Prim(
            "text",
            tx=(pad_l + boundary - 6) / 2,
            ty=cap_y + 19,
            content=str(labels.get("capActual", "")),
            size=12,
            fill=MUTED,
            anchor="middle",
        )
    )
    prims.append(Prim("line", x1=boundary + 6, y1=cap_y, x2=w - pad_r - 4, y2=cap_y, stroke=RULE))
    prims.append(
        Prim(
            "text",
            tx=(boundary + 6 + w - pad_r - 4) / 2,
            ty=cap_y + 19,
            content=str(labels.get("capProjected", "")),
            size=12,
            fill=MUTED,
            anchor="middle",
        )
    )

    # 图例（居中）
    items = [
        ("rect", c_actual, None, str(labels.get("legendActual", ""))),
        ("rect", c_projected, c_projected_edge, str(labels.get("legendProjected", ""))),
        ("line", c_line, None, str(labels.get("legendGrowth", ""))),
    ]
    widths = [(20.0 if t == "rect" else 27.0) + text_width(lbl, 13.5) for t, _, _, lbl in items]
    total_w = sum(widths) + 34.0 * (len(items) - 1)
    cursor = (w - total_w) / 2
    ly = 32.0
    for idx, (kind, color, edge, lbl) in enumerate(items):
        if kind == "rect":
            prims.append(
                Prim(
                    "rect",
                    x=cursor,
                    y=ly - 9,
                    w=13,
                    h=9,
                    rx=1,
                    fill=color,
                    stroke=edge,
                    stroke_width=0.8 if edge else 0,
                )
            )
            cursor += 20.0
        else:
            prims.append(
                Prim("line", x1=cursor, y1=ly - 4.5, x2=cursor + 20, y2=ly - 4.5, stroke=color, stroke_width=2)
            )
            prims.append(Prim("circle", cx=cursor + 10, cy=ly - 4.5, r=3, fill=color, stroke=color, stroke_width=1.5))
            cursor += 27.0
        prims.append(Prim("text", tx=cursor, ty=ly, content=lbl, size=13.5, fill=MUTED))
        cursor += text_width(lbl, 13.5) + (0 if idx == len(items) - 1 else 34.0)

    return h, prims


# ══ 模板 2：水平堆叠条形图 ══


def _stacked_bar_prims(cfg: dict[str, Any]) -> tuple[float, list[Prim]]:
    palette = cfg["theme"]["palette"]
    default_palette = ["#8E2318", "#1E3D57", "#5F6B4E"]
    labels = cfg["labels"]
    series_names: list[str] = labels.get("series") or []
    rows: list[dict[str, Any]] = cfg["data"]["rows"]

    w, h = 980.0, 470.0
    pad_l, pad_r, pad_t, pad_b = 96.0, 72.0, 96.0, 88.0
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    plot_bottom = pad_t + plot_h
    n_rows = len(rows)
    if n_rows > 8:
        h = pad_t + pad_b + 64.0 * n_rows
        plot_h = h - pad_t - pad_b
    slot = plot_h / n_rows
    bar_h = min(54.0, slot * 0.62)

    totals = [sum(float(v or 0.0) for v in row["values"]) for row in rows]
    max_total = max(totals) if totals else 0.0
    step = _nice_step(max_total)
    x_max = max(step, math.ceil(max_total / step) * step) if max_total > 0 else step

    def x_scale(v: float) -> float:
        return pad_l + (v / x_max) * plot_w

    prims: list[Prim] = []

    # 纵向网格与横轴刻度
    v = 0.0
    while v <= x_max:
        gx = x_scale(v)
        if v > 0:
            prims.append(
                Prim("line", x1=gx, y1=pad_t - 6, x2=gx, y2=plot_bottom, stroke=RULE, dash="3 5", opacity=0.55)
            )
        prims.append(
            Prim("text", tx=gx, ty=plot_bottom + 26, content=fmt_number(v), size=14, fill=MUTED, anchor="middle")
        )
        v += step
    prims.append(Prim("line", x1=pad_l, y1=pad_t - 6, x2=pad_l, y2=plot_bottom, stroke=AXIS_LINE))
    prims.append(Prim("line", x1=pad_l, y1=plot_bottom, x2=w - pad_r, y2=plot_bottom, stroke=RULE))
    prims.append(
        Prim(
            "text",
            tx=w - pad_r,
            ty=pad_t - 18,
            content=str(labels.get("unitX", "")),
            size=12.5,
            fill=MUTED,
            anchor="end",
        )
    )

    n_series = len(series_names) or 1
    for i, row in enumerate(rows):
        cy = plot_bottom - slot * (i + 0.5)
        y_top = cy - bar_h / 2
        prims.append(
            Prim("text", tx=pad_l - 14, ty=cy + 5, content=str(row["label"]), size=13.5, fill=INK2, anchor="end")
        )
        acc = 0.0
        total = totals[i]
        for s in range(n_series):
            val = float(row["values"][s] or 0.0) if s < len(row["values"]) else 0.0
            seg_w = max(0.0, val / x_max * plot_w)
            x = x_scale(acc)
            color = _hex_or(palette[s] if s < len(palette) else "", default_palette[s % len(default_palette)])
            if seg_w > 0:
                prims.append(Prim("rect", x=x, y=y_top, w=seg_w, h=bar_h, rx=0, fill=color))
            if val > 0:
                if seg_w >= 40:
                    prims.append(
                        Prim(
                            "text",
                            tx=x + seg_w / 2,
                            ty=cy + 5,
                            content=fmt_number(val),
                            size=13.5,
                            weight=600,
                            fill="#FFFFFF",
                            anchor="middle",
                        )
                    )
                else:
                    prims.append(
                        Prim(
                            "text",
                            tx=x + seg_w / 2,
                            ty=y_top - 9,
                            content=fmt_number(val),
                            size=12.5,
                            weight=600,
                            fill=color,
                            anchor="middle",
                            halo=True,
                        )
                    )
            acc += val
        if total > 0:
            prims.append(
                Prim(
                    "text",
                    tx=x_scale(total) + 10,
                    ty=cy + 5,
                    content=fmt_number(total),
                    size=14.5,
                    weight=700,
                    fill=INK2,
                )
            )

    # 图例（居中）
    widths = [20.0 + text_width(name, 13.5) for name in series_names]
    total_w = sum(widths) + 34.0 * max(0, len(series_names) - 1)
    cursor = (w - total_w) / 2
    ly = 32.0
    for idx, name in enumerate(series_names):
        color = _hex_or(palette[idx] if idx < len(palette) else "", default_palette[idx % len(default_palette)])
        prims.append(Prim("rect", x=cursor, y=ly - 9, w=13, h=9, rx=1, fill=color))
        cursor += 20.0
        prims.append(Prim("text", tx=cursor, ty=ly, content=name, size=13.5, fill=MUTED))
        cursor += text_width(name, 13.5) + (0 if idx == len(series_names) - 1 else 34.0)

    return h, prims


# ══ 模板 3：水平分组条形图 ══


def _grouped_bar_prims(cfg: dict[str, Any]) -> tuple[float, list[Prim]]:
    palette = cfg["theme"]["palette"]
    c_now = _hex_or(palette[0] if palette else "", "#E9E4D6")
    c_goal = _hex_or(palette[1] if len(palette) > 1 else "", "#8E2318")
    labels = cfg["labels"]
    series_names: list[str] = labels.get("series") or ["现状", "目标"]
    rows: list[dict[str, Any]] = cfg["data"]["rows"]

    w, h = 980.0, 620.0
    pad_l, pad_r, pad_t, pad_b = 100.0, 64.0, 92.0, 92.0
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    plot_bottom = pad_t + plot_h
    n_rows = len(rows)
    if n_rows > 10:
        h = pad_t + pad_b + 52.0 * n_rows
        plot_h = h - pad_t - pad_b
    slot = plot_h / n_rows
    bar_h = 16.0
    bar_gap = 8.0
    group_h = bar_h * 2 + bar_gap

    max_val = 0.0
    for row in rows:
        for v in row["values"][:2]:
            max_val = max(max_val, float(v or 0.0))
    step = _nice_step(max_val)
    x_max = max(step, math.ceil(max_val / step) * step) if max_val > 0 else step

    def x_scale(v: float) -> float:
        return pad_l + (v / x_max) * plot_w

    prims: list[Prim] = []

    v = 0.0
    while v <= x_max:
        gx = x_scale(v)
        if v > 0:
            prims.append(
                Prim("line", x1=gx, y1=pad_t - 6, x2=gx, y2=plot_bottom, stroke=RULE, dash="3 5", opacity=0.55)
            )
        prims.append(
            Prim("text", tx=gx, ty=plot_bottom + 26, content=fmt_number(v), size=14, fill=MUTED, anchor="middle")
        )
        v += step
    prims.append(Prim("line", x1=pad_l, y1=pad_t - 6, x2=pad_l, y2=plot_bottom, stroke=AXIS_LINE))
    prims.append(Prim("line", x1=pad_l, y1=plot_bottom, x2=w - pad_r, y2=plot_bottom, stroke=RULE))
    prims.append(
        Prim(
            "text",
            tx=w - pad_r,
            ty=pad_t - 18,
            content=str(labels.get("unitX", "")),
            size=12.5,
            fill=MUTED,
            anchor="end",
        )
    )

    for i, row in enumerate(rows):
        cy = plot_bottom - slot * (i + 0.5)
        group_top = cy - group_h / 2
        prims.append(
            Prim("text", tx=pad_l - 14, ty=cy + 5, content=str(row["label"]), size=13.5, fill=INK2, anchor="end")
        )
        for s in range(2):
            val = float(row["values"][s] or 0.0) if s < len(row["values"]) else 0.0
            seg_w = max(0.0, val / x_max * plot_w)
            y = group_top + s * (bar_h + bar_gap)
            color = c_now if s == 0 else c_goal
            if seg_w > 0:
                prims.append(
                    Prim(
                        "rect",
                        x=pad_l,
                        y=y,
                        w=seg_w,
                        h=bar_h,
                        rx=2,
                        fill=color,
                        stroke="#C6BFAD" if s == 0 else None,
                        stroke_width=0.8 if s == 0 else 0,
                    )
                )
                label_color = INK2 if s == 0 else c_goal
                if seg_w < plot_w - 60:
                    prims.append(
                        Prim(
                            "text",
                            tx=pad_l + seg_w + 8,
                            ty=y + bar_h / 2 + 4.5,
                            content=fmt_number(val),
                            size=12.5,
                            weight=600,
                            fill=label_color,
                        )
                    )
                else:
                    prims.append(
                        Prim(
                            "text",
                            tx=pad_l + seg_w - 8,
                            ty=y + bar_h / 2 + 4.5,
                            content=fmt_number(val),
                            size=12.5,
                            weight=600,
                            fill="#FFFFFF" if s == 1 else INK2,
                            anchor="end",
                        )
                    )

    # 图例（居中）
    widths = [20.0 + text_width(name, 13.5) for name in series_names[:2]]
    total_w = sum(widths) + 34.0 * max(0, len(series_names[:2]) - 1)
    cursor = (w - total_w) / 2
    ly = 32.0
    for idx, name in enumerate(series_names[:2]):
        color = c_now if idx == 0 else c_goal
        prims.append(
            Prim(
                "rect",
                x=cursor,
                y=ly - 9,
                w=13,
                h=9,
                rx=1,
                fill=color,
                stroke="#C6BFAD" if idx == 0 else None,
                stroke_width=0.8 if idx == 0 else 0,
            )
        )
        cursor += 20.0
        prims.append(Prim("text", tx=cursor, ty=ly, content=name, size=13.5, fill=MUTED))
        cursor += text_width(name, 13.5) + (0 if idx == 1 else 34.0)

    return h, prims


_LAYOUTS: dict[str, Callable[[dict[str, Any]], tuple[float, list[Prim]]]] = {
    "bar-line-dual-axis": _dual_axis_prims,
    "stacked-bar-horizontal": _stacked_bar_prims,
    "grouped-bar-horizontal": _grouped_bar_prims,
}


# ══ 整幅图组装 ══


def _cagr_token(cfg: dict[str, Any]) -> str:
    """``{cagr}``：规划期首末值的复合增速（对齐参考 HTML 联动）."""
    rows = cfg["data"]["rows"]
    actual_count = int(cfg["data"].get("actualCount") or len(rows))
    if actual_count < 1 or len(rows) <= actual_count:
        return "—"
    base = rows[actual_count - 1].get("value")
    last = rows[-1].get("value")
    span = len(rows) - actual_count
    if not base or not last or base <= 0 or span <= 0:
        return "—"
    return f"{(math.pow(last / base, 1 / span) - 1) * 100:.1f}%"


def _apply_tokens(cfg: dict[str, Any], note: str) -> str:
    """图注 token 白名单替换；未知 token 原样保留（D11）."""
    return note.replace("{cagr}", _cagr_token(cfg))


def _offset(prims: list[Prim], dx: float, dy: float) -> list[Prim]:
    """把图区局部坐标平移到整幅图坐标（含文本背景片与折线路径）."""
    out: list[Prim] = []
    for p in prims:
        q = Prim(**vars(p))
        if q.kind == "rect":
            q.x += dx
            q.y += dy
        elif q.kind == "line":
            q.x1 += dx
            q.y1 += dy
            q.x2 += dx
            q.y2 += dy
        elif q.kind == "circle":
            q.cx += dx
            q.cy += dy
        elif q.kind == "text":
            q.tx += dx
            q.ty += dy
            if q.plate is not None:
                px, py, pw, ph = q.plate
                q.plate = (px + dx, py + dy, pw, ph)
        elif q.kind == "path" and q.d:
            q.d = _translate_path(q.d, dx, dy)
        out.append(q)
    return out


def _translate_path(d: str, dx: float, dy: float) -> str:
    """平移 ``M x y L x y …`` 形式的折线路径."""
    tokens = d.split(" ")
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("M", "L") and i + 2 < len(tokens) + 1:
            try:
                x, y = float(tokens[i + 1]), float(tokens[i + 2])
                out.append(f"{tok}{x + dx:.1f} {y + dy:.1f}")
                i += 3
                continue
            except ValueError:
                pass
        out.append(tok)
        i += 1
    return " ".join(out)


def render_degraded(chart_id: int, reason: str) -> ChartDocument:
    """失效引用的降级整幅图（I5：不阻断，占位显式可见）."""
    w, h = 640.0, 180.0
    prims = [
        Prim("rect", x=1, y=1, w=w - 2, h=h - 2, rx=6, fill=PAPER, stroke=RULE, stroke_width=1),
        Prim("text", tx=w / 2, ty=64, content=f"图表 #{chart_id}", size=15, weight=600, fill=MUTED, anchor="middle"),
        Prim("text", tx=w / 2, ty=100, content=reason, size=13, fill=MUTED, anchor="middle"),
    ]
    return ChartDocument(width=w, height=h, label=f"图表 #{chart_id}", elements=prims)


def render_chart(template_key: str, config: Any) -> ChartDocument:
    """唯一渲染入口：归一 → 模板布局 → 整幅图（图头 / 标题 / 图区 / 图注）."""
    template = get_template(template_key)
    if template is None:
        raise BadRequestTemplateError(template_key)
    cfg = normalize_config(template_key, config)
    # 行数据整体缺失（如设计器初始空配置）→ 回退模板默认行（I6 坏值回退，避免布局除零）
    if not cfg["data"]["rows"]:
        cfg = normalize_config(template_key, template.default_config)
    layout = _LAYOUTS[template_key]
    plot_h, plot_prims = layout(cfg)
    # 行数多时布局可加高画布：以布局返回值为准
    caption = cfg["caption"]

    prims: list[Prim] = [Prim("rect", x=0, y=0, w=SHEET_WIDTH, h=0, rx=0, fill=PAPER)]
    prims.append(
        Prim(
            "text", tx=SHEET_PAD_X, ty=META_Y, content=str(caption.get("no", "")), size=12.5, fill=BRAND_RED, mono=True
        )
    )
    ctx = str(caption.get("context", ""))
    if ctx:
        prims.append(
            Prim("text", tx=SHEET_WIDTH - SHEET_PAD_X, ty=META_Y, content=ctx, size=11.5, fill=MUTED, anchor="end")
        )
    prims.append(
        Prim("line", x1=SHEET_PAD_X, y1=META_RULE_Y, x2=SHEET_WIDTH - SHEET_PAD_X, y2=META_RULE_Y, stroke=RULE)
    )
    prims.append(
        Prim("text", tx=SHEET_PAD_X, ty=TITLE_Y, content=str(caption.get("title", "")), size=24, weight=600, fill=INK)
    )
    sub = str(caption.get("subtitle", ""))
    if sub:
        prims.append(Prim("text", tx=SHEET_PAD_X, ty=SUBTITLE_Y, content=sub, size=12.5, fill=MUTED))

    plot_top = PLOT_TOP if sub else PLOT_TOP - 28.0
    prims.extend(_offset(plot_prims, SHEET_PAD_X, plot_top))

    # 图注（左红边线 + 多行）
    note = _apply_tokens(cfg, str(caption.get("note", "")))
    y_cursor = plot_top + plot_h + 22.0
    if note:
        lines = note.split("\n")
        prims.append(
            Prim(
                "line",
                x1=SHEET_PAD_X + 2,
                y1=y_cursor - 12,
                x2=SHEET_PAD_X + 2,
                y2=y_cursor - 12 + 24.0 * len(lines) - 10,
                stroke=BRAND_RED,
                stroke_width=2,
            )
        )
        for line in lines:
            prims.append(Prim("text", tx=SHEET_PAD_X + 14, ty=y_cursor, content=line, size=12.5, fill=MUTED))
            y_cursor += 24.0

    total_h = y_cursor + 14.0
    prims[0].h = total_h
    return ChartDocument(
        width=SHEET_WIDTH, height=total_h, label=str(caption.get("title", "")) or template.name, elements=prims
    )


class BadRequestTemplateError(Exception):
    """模板已下线 / 不存在（渲染入口的受控失败，由调用方转降级或 400）."""

    def __init__(self, template_key: str) -> None:
        super().__init__(f"模板 {template_key} 不存在或已下线")
        self.template_key = template_key


__all__ = [
    "ChartDocument",
    "Prim",
    "render_chart",
    "render_degraded",
    "text_width",
]
