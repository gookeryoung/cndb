"""图表渲染管线（ADR 0048 / 需求卡片 0070）单测.

覆盖：唯一渲染入口 render_chart（三模板 + 标准类型 + 垃圾 config 不崩）、
SVG 写端（无脚本无外链、标题转义、path 填充）、PNG 写端（PIL 光栅化 +
倍率、折线 / 扇形光栅化不丢）、降级整幅图、``{cagr}`` token 求值（D11）、
resolve_color 的 var/rgba 解析（边界 6）。
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from cndb.plugins.documents.services.charts.raster import resolve_color, to_png
from cndb.plugins.documents.services.charts.registry import CHART_TEMPLATES, normalize_config
from cndb.plugins.documents.services.charts.render import (
    SHEET_WIDTH,
    BadRequestTemplateError,
    render_chart,
    render_degraded,
)
from cndb.plugins.documents.services.charts.svg import to_svg

TPL_KEYS = ("bar-line-dual-axis", "stacked-bar-horizontal", "grouped-bar-horizontal")

#: 标准类型样例 key（需求卡片 0070 C5：每类抽一套预设做渲染断言）
STANDARD_SAMPLE_KEYS = (
    "line-vivid",
    "area-stacked",
    "bar-stacked",
    "pie-donut",
    "scatter-trend",
    "radar-business",
    "funnel-classic",
    "gauge-business",
    "treemap-business",
    "heatmap-vivid",
)


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


class TestStandardTypeRender:
    """需求卡片 0070 C5：标准类型预设渲染效果."""

    @pytest.mark.parametrize("template_key", STANDARD_SAMPLE_KEYS)
    def test_renders_sheet_with_expected_prims(self, template_key: str):
        """每类图表整幅图成型：纸底铺满 + 关键图元出现."""
        cfg = normalize_config(template_key, CHART_TEMPLATES[template_key].default_config)
        doc = render_chart(template_key, cfg)
        assert doc.width == SHEET_WIDTH
        assert doc.height > 100
        assert doc.elements[0].h == doc.height  # 纸底补齐
        kinds = {p.kind for p in doc.elements}
        assert "text" in kinds  # 图头 / 轴标 / 图例至少其一
        if template_key in (
            "bar-stacked",
            "pie-donut",
            "radar-business",
            "funnel-classic",
            "treemap-business",
            "heatmap-vivid",
        ):
            assert "rect" in kinds
        if template_key in ("line-vivid", "area-stacked", "scatter-trend", "radar-business", "gauge-business"):
            assert "path" in kinds or "line" in kinds

    @pytest.mark.parametrize("template_key", STANDARD_SAMPLE_KEYS)
    def test_png_rasterizes_without_loss(self, template_key: str):
        """PNG 光栅化成功且非空白（C5：写端一致性）."""
        cfg = normalize_config(template_key, CHART_TEMPLATES[template_key].default_config)
        png = to_png(render_chart(template_key, cfg))
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        img = Image.open(io.BytesIO(png)).convert("RGB")
        colors = img.getcolors(2_000_000)
        assert colors is not None and len(colors) > 8  # 非单色空白图

    def test_line_series_paths_present(self):
        """折线图：每系列一条描线 path + 数据点圆标."""
        cfg = normalize_config("line-vivid", CHART_TEMPLATES["line-vivid"].default_config)
        doc = render_chart("line-vivid", cfg)
        strokes = [p for p in doc.elements if p.kind == "path" and p.stroke and not p.fill]
        assert len(strokes) == 3  # 三系列
        circles = [p for p in doc.elements if p.kind == "circle"]
        assert len(circles) >= 3 * 6  # 6 行 × 3 系列数据点

    def test_area_paths_filled(self):
        """面积图：填充 path 带 rgba 填充与描线."""
        cfg = normalize_config("area-stacked", CHART_TEMPLATES["area-stacked"].default_config)
        doc = render_chart("area-stacked", cfg)
        fills = [p for p in doc.elements if p.kind == "path" and p.fill and p.fill.startswith("rgba(")]
        assert len(fills) >= 4  # 堆叠：四系列填充
        svg = to_svg(doc)
        assert 'fill="rgba(' in svg

    def test_pie_sectors_closed_and_percent_labels(self):
        """饼图：扇形 path 首尾闭合、含百分比标签与图例清单."""
        cfg = normalize_config("pie-donut", CHART_TEMPLATES["pie-donut"].default_config)
        doc = render_chart("pie-donut", cfg)
        sectors = [p for p in doc.elements if p.kind == "path" and p.fill and p.fill.startswith("#")]
        assert len(sectors) == 5  # 5 个正数值分块
        for sector in sectors:
            assert sector.d.startswith("M ") and " L " in sector.d
        texts = " ".join(p.content for p in doc.elements if p.kind == "text")
        assert "%" in texts and "合计" in texts

    def test_gauge_reads_max_label(self):
        """仪表盘：读数 / 指标名 / 量程文本存在，指针与轴心为线 + 圆."""
        cfg = normalize_config("gauge-business", CHART_TEMPLATES["gauge-business"].default_config)
        doc = render_chart("gauge-business", cfg)
        texts = [p.content for p in doc.elements if p.kind == "text"]
        assert "76.5%" in texts  # 中心读数
        assert "年度营收目标完成率" in texts
        assert any("量程 0–100%" in t for t in texts)
        assert any(p.kind == "circle" and p.r == 7 for p in doc.elements)  # 轴心

    def test_treemap_rects_fill_area(self):
        """树状图：矩形总面积铺满绘图区、互不重叠且占比合计 100%."""
        cfg = normalize_config("treemap-business", CHART_TEMPLATES["treemap-business"].default_config)
        doc = render_chart("treemap-business", cfg)
        rects = [p for p in doc.elements if p.kind == "rect" and p.fill and p.fill.startswith("#")]
        assert len(rects) == 8
        area = sum(p.w * p.h for p in rects)
        x0 = min(p.x for p in rects)
        x1 = max(p.x + p.w for p in rects)
        y0 = min(p.y for p in rects)
        y1 = max(p.y + p.h for p in rects)
        assert area == pytest.approx((x1 - x0) * (y1 - y0), rel=0.01)  # 面积归一化铺满
        for i, a in enumerate(rects):
            for b in rects[i + 1 :]:
                overlap = a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h
                assert not overlap
        # 占比文本与数据一致（小矩形仅显示占比，大矩形带数值）：逐个对回默认数据
        import re

        texts = "".join(p.content for p in doc.elements if p.kind == "text")
        shown = {float(m) for m in re.findall(r"(\d+\.\d)%", texts)}
        values = [r["value"] for r in CHART_TEMPLATES["treemap-business"].default_config["data"]["rows"]]
        total = sum(values)
        expected = {round(v / total * 100, 1) for v in values}
        assert shown
        assert shown <= expected

    def test_funnel_rates_and_values(self):
        """漏斗：阶段矩形递缩、数值白字、转化率标注."""
        cfg = normalize_config("funnel-classic", CHART_TEMPLATES["funnel-classic"].default_config)
        doc = render_chart("funnel-classic", cfg)
        texts = [p.content for p in doc.elements if p.kind == "text"]
        assert any("转化 53.3%" in t for t in texts)  # 640/1200
        assert any(t == "1200" for t in texts)

    def test_heatmap_grid_and_scale_bar(self):
        """热力图：单元格数量 = 行 × 列，色阶条与行列标签存在."""
        cfg = normalize_config("heatmap-vivid", CHART_TEMPLATES["heatmap-vivid"].default_config)
        doc = render_chart("heatmap-vivid", cfg)
        cells = [p for p in doc.elements if p.kind == "rect" and p.fill and p.fill.startswith("rgba(")]
        assert len(cells) == 6 * 4 + 12  # 24 格 + 12 段色阶条
        texts = [p.content for p in doc.elements if p.kind == "text"]
        assert "研发部" in texts and "一季度" in texts

    def test_style_toggles_change_output(self):
        """C3：样式开关实时调整改变渲染输出（showValues / donut / showTrend）."""
        base = normalize_config("line-vivid", CHART_TEMPLATES["line-vivid"].default_config)
        off = normalize_config("line-vivid", {**base, "style": {"showValues": False, "showMarkers": True}})
        texts_on = sum(1 for p in render_chart("line-vivid", base).elements if p.kind == "text" and p.halo)
        texts_off = sum(1 for p in render_chart("line-vivid", off).elements if p.kind == "text" and p.halo)
        assert texts_on > texts_off
        # donut 开关：中心合计文本只在环形出现
        pie = normalize_config("pie-classic", CHART_TEMPLATES["pie-classic"].default_config)
        donut = normalize_config("pie-donut", CHART_TEMPLATES["pie-donut"].default_config)
        flat_texts = [p.content for p in render_chart("pie-classic", pie).elements if p.kind == "text"]
        donut_texts = [p.content for p in render_chart("pie-donut", donut).elements if p.kind == "text"]
        assert "合计" in donut_texts and "合计" not in flat_texts
        # showTrend 开关：趋势线只在 trend 预设出现
        plain = render_chart(
            "scatter-business", normalize_config("scatter-business", CHART_TEMPLATES["scatter-business"].default_config)
        )
        trend = render_chart(
            "scatter-trend", normalize_config("scatter-trend", CHART_TEMPLATES["scatter-trend"].default_config)
        )
        plain_dashed = [p for p in plain.elements if p.kind == "line" and p.dash]
        trend_dashed = [p for p in trend.elements if p.kind == "line" and p.dash]
        assert len(trend_dashed) > len(plain_dashed)

    def test_degenerate_data_never_crashes(self):
        """C5：全零 / 单行 / 超量行等退化数据不崩."""
        zero = render_chart("pie-donut", {"data": {"rows": [{"label": "A", "value": 0}, {"label": "B", "value": 0}]}})
        assert zero.elements
        single = render_chart("line-vivid", {"data": {"rows": [{"label": "only", "values": [1, 2]}]}})
        assert single.elements
        many = render_chart(
            "scatter-trend",
            {"data": {"rows": [{"x": i, "y": i * 2} for i in range(60)]}},
        )
        assert many.elements
        flat = render_chart("radar-business", {"data": {"rows": [{"label": "A", "values": [0, 0, 0]}]}})
        assert flat.elements

    def test_path_translation_format_roundtrip(self):
        """存量缺陷修复：整幅平移后的 path 为规范形态，PNG 写端可解析（不丢折线）."""
        cfg = normalize_config("bar-line-dual-axis", CHART_TEMPLATES["bar-line-dual-axis"].default_config)
        doc = render_chart("bar-line-dual-axis", cfg)
        from cndb.plugins.documents.services.charts.primitives import parse_path_points

        for p in doc.elements:
            if p.kind == "path" and p.d:
                assert parse_path_points(p.d), p.d  # 平移后仍可解析出坐标点

    def test_png_contains_series_line_pixels(self):
        """存量缺陷修复：双轴图 PNG 中次值折线颜色像素非零（折线不丢）."""
        cfg = normalize_config("bar-line-dual-axis", CHART_TEMPLATES["bar-line-dual-axis"].default_config)
        img = Image.open(io.BytesIO(to_png(render_chart("bar-line-dual-axis", cfg)))).convert("RGB")
        counts = {c: n for n, c in img.getcolors(3_000_000)}
        # 次值折线 YEAR_PROJECTED #8C8578 / OLIVE #7A8570
        assert counts.get((140, 133, 120), 0) + counts.get((122, 133, 112), 0) > 0


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

    def test_value_labels_above_growth_line(self):
        """主值标签画在折线之后（折线穿过不遮挡数字）且带纸色 halo."""
        doc = render_chart("bar-line-dual-axis", CHART_TEMPLATES["bar-line-dual-axis"].default_config)
        kinds = [(idx, p) for idx, p in enumerate(doc.elements)]
        line_idx = next(idx for idx, p in kinds if p.kind == "path" and p.stroke)
        value_labels = [(idx, p) for idx, p in kinds if p.kind == "text" and p.weight == 600 and p.halo]
        assert value_labels
        assert all(idx > line_idx for idx, _ in value_labels)

    def test_leaders_below_value_labels(self):
        """引线画在主值标签下层（引线穿过数字时由 halo 遮线，不遮挡数字）."""
        doc = render_chart("bar-line-dual-axis", CHART_TEMPLATES["bar-line-dual-axis"].default_config)

        def width(text: str, size: float = 14.5) -> float:
            from cndb.plugins.documents.services.charts.render import text_width

            return text_width(text, size)

        import re as _re

        path = next(p for p in doc.elements if p.kind == "path" and p.d and p.stroke)
        points = [(float(a), float(b)) for a, b in _re.findall(r"[ML] ?([\d.]+) ([\d.]+)", path.d)]
        kinds = list(enumerate(doc.elements))
        leaders = [
            idx
            for idx, p in kinds
            if p.kind == "line"
            and p.stroke
            and p.stroke_width == 1
            and any(abs(p.x1 - px) <= 1 and abs(p.y1 - py) <= 1 for px, py in points)
        ]
        assert leaders  # 默认数据存在引线
        for idx, p in kinds:
            if p.kind == "text" and p.weight == 600 and p.halo:
                assert idx > max(leaders), p.content

    def test_displaced_growth_labels_get_leader_lines(self):
        """标签被挤离数据点超过 30px 时必须补引线（偏离不失联）."""
        doc = render_chart("bar-line-dual-axis", CHART_TEMPLATES["bar-line-dual-axis"].default_config)

        def width(text: str, size: float = 14.5) -> float:
            from cndb.plugins.documents.services.charts.render import text_width

            return text_width(text, size)

        import re as _re

        path = next(p for p in doc.elements if p.kind == "path" and p.d and p.stroke)
        points = [(float(a), float(b)) for a, b in _re.findall(r"[ML] ?([\d.]+) ([\d.]+)", path.d)]
        # 只认起始于数据点的细线为引线（stroke_width==1 的还有网格线）
        leaders = [
            p
            for p in doc.elements
            if p.kind == "line"
            and p.stroke
            and p.stroke_width == 1
            and any(abs(p.x1 - px) <= 1 and abs(p.y1 - py) <= 1 for px, py in points)
        ]
        for gl in doc.elements:
            if not (gl.kind == "text" and gl.weight == 700 and gl.content.endswith("%")):
                continue
            lw = width(gl.content, gl.size)
            bbox = (gl.tx - lw / 2, gl.ty - gl.size, lw, gl.size * 1.4)
            cx, cy = bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2
            nearest = min(points, key=lambda q: (q[0] - cx) ** 2 + (q[1] - cy) ** 2)
            dist = ((cx - nearest[0]) ** 2 + (cy - nearest[1]) ** 2) ** 0.5
            if dist <= 30:
                continue
            connected = any(
                bbox[0] - 6 <= ex <= bbox[0] + bbox[2] + 6 and bbox[1] - 6 <= ey <= bbox[1] + bbox[3] + 6
                for ld in leaders
                for ex, ey in ((ld.x1, ld.y1), (ld.x2, ld.y2))
            )
            assert connected, gl.content

    def test_negative_growth_axis_range(self):
        """次轴允许负值：负刻度出现、零基准线绘制、负值点在绘图区内（用户反馈）."""
        cfg = {
            "data": {
                "actualCount": 5,
                "rows": [
                    {
                        "label": str(2020 + i),
                        "value": 200 - i * 30,
                        "growth": [-8.5, -15.0, None, -12.5, 6.0, -20.0, 3.5, -5.0, 9.0, -18.0][i],
                    }
                    for i in range(10)
                ],
            }
        }
        doc = render_chart("bar-line-dual-axis", cfg)
        import re as _re

        path = next(p for p in doc.elements if p.kind == "path" and p.d and p.stroke)
        points = [(float(a), float(b)) for a, b in _re.findall(r"[ML] ?([\d.]+) ([\d.]+)", path.d)]
        assert points
        # 水平线：底轴与零基准线（存在负增长时）
        h_lines = [p for p in doc.elements if p.kind == "line" and p.y1 == p.y2 and p.stroke]
        bottom_axis = max(p.y1 for p in h_lines)
        zero_line = [p for p in h_lines if p.y1 < bottom_axis - 1]
        assert zero_line  # 零基准线
        # 全部折线点落在绘图区内（负值不再被 0 基线裁掉），且存在零线以下的点
        for _x, y in points:
            assert zero_line[0].y1 - 80 <= y <= bottom_axis + 1, y
        assert any(y > zero_line[0].y1 for _x, y in points)
        # 右轴出现负刻度文本
        tick_texts = [p.content for p in doc.elements if p.kind == "text" and p.content.startswith("-")]
        assert any(t in ("-8.5", "-15", "-20", "-12.5", "-5") for t in tick_texts)

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
