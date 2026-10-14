"""导出视觉预设：纯数据，供 DOCX / PDF 导出器应用文字与格式.

文档导出不暴露主题选择，统一使用 {@link DEFAULT_THEME}（历史报表的 minimal 基线），
因此这里不再保留多套主题与按名查找的逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExportTheme:
    """导出视觉参数.

    Attributes:
        heading_font: 标题字体名。
        heading_sizes: H1/H2/H3 字号（Pt）。
        heading_colors: H1/H2/H3 颜色（hex，带 # 前缀）。
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


# 默认预设：无衬线正文 + 黑标题 + 浅灰蓝表头，正式且印刷友好
DEFAULT_THEME = ExportTheme(
    heading_font="Calibri",
    heading_sizes=(18.0, 15.0, 13.0),
    heading_colors=("#000000", "#000000", "#000000"),
    body_font="Calibri",
    body_size=10.5,
    table_header_bg="#E6EEF5",
    table_header_color="#1A5276",
    table_body_font="Calibri",
    code_font="Courier New",
)


__all__ = ["DEFAULT_THEME", "ExportTheme"]
