"""图表 PNG 写端（ADR 0048 D1 / D6）：同一批图元用 Pillow 光栅化.

- 只做序列化，不做几何计算（与 SVG 写端像素语义一致：同坐标、同配色、同文本）；
- 颜色令牌（``var(--x, #hex)`` / ``rgba(...)``）解析为回退十六进制并按透明度
  向纸色混合 —— 固定浅色纸底的打印口径（边界 6）；
- CJK 字体复用 ``export/pdf_fonts.py`` 的候选发现链，不建第三条字体链。
"""

from __future__ import annotations

import io
import math
import re
from typing import TYPE_CHECKING

from cndb.plugins.documents.services.charts.primitives import ChartDocument, parse_path_points

if TYPE_CHECKING:
    from PIL.ImageDraw import ImageDraw

#: 默认输出倍率（DOCX / PDF 导出用 2 倍分辨率，D6）
DEFAULT_SCALE = 2

_VAR_RE = re.compile(r"var\(--[^,]+,\s*(#[0-9A-Fa-f]{3,8})\s*\)")
_RGBA_RE = re.compile(r"rgba?\(([^)]+)\)")

_font_cache: dict[tuple[str, int | None], dict[int, object]] = {}
_font_loaded: list[tuple[str, int | None] | None] = [None]


