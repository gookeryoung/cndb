"""极简 SVG 拼装工具（帮助图示构建器共用，ADR 0030 §1）.

设计要点：

- **不引第三方绘图库**：帮助图示都是结构图 / 流程图 / 数据预览图，用 30 行
  拼装原语足够，也避免给后端加 matplotlib 这类重依赖。
- **颜色只走设计令牌**：`fill="var(--cn-*)"/stroke` 带十六进制回退值，前端把
  SVG 内联进 DOM 后自动跟随浅色 / 暗色主题，后端不维护第二套调色板。
- **零 `<style>` 标签**：避免内联 SVG 的样式泄漏到宿主页面，属性一律行内。
"""

from __future__ import annotations

import math
from xml.sax.saxutils import escape, quoteattr

# 画布逻辑宽度：正文栏最大宽度约 720，640 留出左右呼吸
WIDTH = 640

FONT = "-apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"

TEXT = "var(--cn-text-primary, #1f2937)"
MUTED = "var(--cn-text-muted, #6b7280)"
BORDER = "var(--cn-border, #e5e7eb)"
SURFACE = "var(--cn-bg-container, #ffffff)"
SUBTLE = "var(--cn-bg-subtle, #fafafa)"
BRAND = "var(--cn-brand-color, #1677ff)"


def text_width(content: str, size: float) -> float:
    """估算文本渲染宽度（CJK 按 1 字宽、ASCII 按 0.55 字宽）."""
    total = 0.0
    for ch in content:
        total += size * (1.0 if ord(ch) > 0x2E7F else 0.55)
    return total


def truncate(content: str, size: float, max_width: float) -> str:
    """按估算宽度截断并补省略号（用于表格单元格）."""
    if text_width(content, size) <= max_width:
        return content
    ellipsis = "…"
    budget = max_width - text_width(ellipsis, size)
    out = ""
    for ch in content:
        if text_width(out + ch, size) > budget:
            break
        out += ch
    return out + ellipsis


class Svg:
    """一块定宽画布；按调用顺序累积元素."""

    def __init__(self, height: int, *, width: int = WIDTH) -> None:
        self.width = width
        self.height = max(1, int(height))
        self._parts: list[str] = []

    # ── 图元 ──

    def raw(self, markup: str) -> Svg:
        self._parts.append(markup)
        return self

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        rx: float = 8,
        fill: str = SURFACE,
        stroke: str | None = BORDER,
        dash: str | None = None,
    ) -> Svg:
        attrs = [f'x="{x:.1f}"', f'y="{y:.1f}"', f'width="{w:.1f}"', f'height="{h:.1f}"', f'rx="{rx}"']
        if fill:
            attrs.append(f'fill="{fill}"')
        if stroke:
            attrs.append(f'stroke="{stroke}"')
        if dash:
            attrs.append(f'stroke-dasharray="{dash}"')
        self._parts.append(f"<rect {' '.join(attrs)}/>")
        return self

    def text(
        self,
        x: float,
        y: float,
        content: str,
        *,
        size: float = 13,
        fill: str = TEXT,
        weight: int = 400,
        anchor: str = "start",
    ) -> Svg:
        self._parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{escape(content)}</text>'
        )
        return self

    def line(self, x1: float, y1: float, x2: float, y2: float, *, color: str = BORDER, width: float = 1) -> Svg:
        self._parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{width}"/>'
        )
        return self

    def arrow(self, x1: float, y1: float, x2: float, y2: float, *, color: str = BRAND, width: float = 1.4) -> Svg:
        """直线 + 实心三角箭头（不用 marker，避免多图内联时 id 冲突）."""
        head = 6.0
        angle = math.atan2(y2 - y1, x2 - x1)
        bx = x2 - head * math.cos(angle)
        by = y2 - head * math.sin(angle)
        left = (bx + head * 0.45 * math.sin(angle), by - head * 0.45 * math.cos(angle))
        right = (bx - head * 0.45 * math.sin(angle), by + head * 0.45 * math.cos(angle))
        self.line(x1, y1, bx, by, color=color, width=width)
        self._parts.append(
            f'<polygon points="{x2:.1f},{y2:.1f} {left[0]:.1f},{left[1]:.1f} {right[0]:.1f},{right[1]:.1f}" '
            f'fill="{color}"/>'
        )
        return self

    def chip(
        self,
        x: float,
        y: float,
        content: str,
        *,
        size: float = 12,
        height: float = 26,
        pad: float = 10,
        fill: str = SUBTLE,
        stroke: str = BORDER,
        color: str = TEXT,
        weight: int = 400,
    ) -> float:
        """画一枚圆角标签，返回占用宽度（便于回车换行计算）."""
        width = text_width(content, size) + pad * 2
        self.rect(x, y, width, height, rx=height / 2, fill=fill, stroke=stroke)
        self.text(
            x + width / 2, y + height / 2 + size * 0.36, content, size=size, fill=color, weight=weight, anchor="middle"
        )
        return width

    # ── 输出 ──

    def render(self, *, title: str, desc: str = "") -> str:
        label = quoteattr(title)
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" '
            f'width="100%" role="img" aria-label={label} data-help-figure="1">',
            f"<title>{escape(title)}</title>",
        ]
        if desc:
            parts.append(f"<desc>{escape(desc)}</desc>")
        parts.extend(self._parts)
        parts.append("</svg>")
        return "".join(parts)


__all__ = [
    "BORDER",
    "BRAND",
    "FONT",
    "MUTED",
    "SUBTLE",
    "SURFACE",
    "TEXT",
    "WIDTH",
    "Svg",
    "text_width",
    "truncate",
]
