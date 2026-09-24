"""reports 主题预设纯函数测试（无 DB）.

覆盖：五类主题可取且属性齐全、None/未知回退 minimal、各主题关键视觉参数。
"""

from __future__ import annotations

import pytest

from cndb.plugins.reports.themes import ThemePreset, get_theme_preset

VALID_THEMES = ["business", "minimal", "modern", "engineering", "academic"]


class TestGetThemePreset:
    """主题预设获取：合法值、回退、属性完整性."""

    def test_all_valid_themes_return_preset(self):
        """五类主题均可获取且为 ThemePreset 实例."""
        for name in VALID_THEMES:
            preset = get_theme_preset(name)
            assert isinstance(preset, ThemePreset)

    def test_preset_has_complete_attributes(self):
        """预设属性齐全：标题三级字号/颜色、正文字体字号、表头底色文字、代码字体."""
        preset = get_theme_preset("minimal")
        assert preset.heading_font
        assert preset.heading_sizes == pytest.approx([18.0, 15.0, 13.0])
        assert all(isinstance(c, str) and c for c in preset.heading_colors)
        assert preset.body_font
        assert preset.body_size > 0
        assert preset.table_header_bg
        assert preset.table_header_color
        assert preset.code_font

    def test_none_falls_back_to_minimal(self):
        """None（存量模板未设置）回退 minimal."""
        assert get_theme_preset(None) == get_theme_preset("minimal")

    def test_unknown_falls_back_to_minimal(self):
        """未知主题名回退 minimal（兼容历史脏数据）."""
        assert get_theme_preset("nope") == get_theme_preset("minimal")

    def test_minimal_matches_legacy_style(self):
        """minimal 主题与既有渲染样式一致（黑标题、正文 10.5、灰蓝表头 #E6EEF5）."""
        preset = get_theme_preset("minimal")
        assert preset.heading_colors == ("#000000", "#000000", "#000000")
        assert preset.body_size == pytest.approx(10.5)
        assert preset.table_header_bg == "#E6EEF5"
        assert preset.code_font == "Courier New"

    def test_business_uses_brand_color(self):
        """business 主题：深蓝标题 + 灰蓝表头."""
        preset = get_theme_preset("business")
        assert preset.heading_colors[0] == "#1F3864"
        assert preset.table_header_bg == "#D9E2F3"

    def test_academic_uses_serif_body(self):
        """academic 主题：衬线正文（Times New Roman）+ 黑标题."""
        preset = get_theme_preset("academic")
        assert preset.body_font == "Times New Roman"
        assert preset.heading_colors == ("#000000", "#000000", "#000000")

    def test_modern_uses_larger_headings(self):
        """modern 主题：标题字号不小于 minimal."""
        modern = get_theme_preset("modern")
        minimal = get_theme_preset("minimal")
        assert modern.heading_sizes[0] >= minimal.heading_sizes[0]

    def test_engineering_uses_mono_table_font(self):
        """engineering 主题：表格正文用等宽字体."""
        preset = get_theme_preset("engineering")
        assert preset.table_body_font == "Consolas"