def resolve_color(color: str, paper: str = "#FBFAF5") -> str:
    """把图元颜色解析为不透明十六进制（打印口径）."""
    if not color:
        return "#000000"
    m = _VAR_RE.search(color)
    if m:
        color = m.group(1)
    if color.startswith("#"):
        if len(color) == 4:
            color = "#" + "".join(ch * 2 for ch in color[1:])
        return color[:7]
    m = _RGBA_RE.match(color)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        try:
            r, g, b = (int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
            alpha = float(parts[3]) if len(parts) > 3 else 1.0
        except (ValueError, IndexError):
            return "#000000"
        pr, pg, pb = int(paper[1:3], 16), int(paper[3:5], 16), int(paper[5:7], 16)

        def mix(c: float, p: float) -> int:
            return round(c * alpha + p * (1 - alpha))

        return f"#{mix(r, pr):02X}{mix(g, pg):02X}{mix(b, pb):02X}"
    return "#000000"


def _load_font(size: int) -> object | None:
    """按尺寸取 PIL 字体（CJK 候选链懒加载 + 缓存）；全部失败回退默认字体."""
    from PIL import ImageFont

    if _font_loaded[0] is None:
        from cndb.plugins.documents.services.export.pdf_fonts import _cjk_font_candidates

        for _name, path, index in _cjk_font_candidates():
            if not path or path.lower().endswith(".otf"):
                continue
            try:
                ImageFont.truetype(path, 12, index=index or 0)
                _font_loaded[0] = (path, index)
                break
            except Exception:
                continue
    spec = _font_loaded[0]
    if spec is None:
        return None
    path, index = spec
    bucket = _font_cache.setdefault(spec, {})
    if size not in bucket:
        try:
            bucket[size] = ImageFont.truetype(path, size, index=index or 0)
        except Exception:
            return None
    return bucket[size]


def _dashed_line(draw: ImageDraw, x1: float, y1: float, x2: float, y2: float, dash: str, width: int, fill: str) -> None:
    """按 ``"on off"`` 节奏画虚线（Pillow 无原生 dash）."""
    try:
        on_s, off_s = dash.split()
        on, off = float(on_s), float(off_s)
    except ValueError:
        on, off = 3.0, 5.0
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    if dist <= 0:
        return
    ux, uy = dx / dist, dy / dist
    t = 0.0
    line = draw.line  # type: ignore[attr-defined]
    while t < dist:
        t2 = min(t + on, dist)
        line([(x1 + ux * t, y1 + uy * t), (x1 + ux * t2, y1 + uy * t2)], fill=fill, width=width)
        t = t2 + off


def to_png(doc: ChartDocument, scale: int = DEFAULT_SCALE) -> bytes:
    """整幅图 → PNG 字节（DOCX / PDF 导出通道）."""
    from PIL import Image, ImageDraw

    paper = "#FBFAF5"
    # 纸色取自第一个全幅背景矩形（若有）
    for p in doc.elements:
        if p.kind == "rect" and p.w >= doc.width - 1:
            paper = resolve_color(p.fill, "#FBFAF5")
            break

    w, h = round(doc.width * scale), round(doc.height * scale)
    img = Image.new("RGB", (max(1, w), max(1, h)), paper)
    draw = ImageDraw.Draw(img)

    for p in doc.elements:
        if p.kind == "rect" and p.w >= doc.width - 1:
            continue  # 背景已在建图时铺
        fill = resolve_color(p.fill, paper) if p.fill and p.fill != "none" else None
        stroke = resolve_color(p.stroke, paper) if p.stroke else None
        if p.kind == "rect":
            box = [p.x * scale, p.y * scale, (p.x + p.w) * scale, (p.y + p.h) * scale]
            sw = max(1, round(p.stroke_width * scale)) if p.stroke_width and stroke else 0
            if p.rx >= 1:
                draw.rounded_rectangle(box, radius=p.rx * scale, fill=fill, outline=stroke, width=sw if stroke else 0)
            else:
                draw.rectangle(box, fill=fill, outline=stroke, width=sw if stroke else 0)
        elif p.kind == "line":
            color = stroke or fill or "#000000"
            width = max(1, round(p.stroke_width * scale))
            if p.dash:
                _dashed_line(draw, p.x1 * scale, p.y1 * scale, p.x2 * scale, p.y2 * scale, p.dash, width, color)
            else:
                draw.line([(p.x1 * scale, p.y1 * scale), (p.x2 * scale, p.y2 * scale)], fill=color, width=width)
        elif p.kind == "circle":
            r = p.r * scale
            box = [p.cx * scale - r, p.cy * scale - r, p.cx * scale + r, p.cy * scale + r]
            draw.ellipse(box, fill=fill, outline=stroke, width=max(1, round(p.stroke_width * scale)) if stroke else 0)
        elif p.kind == "path" and p.d:
            pts = [(x * scale, y * scale) for x, y in parse_path_points(p.d)]
            if len(pts) >= 2:
                # 填充路径（面积 / 雷达 / 饼图扇形，需求卡片 0070）；无填充保持折线
                if fill is not None:
                    draw.polygon(pts, fill=fill, outline=stroke)
                else:
                    draw.line(pts, fill=stroke or "#000000", width=max(1, round(p.stroke_width * scale)), joint="curve")
        elif p.kind == "text":
            size = round(p.size * scale)
            font = _load_font(size)
            color = fill or "#000000"
            text = p.content
            if not text:
                continue
            if font is not None:
                tw = draw.textlength(text, font=font)  # type: ignore[attr-defined]
                ascent, _descent = font.getmetrics()  # type: ignore[attr-defined]
            else:
                tw, ascent = size * len(text) * 0.6, size
            if p.anchor == "middle":
                x = p.tx * scale - tw / 2
            elif p.anchor == "end":
                x = p.tx * scale - tw
            else:
                x = p.tx * scale
            baseline_y = p.ty * scale
            if p.plate is not None:
                px, py, pw, ph = p.plate
                draw.rounded_rectangle(
                    [px * scale, py * scale, (px + pw) * scale, (py + ph) * scale],
                    radius=2 * scale,
                    fill=paper,
                    outline="#E0D9C8",
                    width=1,
                )
            stroke_kwargs: dict[str, object] = {}
            if p.halo:
                stroke_kwargs = {"stroke_fill": paper, "stroke_width": max(1, 2 * scale // 2)}
            if font is not None:
                draw.text((x, baseline_y - ascent), text, font=font, fill=color, **stroke_kwargs)  # type: ignore[arg-type]
            else:
                draw.text((x, baseline_y - ascent), text, fill=color, **stroke_kwargs)  # type: ignore[arg-type]

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


__all__ = ["DEFAULT_SCALE", "resolve_color", "to_png"]
