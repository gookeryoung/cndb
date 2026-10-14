"""HTML 渲染器：单文件 HTML（内联样式 + 主题变量）。"""

from __future__ import annotations

import re
from typing import Any

from cndb.plugins.reports.models import ThemeStyle
from cndb.plugins.reports.renderers.markdown import _MD_HEADING_RE, _MD_TABLE_SEP_RE
from cndb.plugins.reports.themes import get_theme_preset

_HTML_ESCAPE_RE = re.compile(r"[&<>\"']")


def _html_escape(text: str) -> str:
    """转义 HTML 特殊字符（& < > " '），防注入."""
    return _HTML_ESCAPE_RE.sub(
        lambda m: {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[m.group()],
        text,
    )


def _html_rich_text(text: str) -> str:
    """把段落文本中的 **bold** 与 `code` 转为 HTML 标签（先转义再加标签）."""
    escaped = _html_escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped


def _render_html(rendered_text: str, ctx: dict[str, Any], theme: str = ThemeStyle.MINIMAL.value) -> bytes:
    """HTML 渲染：Markdown 风格标题/表格/加粗/代码转为自包含 HTML 文档，按主题应用配色.

    ctx 保留签名一致性（与其他渲染器相同）；页面内嵌 CSS，无外部依赖，
    可直接用浏览器打开或归档。`---PAGE---` 换页标记转为分页符（打印场景）。
    """
    preset = get_theme_preset(theme)
    accent = preset.heading_colors[0] if preset.heading_colors else "#1f3864"
    header_bg = preset.table_header_bg if preset.table_header_bg else "#f2f2f2"
    header_color = preset.table_header_color if preset.table_header_color else "#ffffff"

    body_parts: list[str] = []
    table_buffer: list[str] = []
    in_table = False

    def _is_table_row(line: str) -> bool:
        s = line.strip()
        return s.startswith("|") and s.endswith("|")

    def _flush_table() -> None:
        nonlocal in_table, table_buffer
        rows = [[c.strip() for c in raw.strip().strip("|").split("|")] for raw in table_buffer if raw.strip()]
        rows = [r for r in rows if not all(_MD_TABLE_SEP_RE.match(c or "-") for c in r)]
        if rows:
            cells_html: list[str] = []
            for i, row_cells in enumerate(rows):
                tag = "th" if i == 0 else "td"
                tds = "".join(f"<{tag}>{_html_rich_text(c)}</{tag}>" for c in row_cells)
                cells_html.append(f"<tr>{tds}</tr>")
            body_parts.append('<table border="1" cellspacing="0" cellpadding="6">' + "".join(cells_html) + "</table>")
        in_table = False
        table_buffer = []

    for raw_line in rendered_text.split("\n"):
        line = raw_line.rstrip()

        if _is_table_row(line):
            if not in_table:
                in_table = True
                table_buffer = []
            table_buffer.append(line)
            continue
        if in_table:
            _flush_table()

        if not line.strip():
            continue

        m = _MD_HEADING_RE.match(line)
        if m:
            level = min(len(m.group(1)), 6)
            body_parts.append(f"<h{level}>{_html_rich_text(m.group(2).strip())}</h{level}>")
            continue

        # 换页标记 → 打印分页符
        if line.strip() == "---PAGE---":
            body_parts.append('<div style="page-break-after: always;"></div>')
            continue

        # 引用块
        if line.strip().startswith(">"):
            body_parts.append(f"<blockquote>{_html_rich_text(line.strip().lstrip('>').strip())}</blockquote>")
            continue

        body_parts.append(f"<p>{_html_rich_text(line.strip())}</p>")

    if in_table:
        _flush_table()

    html = (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{_html_escape(ctx.get('table_name', '报告'))}</title>\n"
        "<style>\n"
        "body { font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; margin: 40px auto; "
        f"max-width: 960px; color: #333; line-height: 1.6; }}\n"
        f"h1, h2, h3, h4, h5, h6 {{ color: {accent}; }}\n"
        f"table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 14px; }}\n"
        f"th {{ background: {header_bg}; color: {header_color}; }}\n"
        "tr:nth-child(even) { background: #fafafa; }\n"
        "code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; }\n"
        "blockquote { border-left: 4px solid #ddd; margin: 8px 0; padding: 4px 12px; color: #666; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n" + "\n".join(body_parts) + "\n</body>\n</html>\n"
    )
    return html.encode("utf-8")
