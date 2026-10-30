"""图表 SVG 写端（ADR 0048 D1）：共享图元 → SVG 字符串.

- 无脚本、无外链、无 ``<style>`` 标签（内联进宿主 DOM 不泄漏样式）；
- 字体用字族串，中性色带 ``var(--cn-*, #hex)`` 回退，跟随前端明暗主题（边界 6）。
"""

from __future__ import annotations

import math
from xml.sax.saxutils import escape, quoteattr

from cndb.plugins.documents.services.charts.render import (
    FONT_FAMILY,
    ChartDocument,
    Prim,
)

MONO_FAMILY = "Consolas, Menlo, 'Courier New', monospace"


def _num(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".") if not math.isnan(v) and not math.isinf(v) else "0"


def _opacity_attrs(p: Prim) -> str:
    return f' opacity="{p.opacity}"' if p.opacity is not None else ""


def _prim_svg(p: Prim) -> str:
    if p.kind == "rect":
        attrs = [
            f'x="{_num(p.x)}"',
            f'y="{_num(p.y)}"',
            f'width="{_num(p.w)}"',
            f'height="{_num(p.h)}"',
        ]
        if p.rx > 0:
            attrs.append(f'rx="{_num(p.rx)}"')
        if p.fill:
            attrs.append(f'fill="{p.fill}"')
        if p.stroke:
            attrs.append(f'stroke="{p.stroke}"')
        if p.stroke_width:
            attrs.append(f'stroke-width="{_num(p.stroke_width)}"')
        return f"<rect {' '.join(attrs)}/>"
    if p.kind == "line":
        attrs = [
            f'x1="{_num(p.x1)}"',
            f'y1="{_num(p.y1)}"',
            f'x2="{_num(p.x2)}"',
            f'y2="{_num(p.y2)}"',
        ]
        if p.stroke:
            attrs.append(f'stroke="{p.stroke}"')
        if p.stroke_width != 1:
            attrs.append(f'stroke-width="{_num(p.stroke_width)}"')
        if p.dash:
            attrs.append(f'stroke-dasharray="{p.dash}"')
        return f"<line {' '.join(attrs)}{_opacity_attrs(p)}/>"
    if p.kind == "circle":
        return (
            f'<circle cx="{_num(p.cx)}" cy="{_num(p.cy)}" r="{_num(p.r)}" '
            f'fill="{p.fill}" stroke="{p.stroke}" stroke-width="{_num(p.stroke_width)}"/>'
        )
    if p.kind == "path":
        # 填充路径（面积 / 雷达 / 饼图扇形，需求卡片 0070）：fill 为空保持描线语义
        return (
            f'<path d="{p.d}" fill="{p.fill or "none"}" stroke="{p.stroke or "none"}" '
            f'stroke-width="{_num(p.stroke_width)}" stroke-linejoin="round" stroke-linecap="round"/>'
        )
    if p.kind == "text":
        parts: list[str] = []
        if p.plate is not None:
            px, py, pw, ph = p.plate
            parts.append(
                f'<rect x="{_num(px)}" y="{_num(py)}" width="{_num(pw)}" height="{_num(ph)}" rx="2.5" '
                'fill="var(--cn-bg-container, #FBFAF5)" stroke="#E0D9C8" stroke-width="0.8"/>'
            )
        attrs = [
            f'x="{_num(p.tx)}"',
            f'y="{_num(p.ty)}"',
            f'font-family="{MONO_FAMILY if p.mono else FONT_FAMILY}"',
            f'font-size="{_num(p.size)}"',
        ]
        if p.weight != 400:
            attrs.append(f'font-weight="{p.weight}"')
        if p.fill:
            attrs.append(f'fill="{p.fill}"')
        if p.anchor != "start":
            attrs.append(f'text-anchor="{p.anchor}"')
        if p.halo:
            attrs.append('paint-order="stroke"')
            attrs.append('stroke="var(--cn-bg-container, #FBFAF5)"')
            attrs.append('stroke-width="4"')
            attrs.append('stroke-linejoin="round"')
        parts.append(f"<text {' '.join(attrs)}>{escape(p.content)}</text>")
        return "".join(parts)
    return ""


def to_svg(doc: ChartDocument) -> str:
    """整幅图 → SVG 字符串（含 aria 标题，可独立成文件）."""
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {_num(doc.width)} {_num(doc.height)}" width="100%" role="img" '
        f"aria-label={quoteattr(doc.label)}>",
        f"<title>{escape(doc.label)}</title>",
    ]
    parts.extend(_prim_svg(p) for p in doc.elements)
    parts.append("</svg>")
    return "".join(parts)


__all__ = ["to_svg"]
