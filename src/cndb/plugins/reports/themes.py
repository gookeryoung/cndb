"""reports 主题风格预设：纯数据 + 纯函数，供 DOCX/PDF 渲染器应用文字与格式."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemePreset:
    """主题视觉参数.

    Attributes:
        heading_font: 标题字体名。
        heading_sizes: H1/H2/H3 字号（Pt）。
        heading_colors: H1/H2/H3 颜色（hex，不含 # 前缀由调用方约定，统一带 #）。
        body_font: 正文字体名。
        body_size: 正文字号（Pt）。
        table_header_bg: 表头底色（hex）。
        table_header_color: 表头文字色（hex）。
        table_body_font: 表格正文字体名。
        code_font: 行内代码字体名。
    """

    heading_font: str
    heading_sizes: tuple[float, float, float]
    heading_colors: tuple[str, str, str]
    body_font: str
    body_size: float
    table_header_bg: str
    table_header_color: str
    table_body_font: str
    code_font: str


# 各主题视觉参数（minimal 与既有渲染样式保持一致，作为基线）
_THEME_PRESETS: dict[str, ThemePreset] = {
    # 简约：现状样式（黑标题、无衬线正文、浅灰蓝表头）
    "minimal": ThemePreset(
        heading_font="Calibri",
        heading_sizes=(18.0, 15.0, 13.0),
        heading_colors=("#000000", "#000000", "#000000"),
        body_font="Calibri",
        body_size=10.5,
        table_header_bg="#E6EEF5",
        table_header_color="#1A5276",
        table_body_font="Calibri",
        code_font="Courier New",
    ),
    # 商务：深蓝标题 + 灰蓝表头，稳重正式
    "business": ThemePreset(
        heading_font="Calibri",
        heading_sizes=(18.0, 15.0, 13.0),
        heading_colors=("#1F3864", "#1F3864", "#2E5395"),
        body_font="Calibri",
        body_size=10.5,
        table_header_bg="#D9E2F3",
        table_header_color="#1F3864",
        table_body_font="Calibri",
        code_font="Courier New",
    ),
    # 现代：大字号标题 + 主题色强调，视觉冲击强
    "modern": ThemePreset(
        heading_font="Segoe UI",
        heading_sizes=(20.0, 16.0, 14.0),
        heading_colors=("#0F766E", "#0F766E", "#14B8A6"),
        body_font="Segoe UI",
        body_size=10.5,
        table_header_bg="#0F766E",
        table_header_color="#FFFFFF",
        table_body_font="Segoe UI",
        code_font="Consolas",
    ),
    # 工程：紧凑行距感（小字号）+ 等宽表格，面向技术数据
    "engineering": ThemePreset(
        heading_font="Arial",
        heading_sizes=(16.0, 13.5, 12.0),
        heading_colors=("#37474F", "#37474F", "#546E7A"),
        body_font="Arial",
        body_size=10.0,
        table_header_bg="#CFD8DC",
        table_header_color="#263238",
        table_body_font="Consolas",
        code_font="Consolas",
    ),
    # 学术：衬线正文 + 黑标题，面向论文/汇报
    "academic": ThemePreset(
        heading_font="Times New Roman",
        heading_sizes=(17.0, 14.0, 12.5),
        heading_colors=("#000000", "#000000", "#000000"),
        body_font="Times New Roman",
        body_size=11.0,
        table_header_bg="#F2F2F2",
        table_header_color="#000000",
        table_body_font="Times New Roman",
        code_font="Courier New",
    ),
}


def get_theme_preset(name: str | None) -> ThemePreset:
    """按名称取主题预设；None 或未知名称回退 minimal（兼容存量/脏数据）.

    Args:
        name: 主题名（business/minimal/modern/engineering/academic）。

    Returns:
        对应的 ThemePreset；无效名称返回 minimal 预设。
    """
    return _THEME_PRESETS.get(name or "", _THEME_PRESETS["minimal"])


__all__ = ["ThemePreset", "get_theme_preset"]
