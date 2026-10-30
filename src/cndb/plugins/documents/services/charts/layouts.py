"""标准图表类型布局（需求卡片 0070）：折线 / 面积 / 柱状 / 饼图 / 散点 / 雷达 / 漏斗 / 仪表盘 / 树状图 / 热力图.

- 每类图表一个布局函数，预设模板（注册表条目）共享布局、以 default_config
  差异化配色 / 纸底 / 样式开关（``style`` 节）与示例数据；
- 圆弧（饼图扇形 / 仪表盘刻度弧）用 M/L 折线近似，两端写端（SVG / PNG）
  的路径解析零分叉；填充路径走 ``Prim.fill``（面积 / 雷达 / 漏斗连接带）；
- 布局只读归一后的 config，坏值已在 registry 归一（None → 按缺省处理），
  此处仍做防御：空系列 / 全零值不得除零或抛错。
"""

from __future__ import annotations

import math
from typing import Any

from cndb.plugins.documents.services.charts.primitives import (
    AXIS_LINE,
    INK2,
    MUTED,
    PAPER,
    RULE,
    Prim,
    draw_legend,
    fmt_number,
    nice_axis,
    nice_step,
    rgba_fill,
    series_color,
)

#: 画布横向宽度（与既有三模板一致：整幅 1052 − 两侧 36 边距）
W = 980.0


def _style_flag(cfg: dict[str, Any], key: str, default: bool) -> bool:
    """样式开关读取：config 无 style 节（旧数据 / 预览脏值）时回退默认."""
    style = cfg.get("style")
    if isinstance(style, dict):
        value = style.get(key)
        if isinstance(value, bool):
            return value
    return default


