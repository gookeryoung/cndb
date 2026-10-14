"""文档导出：Markdown / Word(.docx) / PDF 文件生成.

文档正文即 Markdown，因此导出链路不涉及模板变量、数据聚合或跨表取数：
导出器签名统一为 ``exporter(markdown_text: str, title: str) -> bytes``。
"""

from __future__ import annotations

from typing import Any

from cndb.plugins.documents.services.export.docx import _render_docx
from cndb.plugins.documents.services.export.pdf import _render_pdf

FORMAT_MARKDOWN = "md"
FORMAT_DOCX = "docx"
FORMAT_PDF = "pdf"

# 规范格式名 → 别名（请求参数大小写/全称兼容）
_FORMAT_ALIASES: dict[str, str] = {
    "md": FORMAT_MARKDOWN,
    "markdown": FORMAT_MARKDOWN,
    "docx": FORMAT_DOCX,
    "word": FORMAT_DOCX,
    "pdf": FORMAT_PDF,
}


def _render_markdown(markdown_text: str, title: str = "") -> bytes:
    """Markdown 导出：正文原样落盘为 UTF-8 字节流."""
    _ = title
    return markdown_text.encode("utf-8")


_EXPORTERS: dict[str, Any] = {
    FORMAT_MARKDOWN: _render_markdown,
    FORMAT_DOCX: _render_docx,
    FORMAT_PDF: _render_pdf,
}

# 导出格式契约：格式名 → (MIME, 文件扩展名)
FORMAT_CONTENT_TYPES: dict[str, str] = {
    FORMAT_MARKDOWN: "text/markdown; charset=utf-8",
    FORMAT_DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    FORMAT_PDF: "application/pdf",
}

FORMAT_EXTENSIONS: dict[str, str] = {
    FORMAT_MARKDOWN: "md",
    FORMAT_DOCX: "docx",
    FORMAT_PDF: "pdf",
}

SUPPORTED_FORMATS: tuple[str, ...] = tuple(_EXPORTERS)


def normalize_format(fmt: str) -> str | None:
    """把请求格式名规范化为 ``md`` / ``docx`` / ``pdf``；不支持的返回 None."""
    return _FORMAT_ALIASES.get((fmt or "").strip().lower())


def render_export(markdown_text: str, fmt: str, title: str = "") -> bytes:
    """按格式渲染文档正文.

    Args:
        markdown_text: 文档最新版本正文（Markdown）。
        fmt: 已规范化的格式名（见 {@link normalize_format}）。
        title: 文档标题，用于 DOCX 属性与 PDF 页眉。

    Raises:
        KeyError: 传入未注册的格式名。
    """
    return _EXPORTERS[fmt](markdown_text, title)


__all__ = [
    "FORMAT_CONTENT_TYPES",
    "FORMAT_DOCX",
    "FORMAT_EXTENSIONS",
    "FORMAT_MARKDOWN",
    "FORMAT_PDF",
    "SUPPORTED_FORMATS",
    "normalize_format",
    "render_export",
]
