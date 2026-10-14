"""报告输出格式渲染器注册表。

renderer 签名：renderer(rendered_text: str, ctx: dict[str, Any], theme: str) -> bytes 。"""

from __future__ import annotations

from typing import Any

from cndb.plugins.reports.models import OutputFormat
from cndb.plugins.reports.renderers.docx import _render_docx
from cndb.plugins.reports.renderers.html import _render_html
from cndb.plugins.reports.renderers.pdf import _render_pdf
from cndb.plugins.reports.renderers.xlsx import _render_xlsx

_FORMAT_RENDERERS: dict[str, Any] = {
    OutputFormat.DOCX: _render_docx,
    OutputFormat.PDF: _render_pdf,
    OutputFormat.XLSX: _render_xlsx,
    OutputFormat.HTML: _render_html,
}
