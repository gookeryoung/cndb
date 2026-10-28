"""图表渲染管线（ADR 0048）单测.

覆盖：唯一渲染入口 render_chart（三模板 + 垃圾 config 不崩）、SVG 写端
（无脚本无外链、标题转义）、PNG 写端（PIL 光栅化 + 倍率）、降级整幅图、
``{cagr}`` token 求值（D11）、resolve_color 的 var/rgba 解析（边界 6）。
"""

from __future__ import annotations

import pytest

from cndb.plugins.documents.services.charts.raster import resolve_color, to_png
from cndb.plugins.documents.services.charts.registry import CHART_TEMPLATES
from cndb.plugins.documents.services.charts.render import (
    SHEET_WIDTH,
    BadRequestTemplateError,
    render_chart,
    render_degraded,
)
from cndb.plugins.documents.services.charts.svg import to_svg

TPL_KEYS = ("bar-line-dual-axis", "stacked-bar-horizontal", "grouped-bar-horizontal")


def _render_svg(key: str, config: dict | None = None) -> str:
    return to_svg(render_chart(key, config if config is not None else CHART_TEMPLATES[key].default_config))


class TestRenderChart:
    @pytest.mark.parametrize("template_key", TPL_KEYS)
    def test_three_templates_render_sheet(self, template_key: str):
        doc = render_chart(template_key, CHART_TEMPLATES[template_key].default_config)
        assert doc.width == SHEET_WIDTH
        assert doc.height > 100
        kinds = {p.kind for p in doc.elements}
        assert {"rect", "line", "text"} <= kinds
        # 背景矩形在收尾时补齐整幅高度
        assert doc.elements[0].h == doc.height

    @pytest.mark.parametrize("template_key", TPL_KEYS)
    def test_empty_config_falls_back_to_defaults(self, template_key: str):
        """空 config（设计器初稿）不崩，按模板默认行渲染（I6 回退）."""
        doc = render_chart(template_key, {})
        assert doc.elements
        svg = to_svg(doc)
        assert "<svg" in svg

    def test_garbage_config_never_raises(self):
        assert render_chart("bar-line-dual-axis", None).elements
        assert render_chart("stacked-bar-horizontal", "junk").elements

    def test_unknown_template_raises_controlled(self):
        with pytest.raises(BadRequestTemplateError):
            render_chart("gone", {})

    def test_many_rows_expand_canvas(self):
        """行数超基线时布局加高画布（堆叠 >8 行 / 分组 >10 行）."""
        rows = [{"label": f"R{i}", "values": [10, 20]} for i in range(12)]
        tall = render_chart("stacked-bar-horizontal", {"data": {"rows": rows}})
        base = render_chart("stacked-bar-horizontal", CHART_TEMPLATES["stacked-bar-horizontal"].default_config)
        assert tall.height > base.height