def _series_frame(cfg: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """系列类模板的 (系列名, 行) 提取."""
    names = [str(n) for n in (cfg["labels"].get("series") or [])]
    rows = cfg["data"]["rows"]
    return names, rows


def _row_values(row: dict[str, Any], count: int) -> list[float]:
    """行系列值：None 补 0，截断到系列数."""
    raw = row.get("values") or []
    out = [float(raw[i] or 0.0) if i < len(raw) else 0.0 for i in range(count)]
    return out


def _h_axis(
    prims: list[Prim],
    left: float,
    right: float,
    bottom: float,
    plot_h: float,
    y_max: float,
    step: float,
) -> None:
    """纵轴：水平网格线 + 左侧刻度 + 轴线."""
    v = 0.0
    while v <= y_max + 1e-9:
        gy = bottom - (v / y_max) * plot_h if y_max > 0 else bottom
        if v > 0:
            prims.append(Prim("line", x1=left, y1=gy, x2=right, y2=gy, stroke=RULE, dash="3 5", opacity=0.55))
        prims.append(Prim("text", tx=left - 10, ty=gy + 5, content=fmt_number(v), size=13, fill=MUTED, anchor="end"))
        v += step
    prims.append(Prim("line", x1=left, y1=bottom, x2=right, y2=bottom, stroke=AXIS_LINE))


def _x_labels(prims: list[Prim], rows: list[dict[str, Any]], xs: list[float], bottom: float, limit: int = 16) -> None:
    """横轴分类标签：行数过多时间隔显示，避免重叠."""
    n = len(rows)
    stride = 1 if n <= limit else math.ceil(n / limit)
    for i in range(0, n, stride):
        prims.append(
            Prim(
                "text",
                tx=xs[i],
                ty=bottom + 26,
                content=str(rows[i].get("label", "")),
                size=13,
                fill=INK2,
                anchor="middle",
            )
        )


# ══ 折线图 ══


def _line_prims(cfg: dict[str, Any]) -> tuple[float, list[Prim]]:
    series_names, rows = _series_frame(cfg)
    n_series = len(series_names)
    palette = cfg["theme"]["palette"]
    show_markers = _style_flag(cfg, "showMarkers", True)
    show_values = _style_flag(cfg, "showValues", False)

    h = 560.0
    pad_l, pad_r, pad_t, pad_b = 70.0, 30.0, 56.0, 78.0
    left, right = pad_l, W - pad_r
    plot_w, plot_h = right - left, h - pad_t - pad_b
    bottom = pad_t + plot_h
    n = len(rows)
    xs = [left + plot_w * (i / (n - 1)) if n > 1 else (left + right) / 2 for i in range(n)]

    max_v = 0.0
    for row in rows:
        for v in _row_values(row, n_series):
            max_v = max(max_v, v)
    step, y_max = nice_axis(max_v)

    prims: list[Prim] = []
    _h_axis(prims, left, right, bottom, plot_h, y_max, step)
    prims.append(
        Prim(
            "text",
            tx=left - 10,
            ty=pad_t - 14,
            content=str(cfg["labels"].get("unitY", "")),
            size=12.5,
            fill=MUTED,
            anchor="end",
        )
    )
    _x_labels(prims, rows, xs, bottom)

    for s in range(n_series):
        color = series_color(palette, s)
        pts: list[tuple[float, float]] = []
        for i, row in enumerate(rows):
            v = _row_values(row, n_series)[s]
            pts.append((xs[i], bottom - (v / y_max) * plot_h if y_max > 0 else bottom))
        d = " ".join(f"{'M' if k == 0 else 'L'} {px:.1f} {py:.1f}" for k, (px, py) in enumerate(pts))
        prims.append(Prim("path", d=d, stroke=color, stroke_width=2.4))
        if show_markers:
            for px, py in pts:
                prims.append(Prim("circle", cx=px, cy=py, r=4, fill=PAPER, stroke=color, stroke_width=2))
        if show_values:
            for i, (px, py) in enumerate(pts):
                v = _row_values(rows[i], n_series)[s]
                prims.append(
                    Prim(
                        "text",
                        tx=px,
                        ty=py - 10,
                        content=fmt_number(v),
                        size=12,
                        weight=600,
                        fill=color,
                        anchor="middle",
                        halo=True,
                    )
                )

    draw_legend(prims, [("line", series_color(palette, s), name) for s, name in enumerate(series_names)], W)
    return h, prims


# ══ 面积图 ══


def _area_prims(cfg: dict[str, Any]) -> tuple[float, list[Prim]]:
    series_names, rows = _series_frame(cfg)
    n_series = len(series_names)
    palette = cfg["theme"]["palette"]
    stacked = _style_flag(cfg, "stacked", False)
    show_values = _style_flag(cfg, "showValues", False)

    h = 560.0
    pad_l, pad_r, pad_t, pad_b = 70.0, 30.0, 56.0, 78.0
    left, right = pad_l, W - pad_r
    plot_w, plot_h = right - left, h - pad_t - pad_b
    bottom = pad_t + plot_h
    n = len(rows)
    xs = [left + plot_w * (i / (n - 1)) if n > 1 else (left + right) / 2 for i in range(n)]

    # 堆叠：逐行累加；平铺：各系列独立
    levels: list[list[float]] = []
    for row in rows:
        vals = _row_values(row, n_series)
        if stacked:
            base = levels[-1] if levels else [0.0] * n_series
            levels.append([base[s] + vals[s] for s in range(n_series)])
        else:
            levels.append(vals)
    max_v = max((v for lv in levels for v in lv), default=0.0)
    step, y_max = nice_axis(max_v)

    prims: list[Prim] = []
    _h_axis(prims, left, right, bottom, plot_h, y_max, step)
    prims.append(
        Prim(
            "text",
            tx=left - 10,
            ty=pad_t - 14,
            content=str(cfg["labels"].get("unitY", "")),
            size=12.5,
            fill=MUTED,
            anchor="end",
        )
    )
    _x_labels(prims, rows, xs, bottom)

    # 后系列先画，首系列置顶
    for s in range(n_series - 1, -1, -1):
        color = series_color(palette, s)
        top_pts = [(xs[i], bottom - (levels[i][s] / y_max) * plot_h if y_max > 0 else bottom) for i in range(n)]
        if n >= 2:
            d = (
                f"M {top_pts[0][0]:.1f} {bottom:.1f} "
                + " ".join(f"L {px:.1f} {py:.1f}" for px, py in top_pts)
                + f" L {top_pts[-1][0]:.1f} {bottom:.1f}"
            )
            prims.append(Prim("path", d=d, fill=rgba_fill(color, 0.30)))
        prims.append(
            Prim(
                "path",
                d=" ".join(f"{'M' if k == 0 else 'L'} {px:.1f} {py:.1f}" for k, (px, py) in enumerate(top_pts)),
                stroke=color,
                stroke_width=2.2,
            )
        )
        if show_values and not stacked:
            for i, (px, py) in enumerate(top_pts):
                prims.append(
                    Prim(
                        "text",
                        tx=px,
                        ty=py - 10,
                        content=fmt_number(levels[i][s]),
                        size=12,
                        weight=600,
                        fill=color,
                        anchor="middle",
                        halo=True,
                    )
                )
    if show_values and stacked:
        for i in range(n):
            total = levels[i][n_series - 1]
            prims.append(
                Prim(
                    "text",
                    tx=xs[i],
                    ty=bottom - (total / y_max) * plot_h - 10 if y_max > 0 else bottom,
                    content=fmt_number(total),
                    size=12.5,
                    weight=700,
                    fill=INK2,
                    anchor="middle",
                    halo=True,
                )
            )

    draw_legend(prims, [("rect", series_color(palette, s), name) for s, name in enumerate(series_names)], W)
    return h, prims


# ══ 柱状图（纵向分组 / 堆叠） ══


def _bar_v_prims(cfg: dict[str, Any]) -> tuple[float, list[Prim]]:
    series_names, rows = _series_frame(cfg)
    n_series = len(series_names)
    palette = cfg["theme"]["palette"]
    stacked = _style_flag(cfg, "stacked", False)
    show_values = _style_flag(cfg, "showValues", False)

    n = len(rows)
    h = 560.0 if n <= 10 else 92.0 + 46.0 * n
    pad_l, pad_r, pad_t, pad_b = 70.0, 30.0, 56.0, 78.0
    left, right = pad_l, W - pad_r
    plot_w, plot_h = right - left, h - pad_t - pad_b
    bottom = pad_t + plot_h

    vals = [_row_values(row, n_series) for row in rows]
    max_v = max((sum(v) if stacked else max(v, default=0.0) for v in vals), default=0.0)
    step, y_max = nice_axis(max_v)

    prims: list[Prim] = []
    _h_axis(prims, left, right, bottom, plot_h, y_max, step)
    prims.append(
        Prim(
            "text",
            tx=left - 10,
            ty=pad_t - 14,
            content=str(cfg["labels"].get("unitY", "")),
            size=12.5,
            fill=MUTED,
            anchor="end",
        )
    )

    slot = plot_w / max(n, 1)
    for i in range(n):
        cx = left + slot * (i + 0.5)
        if stacked:
            bar_w = min(56.0, slot * 0.52)
            acc = 0.0
            for s in range(n_series):
                v = vals[i][s]
                seg_h = (v / y_max) * plot_h if y_max > 0 else 0.0
                if seg_h > 0:
                    prims.append(
                        Prim(
                            "rect",
                            x=cx - bar_w / 2,
                            y=bottom - (acc / y_max) * plot_h - seg_h,
                            w=bar_w,
                            h=seg_h,
                            rx=1.5,
                            fill=series_color(palette, s),
                        )
                    )
                acc += v
            if show_values and acc > 0:
                prims.append(
                    Prim(
                        "text",
                        tx=cx,
                        ty=bottom - (acc / y_max) * plot_h - 9,
                        content=fmt_number(acc),
                        size=13,
                        weight=700,
                        fill=INK2,
                        anchor="middle",
                        halo=True,
                    )
                )
        else:
            group_w = min(84.0, slot * 0.72)
            bar_w = group_w / max(n_series, 1)
            for s in range(n_series):
                v = vals[i][s]
                bar_h = (v / y_max) * plot_h if y_max > 0 else 0.0
                x = cx - group_w / 2 + bar_w * s
                if bar_h > 0:
                    prims.append(
                        Prim("rect", x=x, y=bottom - bar_h, w=bar_w - 2, h=bar_h, rx=1.5, fill=series_color(palette, s))
                    )
                if show_values and n_series <= 4:
                    prims.append(
                        Prim(
                            "text",
                            tx=x + (bar_w - 2) / 2,
                            ty=bottom - bar_h - 8,
                            content=fmt_number(v),
                            size=11.5,
                            weight=600,
                            fill=series_color(palette, s),
                            anchor="middle",
                            halo=True,
                        )
                    )
        prims.append(
            Prim(
                "text",
                tx=cx,
                ty=bottom + 26,
                content=str(rows[i].get("label", "")),
                size=13,
                fill=INK2,
                anchor="middle",
            )
        )

    draw_legend(prims, [("rect", series_color(palette, s), name) for s, name in enumerate(series_names)], W)
    return h, prims


# ══ 饼图 / 环形图 ══


def _pie_prims(cfg: dict[str, Any]) -> tuple[float, list[Prim]]:
    rows = cfg["data"]["rows"]
    palette = cfg["theme"]["palette"]
    donut = _style_flag(cfg, "donut", False)
    show_percent = _style_flag(cfg, "showPercent", True)

    h = 520.0
    cx, cy = 330.0, 130.0 + (h - 130.0) / 2
    radius = min(180.0, (h - 150.0) / 2 + 40.0)
    inner_r = radius * 0.58 if donut else 0.0

    items = [(str(r.get("label", "")), float(r.get("value") or 0.0)) for r in rows]
    items = [(name, v) for name, v in items if v > 0]
    total = sum(v for _, v in items) or 1.0

    def pt(r: float, t: float) -> tuple[float, float]:
        return (cx + r * math.sin(t), cy - r * math.cos(t))

    prims: list[Prim] = []
    t0 = 0.0
    for idx, (_name, v) in enumerate(items):
        share = v / total
        t1 = t0 + share * 2 * math.pi
        color = series_color(palette, idx)
        segs = max(2, math.ceil(math.degrees(t1 - t0) / 6.0))
        outer = [pt(radius, t0 + (t1 - t0) * k / segs) for k in range(segs + 1)]
        if donut:
            inner = [pt(inner_r, t0 + (t1 - t0) * k / segs) for k in range(segs + 1)]
            pts = outer + inner[::-1] + [outer[0]]
        else:
            pts = [(cx, cy), *outer, (cx, cy)]
        d = " ".join(f"{'M' if k == 0 else 'L'} {px:.1f} {py:.1f}" for k, (px, py) in enumerate(pts))
        prims.append(Prim("path", d=d, fill=color, stroke=PAPER, stroke_width=1.5))

        mid = (t0 + t1) / 2
        if show_percent and share >= 0.055:
            lr = (inner_r + radius) / 2 if donut else radius * 0.68
            lx, ly = pt(lr, mid)
            prims.append(
                Prim(
                    "text",
                    tx=lx,
                    ty=ly + 5,
                    content=f"{share * 100:.1f}%",
                    size=13,
                    weight=600,
                    fill="#FFFFFF",
                    anchor="middle",
                )
            )
        t0 = t1

    if donut:
        prims.append(
            Prim("text", tx=cx, ty=cy + 2, content=fmt_number(total), size=30, weight=700, fill=INK2, anchor="middle")
        )
        prims.append(Prim("text", tx=cx, ty=cy + 26, content="合计", size=12.5, fill=MUTED, anchor="middle"))

    # 右侧图例清单：色块 + 名称 + 占比（+ 数值）
    lx = 620.0
    ly = cy - len(items) * 15.0 + 10.0
    for idx, (name, v) in enumerate(items):
        share = v / total
        prims.append(Prim("rect", x=lx, y=ly - 9, w=13, h=9, rx=1, fill=series_color(palette, idx)))
        desc = f"{share * 100:.1f}%" if show_percent else fmt_number(v)
        if show_percent:
            desc = f"{desc}　{fmt_number(v)}"
        prims.append(Prim("text", tx=lx + 22, ty=ly, content=f"{name}　{desc}", size=13.5, fill=INK2))
        ly += 30.0
    return h, prims


# ══ 散点图 ══


def _scatter_prims(cfg: dict[str, Any]) -> tuple[float, list[Prim]]:
    rows = cfg["data"]["rows"]
    palette = cfg["theme"]["palette"]
    show_trend = _style_flag(cfg, "showTrend", False)
    color = series_color(palette, 0)

    h = 560.0
    pad_l, pad_r, pad_t, pad_b = 70.0, 30.0, 40.0, 78.0
    left, right = pad_l, W - pad_r
    plot_w, plot_h = right - left, h - pad_t - pad_b
    bottom = pad_t + plot_h

    pts = [
        (float(r.get("x") or 0.0), float(r.get("y") or 0.0))
        for r in rows
        if r.get("x") is not None and r.get("y") is not None
    ]
    max_x = max((p[0] for p in pts), default=0.0)
    max_y = max((p[1] for p in pts), default=0.0)
    step_x, x_max = nice_axis(max_x)
    step_y, y_max = nice_axis(max_y)

    prims: list[Prim] = []
    _h_axis(prims, left, right, bottom, plot_h, y_max, step_y)
    prims.append(
        Prim(
            "text",
            tx=left - 10,
            ty=pad_t - 12,
            content=str(cfg["labels"].get("unitY", "")),
            size=12.5,
            fill=MUTED,
            anchor="end",
        )
    )

    # 横轴（数值刻度）
    v = 0.0
    while v <= x_max + 1e-9:
        gx = left + (v / x_max) * plot_w if x_max > 0 else left
        if v > 0:
            prims.append(Prim("line", x1=gx, y1=pad_t, x2=gx, y2=bottom, stroke=RULE, dash="3 5", opacity=0.55))
        prims.append(Prim("text", tx=gx, ty=bottom + 26, content=fmt_number(v), size=13, fill=MUTED, anchor="middle"))
        v += step_x
    prims.append(
        Prim(
            "text",
            tx=right,
            ty=bottom + 52,
            content=str(cfg["labels"].get("unitX", "")),
            size=12.5,
            fill=MUTED,
            anchor="end",
        )
    )

    for x, y in pts:
        px = left + (x / x_max) * plot_w if x_max > 0 else left
        py = bottom - (y / y_max) * plot_h if y_max > 0 else bottom
        prims.append(Prim("circle", cx=px, cy=py, r=5, fill=rgba_fill(color, 0.75), stroke=color, stroke_width=1.2))

    # 趋势参考线：最小二乘拟合，虚线画在图区范围内
    if show_trend and len(pts) >= 2:
        n = len(pts)
        sx = sum(p[0] for p in pts)
        sy = sum(p[1] for p in pts)
        sxx = sum(p[0] * p[0] for p in pts)
        sxy = sum(p[0] * p[1] for p in pts)
        denom = n * sxx - sx * sx
        if abs(denom) > 1e-12:
            slope = (n * sxy - sx * sy) / denom
            intercept = (sy - slope * sx) / n
            x1v = x_max if x_max > 0 else 1.0

            def trend_y(vx: float) -> float:
                """趋势线 y 值钳制在图区内（y_max 为 0 时贴底）."""
                clamped = min(max(intercept + slope * vx, 0.0), y_max)
                return bottom - (clamped / y_max) * plot_h if y_max > 0 else bottom

            prims.append(
                Prim(
                    "line",
                    x1=left,
                    y1=trend_y(0.0),
                    x2=left + plot_w,
                    y2=trend_y(x1v),
                    stroke=color,
                    stroke_width=1.6,
                    dash="6 4",
                    opacity=0.8,
                )
            )
    return h, prims


# ══ 雷达图 ══


def _radar_prims(cfg: dict[str, Any]) -> tuple[float, list[Prim]]:
    series_names, rows = _series_frame(cfg)
    n_series = len(series_names)
    palette = cfg["theme"]["palette"]
    fill = _style_flag(cfg, "fill", True)

    h = 560.0
    cx, cy = W / 2, 66.0 + (h - 66.0 - 46.0) / 2
    radius = 178.0
    n = max(len(rows), 3)

    max_v = 0.0
    for row in rows:
        for v in _row_values(row, n_series):
            max_v = max(max_v, v)
    if max_v <= 0:
        max_v = 1.0
    step = nice_step(max_v)
    grid_max = max(step, math.ceil(max_v / step) * step)

    def vertex(i: int, r: float) -> tuple[float, float]:
        t = 2 * math.pi * i / n - math.pi / 2
        return (cx + r * math.cos(t), cy + r * math.sin(t))

    prims: list[Prim] = []

    # 网格环 + 轴（实线略深，保证白底可见）
    for frac in (0.25, 0.5, 0.75, 1.0):
        ring = [vertex(i, radius * frac) for i in range(n)]
        d = " ".join(f"{'M' if k == 0 else 'L'} {px:.1f} {py:.1f}" for k, (px, py) in enumerate([*ring, ring[0]]))
        prims.append(Prim("path", d=d, stroke=RULE, dash="3 4"))
    for i in range(n):
        px, py = vertex(i, radius)
        prims.append(Prim("line", x1=cx, y1=cy, x2=px, y2=py, stroke=AXIS_LINE, opacity=0.6))
        if i < len(rows):
            lx, ly = vertex(i, radius + 26)
            anchor = "middle"
            if lx > cx + 12:
                anchor = "start"
            elif lx < cx - 12:
                anchor = "end"
            prims.append(
                Prim("text", tx=lx, ty=ly + 4, content=str(rows[i].get("label", "")), size=13, fill=INK2, anchor=anchor)
            )

    # 系列：先画全部填充再画描线 / 数据点，避免后画系列的填充覆盖先画系列的线
    polys: list[tuple[str, list[tuple[float, float]]]] = []
    for s in range(n_series):
        color = series_color(palette, s)
        poly = [vertex(i, radius * (_row_values(rows[i], n_series)[s] / grid_max)) for i in range(n) if i < len(rows)]
        if len(poly) >= 3:
            polys.append((color, poly))
    for color, poly in polys:
        d = " ".join(f"{'M' if k == 0 else 'L'} {px:.1f} {py:.1f}" for k, (px, py) in enumerate([*poly, poly[0]]))
        if fill:
            prims.append(Prim("path", d=d, fill=rgba_fill(color, 0.18)))
    for color, poly in polys:
        d = " ".join(f"{'M' if k == 0 else 'L'} {px:.1f} {py:.1f}" for k, (px, py) in enumerate([*poly, poly[0]]))
        prims.append(Prim("path", d=d, stroke=color, stroke_width=2.2))
        for px, py in poly:
            prims.append(Prim("circle", cx=px, cy=py, r=3.5, fill=PAPER, stroke=color, stroke_width=1.8))

    draw_legend(prims, [("line", series_color(palette, s), name) for s, name in enumerate(series_names)], W)
    return h, prims


# ══ 漏斗图 ══


def _funnel_prims(cfg: dict[str, Any]) -> tuple[float, list[Prim]]:
    rows = cfg["data"]["rows"]
    palette = cfg["theme"]["palette"]
    show_rates = _style_flag(cfg, "showRates", True)

    n = max(len(rows), 1)
    bar_h, gap = 42.0, 30.0
    pad_t, pad_b = 56.0, 50.0
    h = pad_t + pad_b + n * bar_h + (n - 1) * gap
    cx = W / 2
    max_w = 720.0

    vals = [float(r.get("value") or 0.0) for r in rows]
    max_v = max(vals, default=0.0) or 1.0

    prims: list[Prim] = []
    y = pad_t
    prev_half = None
    for i, row in enumerate(rows):
        name = str(row.get("label", ""))
        v = vals[i]
        half = max_w * (v / max_v) / 2
        color = series_color(palette, i)
        # 上一级 → 本级的连接带（梯形，画在柱下层）
        if prev_half is not None:
            band = rgba_fill(series_color(palette, i - 1), 0.16)
            d = (
                f"M {cx - prev_half:.1f} {y - gap:.1f} L {cx + prev_half:.1f} {y - gap:.1f} "
                f"L {cx + half:.1f} {y:.1f} L {cx - half:.1f} {y:.1f}"
            )
            prims.append(Prim("path", d=d, fill=band))
        if half > 0:
            prims.append(Prim("rect", x=cx - half, y=y, w=half * 2, h=bar_h, rx=3, fill=color))
            prims.append(
                Prim(
                    "text",
                    tx=cx,
                    ty=y + bar_h / 2 + 5,
                    content=fmt_number(v),
                    size=15,
                    weight=700,
                    fill="#FFFFFF",
                    anchor="middle",
                )
            )
        else:
            prims.append(
                Prim(
                    "text",
                    tx=cx,
                    ty=y + bar_h / 2 + 5,
                    content=fmt_number(v),
                    size=14,
                    weight=600,
                    fill=MUTED,
                    anchor="middle",
                )
            )
        # 阶段名（左）与转化率（右）
        prims.append(
            Prim("text", tx=cx - max_w / 2 - 16, ty=y + bar_h / 2 + 5, content=name, size=13.5, fill=INK2, anchor="end")
        )
        if show_rates and i > 0 and vals[i - 1] > 0:
            rate = v / vals[i - 1] * 100
            prims.append(
                Prim(
                    "text",
                    tx=cx + max_w / 2 + 16,
                    ty=y + bar_h / 2 + 5,
                    content=f"转化 {rate:.1f}%",
                    size=12.5,
                    fill=MUTED,
                )
            )
        prev_half = half
        y += bar_h + gap
    return h, prims


# ══ 仪表盘 ══


def _gauge_prims(cfg: dict[str, Any]) -> tuple[float, list[Prim]]:
    rows = cfg["data"]["rows"]
    palette = cfg["theme"]["palette"]
    labels = cfg["labels"]
    try:
        max_v = float(labels.get("max") or 100.0)
    except (TypeError, ValueError):
        max_v = 100.0
    if max_v <= 0:
        max_v = 100.0
    unit = str(labels.get("unit", ""))
    value = float(rows[0].get("value") or 0.0) if rows else 0.0
    frac = max(0.0, min(value / max_v, 1.0))
    color = series_color(palette, 0)

    h = 440.0
    cx, cy = W / 2, 292.0
    radius = 186.0
    # 弧度制：12 点钟为 -pi/2，顺时针扫 240°（4π/3）
    a0, sweep = -math.pi * 7 / 6, math.pi * 4 / 3

    def pt(r: float, t: float) -> tuple[float, float]:
        return (cx + r * math.cos(t), cy + r * math.sin(t))

    def arc_d(r: float, f0: float, f1: float) -> str:
        segs = max(2, math.ceil(math.degrees(sweep * (f1 - f0)) / 5.0))
        pts = [pt(r, a0 + sweep * (f0 + (f1 - f0) * k / segs)) for k in range(segs + 1)]
        return " ".join(f"{'M' if k == 0 else 'L'} {px:.1f} {py:.1f}" for k, (px, py) in enumerate(pts))

    prims: list[Prim] = []
    # 背景弧 + 数值弧（粗线）+ 刻度
    prims.append(Prim("path", d=arc_d(radius, 0.0, 1.0), stroke=RULE, stroke_width=18))
    if frac > 0:
        prims.append(Prim("path", d=arc_d(radius, 0.0, frac), stroke=color, stroke_width=18))
    for k in range(11):
        t = a0 + sweep * k / 10
        x0, y0 = pt(radius - 12, t)
        x1, y1 = pt(radius - 24 if k % 5 else radius - 30, t)
        prims.append(Prim("line", x1=x0, y1=y0, x2=x1, y2=y1, stroke=MUTED, stroke_width=1.2))
        if k % 5 == 0:
            tx, ty = pt(radius + 26, t)
            prims.append(
                Prim("text", tx=tx, ty=ty + 5, content=fmt_number(max_v * k / 10), size=13, fill=MUTED, anchor="middle")
            )

    # 指针 + 轴心
    nx, ny = pt(radius - 40, a0 + sweep * frac)
    prims.append(Prim("line", x1=cx, y1=cy, x2=nx, y2=ny, stroke=INK2, stroke_width=3))
    prims.append(Prim("circle", cx=cx, cy=cy, r=7, fill=PAPER, stroke=INK2, stroke_width=2))

    # 中心读数 + 指标名
    prims.append(
        Prim(
            "text",
            tx=cx,
            ty=cy + 78,
            content=f"{fmt_number(value)}{unit}",
            size=42,
            weight=700,
            fill=INK2,
            anchor="middle",
        )
    )
    name = str(rows[0].get("label", "")) if rows else ""
    if name:
        prims.append(Prim("text", tx=cx, ty=cy + 112, content=name, size=14, fill=MUTED, anchor="middle"))
    prims.append(
        Prim(
            "text",
            tx=cx,
            ty=cy + 140,
            content=f"量程 0–{fmt_number(max_v)}{unit}",
            size=12,
            fill=MUTED,
            anchor="middle",
        )
    )
    return h, prims


# ══ 树状图 ══


def _worst_row(items: list[tuple[int, float]], side: float) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """squarified 贪心取行：继续放只会更差时停（值先按区域面积归一化）."""

    def worst(row: list[tuple[int, float]]) -> float:
        s = sum(v for _, v in row)
        if s <= 0 or not row:
            return float("inf")
        vs = [v for _, v in row]
        mx, mn = max(vs), min(vs)
        return max(side * side * mx / (s * s), s * s / (side * side * mn))

    row = [items[0]]
    for item in items[1:]:
        if worst([*row, item]) <= worst(row):
            row.append(item)
        else:
            break
    return row, items[len(row) :]


def _squarify(values: list[float], x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """squarified 树状图切分：返回与 ``values`` 同序的 (x, y, w, h) 矩形.

    值先归一化到区域面积（``w × h``），零值项返回零面积矩形占位。
    """
    total = sum(values)
    if total <= 0 or w <= 0 or h <= 0:
        return [(x, y, 0.0, 0.0)] * len(values)
    scale = w * h / total
    items = sorted(
        ((i, v * scale) for i, v in enumerate(values) if v > 0),
        key=lambda t: t[1],
        reverse=True,
    )
    rects: list[tuple[float, float, float, float] | None] = [None] * len(values)
    px, py, pw, ph = x, y, w, h
    queue = items
    while queue:
        if pw >= ph:
            row, queue = _worst_row(queue, ph)
            rw = sum(v for _, v in row) / ph if ph > 0 else 0.0
            yy = py
            for idx, v in row:
                rh = v / rw if rw > 0 else 0.0
                rects[idx] = (px, yy, rw, rh)
                yy += rh
            px += rw
            pw -= rw
        else:
            row, queue = _worst_row(queue, pw)
            rh = sum(v for _, v in row) / pw if pw > 0 else 0.0
            xx = px
            for idx, v in row:
                rw = v / rh if rh > 0 else 0.0
                rects[idx] = (xx, py, rw, rh)
                xx += rw
            py += rh
            ph -= rh
    return [r if r is not None else (x, y, 0.0, 0.0) for r in rects]


def _treemap_prims(cfg: dict[str, Any]) -> tuple[float, list[Prim]]:
    rows = cfg["data"]["rows"]
    palette = cfg["theme"]["palette"]
    show_values = _style_flag(cfg, "showValues", True)

    h = 560.0
    x0, y0, tw, th = 8.0, 48.0, W - 16.0, h - 56.0

    items = [(str(r.get("label", "")), float(r.get("value") or 0.0)) for r in rows]
    total = sum(v for _, v in items) or 1.0
    rects = _squarify([v for _, v in items], x0, y0, tw, th)

    prims: list[Prim] = []
    for idx, (name, v) in enumerate(items):
        rx, ry, rw, rh = rects[idx]
        if rw <= 0 or rh <= 0:
            continue
        color = series_color(palette, idx)
        prims.append(Prim("rect", x=rx + 1, y=ry + 1, w=max(rw - 2, 0), h=max(rh - 2, 0), rx=2, fill=color))
        share = v / total * 100
        value_text = f"{fmt_number(v)}（{share:.1f}%）" if show_values else f"{share:.1f}%"
        if rw >= 76 and rh >= 48:
            prims.append(Prim("text", tx=rx + 10, ty=ry + 22, content=name, size=13.5, weight=600, fill="#FFFFFF"))
            prims.append(
                Prim("text", tx=rx + 10, ty=ry + 42, content=value_text, size=12.5, fill="rgba(255,255,255,.88)")
            )
        elif rw >= 44 and rh >= 26:
            prims.append(
                Prim(
                    "text",
                    tx=rx + rw / 2,
                    ty=ry + rh / 2 + 5,
                    content=f"{share:.1f}%",
                    size=12,
                    weight=600,
                    fill="#FFFFFF",
                    anchor="middle",
                )
            )
    return h, prims


# ══ 热力图 ══


def _heatmap_prims(cfg: dict[str, Any]) -> tuple[float, list[Prim]]:
    series_names, rows = _series_frame(cfg)
    n_cols = len(series_names)
    palette = cfg["theme"]["palette"]
    base = series_color(palette, 0)

    n = max(len(rows), 1)
    pad_l, pad_r, pad_t, pad_b = 108.0, 24.0, 76.0, 92.0
    plot_w = W - pad_l - pad_r
    cell_w = plot_w / max(n_cols, 1)
    cell_h = min(46.0, (560.0 - pad_t - pad_b) / n)
    h = pad_t + pad_b + cell_h * n

    vals = [_row_values(row, n_cols) for row in rows]
    flat = [v for row_v in vals for v in row_v]
    v_min = min(flat, default=0.0)
    v_max = max(flat, default=0.0)
    span = v_max - v_min if v_max > v_min else 1.0

    prims: list[Prim] = []
    for j, name in enumerate(series_names):
        prims.append(
            Prim(
                "text",
                tx=pad_l + cell_w * (j + 0.5),
                ty=pad_t - 14,
                content=name,
                size=12.5,
                fill=MUTED,
                anchor="middle",
            )
        )
    for i, row in enumerate(rows):
        y = pad_t + cell_h * i
        prims.append(
            Prim(
                "text",
                tx=pad_l - 12,
                ty=y + cell_h / 2 + 5,
                content=str(row.get("label", "")),
                size=13,
                fill=INK2,
                anchor="end",
            )
        )
        for j in range(n_cols):
            v = vals[i][j]
            t = (v - v_min) / span
            x = pad_l + cell_w * j
            prims.append(
                Prim(
                    "rect",
                    x=x + 1,
                    y=y + 1,
                    w=max(cell_w - 2, 0),
                    h=max(cell_h - 2, 0),
                    rx=2,
                    fill=rgba_fill(base, 0.08 + 0.82 * t),
                )
            )
            if cell_w >= 46 and cell_h >= 26:
                prims.append(
                    Prim(
                        "text",
                        tx=x + cell_w / 2,
                        ty=y + cell_h / 2 + 5,
                        content=fmt_number(v),
                        size=12,
                        fill=INK2,
                        anchor="middle",
                    )
                )

    # 底部色阶条（浅 → 深）
    bar_w, bar_h = 260.0, 12.0
    bx, by = (W - bar_w) / 2, h - pad_b + 34.0
    steps = 12
    for k in range(steps):
        prims.append(
            Prim(
                "rect",
                x=bx + bar_w * k / steps,
                y=by,
                w=bar_w / steps,
                h=bar_h,
                fill=rgba_fill(base, 0.08 + 0.82 * k / (steps - 1)),
            )
        )
    prims.append(Prim("text", tx=bx - 10, ty=by + 10, content=fmt_number(v_min), size=12, fill=MUTED, anchor="end"))
    prims.append(Prim("text", tx=bx + bar_w + 10, ty=by + 10, content=fmt_number(v_max), size=12, fill=MUTED))
    return h, prims


#: 模板 key → 布局函数（标准类型；预设模板共享布局，差异在 default_config）
LAYOUTS: dict[str, Any] = {}
for _keys, _fn in (
    (("line-business", "line-classic", "line-vivid"), _line_prims),
    (("area-business", "area-classic", "area-stacked"), _area_prims),
    (("bar-business", "bar-classic", "bar-stacked"), _bar_v_prims),
    (("pie-business", "pie-classic", "pie-donut"), _pie_prims),
    (("scatter-business", "scatter-classic", "scatter-trend"), _scatter_prims),
    (("radar-business", "radar-classic", "radar-fill"), _radar_prims),
    (("funnel-business", "funnel-classic", "funnel-vivid"), _funnel_prims),
    (("gauge-business", "gauge-classic", "gauge-vivid"), _gauge_prims),
    (("treemap-business", "treemap-classic", "treemap-vivid"), _treemap_prims),
    (("heatmap-business", "heatmap-classic", "heatmap-vivid"), _heatmap_prims),
):
    for _key in _keys:
        LAYOUTS[_key] = _fn

__all__ = ["LAYOUTS"]