class TestSvgWriter:
    def test_svg_header_and_no_script_no_links(self):
        svg = _render_svg("bar-line-dual-axis")
        assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
        assert "<title>" in svg
        assert "<script" not in svg
        assert "href" not in svg
        assert "<style" not in svg
        assert svg.endswith("</svg>")

    def test_svg_carries_caption_text(self):
        svg = _render_svg("bar-line-dual-axis")
        assert "产业营业收入与增速（2020—2030年）" in svg
        assert "图 2-1" in svg

    def test_svg_tokens_follow_theme_variables(self):
        svg = _render_svg("bar-line-dual-axis")
        # 纸底 rect 用主题令牌（SVG 跟随前端明暗主题，边界 6）
        assert 'fill="var(--cn-bg-container, #FBFAF5)"' in svg

    def test_projected_band_and_derived_growth_present(self):
        """规划期分界与派生增速（测算期无 growth 输入 → 按主值推算）."""
        svg = _render_svg("bar-line-dual-axis")
        assert "规划期（测算值）" in svg
        assert "12.8%" in svg  # 285 → 520 五年复合增速

    def test_actual_segment_growth_derived_when_empty(self):
        """ADR 0056：次值留空时实际段也按主值推算，增长曲线不缺段."""
        svg = _render_svg("bar-line-dual-axis")  # 默认 11 行 growth 全空
        assert "19.7%" in svg  # 实际段 132 → 158
        assert "12.8%" in svg  # 测算段推算
        # 全部次值点连续成线（10 个折线点：i=1..10）
        assert svg.count("<circle") >= 10

    def test_growth_labels_avoid_bars_and_value_labels(self):
        """次值标签避让：不与柱体填充区 / 柱顶主值标签相交，且全部带纸色 halo."""
        doc = render_chart("bar-line-dual-axis", CHART_TEMPLATES["bar-line-dual-axis"].default_config)

        def width(text: str, size: float = 14.5) -> float:
            from cndb.plugins.documents.services.charts.render import text_width

            return text_width(text, size)

        def hits(a, b):
            return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]

        # 只取柱体矩形：排除规划期底色带（整片浅色 rect）与纸底
        bars = [
            p
            for p in doc.elements
            if p.kind == "rect"
            and p.h
            and p.h > 5
            and p.fill not in (None, "var(--cn-bg-container, #FBFAF5)", "rgba(30,61,87,.045)")
        ]
        value_labels = [p for p in doc.elements if p.kind == "text" and p.weight == 600]
        growth_labels = [p for p in doc.elements if p.kind == "text" and p.weight == 700 and p.content.endswith("%")]
        assert growth_labels
        # 解析折线 path d，重建折线几何（数据点 + 段）
        import re as _re

        path = next(p for p in doc.elements if p.kind == "path" and p.d and p.stroke)
        coords = [(float(a), float(b)) for a, b in _re.findall(r"[ML] ?([\d.]+) ([\d.]+)", path.d)]
        assert len(coords) >= 10
        for gl in growth_labels:
            lw = width(gl.content, gl.size)
            bbox = (gl.tx - lw / 2, gl.ty - gl.size, lw, gl.size * 1.4)
            assert gl.halo, gl.content
            assert not gl.plate  # 底板压柱降级已废除
            for bar in bars:
                assert not hits(bbox, (bar.x, bar.y, bar.w, bar.h)), gl.content
            for vl in value_labels:
                vw = width(vl.content, vl.size)
                assert not hits(bbox, (vl.tx - vw / 2, vl.ty - vl.size, vw, vl.size * 1.3)), gl.content
            # 不得压增长折线段与数据点标记（解析 path d 重建折线几何）
            for cx, cy in coords:
                assert not hits(bbox, (cx - 8, cy - 8, 16, 16)), gl.content
            for j in range(1, len(coords)):
                sx0, sy0 = coords[j - 1]
                sx1, sy1 = coords[j]
                seg = (min(sx0, sx1) - 5, min(sy0, sy1) - 5, abs(sx1 - sx0) + 10, abs(sy1 - sy0) + 10)
                assert not hits(bbox, seg), gl.content
        # 相邻增长率标签互不重叠
        placed = []
        for gl in growth_labels:
            lw = width(gl.content, gl.size)
            bbox = (gl.tx - lw / 2, gl.ty - gl.size, lw, gl.size * 1.4)
            for other in placed:
                assert not hits(bbox, other), gl.content
            placed.append(bbox)

    def test_growth_labels_dense_extreme_never_crash(self):
        """极端数据（柱满高 + 高增速）渲染不崩且标签仍有 halo."""
        cfg = {
            "data": {
                "actualCount": 3,
                "rows": [{"label": str(2020 + i), "value": 100 + i * 50, "growth": 5.0 + i * 8} for i in range(11)],
            }
        }
        svg = _render_svg("bar-line-dual-axis", cfg)
        assert svg.count('paint-order="stroke"') >= 10


class TestCagrToken:
    def test_cagr_evaluated_in_note(self):
        cfg = CHART_TEMPLATES["bar-line-dual-axis"].default_config
        svg = _render_svg("bar-line-dual-axis", cfg)
        assert "2026—2030年营业收入年均增速12.8%" in svg
        assert "{cagr}" not in svg

    def test_unknown_token_kept_verbatim(self):
        cfg = {
            "caption": {"note": "增速{cagr}，其他{nope}"},
            "data": {
                "actualCount": 1,
                "rows": [
                    {"label": "2025", "value": 100, "growth": None},
                    {"label": "2026", "value": 110, "growth": None},
                ],
            },
        }
        svg = _render_svg("bar-line-dual-axis", cfg)
        assert "{nope}" in svg

    def test_cagr_without_projected_rows_is_dash(self):
        cfg = {
            "caption": {"note": "增速{cagr}"},
            "data": {"actualCount": 2, "rows": [{"label": "A", "value": 1}, {"label": "B", "value": 2}]},
        }
        svg = _render_svg("bar-line-dual-axis", cfg)
        assert "增速—" in svg


class TestDegraded:
    def test_degraded_placeholder(self):
        doc = render_degraded(7, "[图表引用无效：模板已下线]")
        assert (doc.width, doc.height) == (640.0, 180.0)
        svg = to_svg(doc)
        assert "图表 #7" in svg
        assert "模板已下线" in svg


class TestPngWriter:
    def test_png_bytes_and_scale(self):
        doc = render_chart("bar-line-dual-axis", CHART_TEMPLATES["bar-line-dual-axis"].default_config)
        png2 = to_png(doc)  # 默认 2 倍（DOCX/PDF 导出口径）
        assert png2.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(png2) > 1000
        png1 = to_png(doc, scale=1)
        assert png1.startswith(b"\x89PNG")
        assert len(png1) < len(png2)

    def test_png_of_degraded(self):
        png = to_png(render_degraded(3, "x"))
        assert png.startswith(b"\x89PNG")


class TestResolveColor:
    def test_var_fallback_extracted(self):
        assert resolve_color("var(--cn-border, #D8D2C1)") == "#D8D2C1"
        assert resolve_color("var(--x, #abc)") == "#aabbcc"

    def test_rgba_blended_over_paper(self):
        mixed = resolve_color("rgba(30, 61, 87, 0.045)")
        assert mixed.startswith("#")
        assert mixed != "#1E3D57"  # 已按透明度向纸色混合
        assert resolve_color("rgba(30, 61, 87)") == "#1E3D57"  # 无 alpha = 不透明

    def test_fallbacks(self):
        assert resolve_color("") == "#000000"
        assert resolve_color("rgba(junk)") == "#000000"
        assert resolve_color("not-a-color") == "#000000"
