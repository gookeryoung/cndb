"""文档导出：Markdown / Word(.docx) / PDF 文件生成.

文档正文即 Markdown；正文中独占段落的 ``{{table:…}}`` 数据表引用由
:mod:`table_refs` 解析为真实表格（ADR 0045），``{{chart:…}}`` 图表引用由
:mod:`chart_refs` 解析为真实图形（ADR 0048）。
导出器签名统一为 ``exporter(markdown_text, title, images, tables, charts)``。
"""

from __future__ import annotations

import io
from typing import Any

from cndb.plugins.documents.services.export import chart_refs
from cndb.plugins.documents.services.export.chart_refs import (
    ChartResolver,
    make_chart_resolver,
    parse_chart_ref_line,
    referenced_chart_ids,
    rewrite_markdown_chart_refs,
)
from cndb.plugins.documents.services.export.docx import _render_docx
from cndb.plugins.documents.services.export.images import (
    ImageResolver,
    make_image_resolver,
    rewrite_markdown_images,
)
from cndb.plugins.documents.services.export.pdf import _render_pdf
from cndb.plugins.documents.services.export.table_refs import (
    TableResolver,
    make_table_resolver,
    rewrite_markdown_table_refs,
)

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


def _render_markdown(
    markdown_text: str,
    title: str = "",
    images: ImageResolver | None = None,
    tables: TableResolver | None = None,
    charts: ChartResolver | None = None,
) -> bytes:
    """Markdown 导出：正文落盘为 UTF-8 字节流.

    单文件 markdown 无法内嵌二进制：保留 ``file:<file_key>`` 应用内引用不改写；
    数据表引用在落盘前改写为静态 GFM 表格快照（图表引用由端点侧先改写为
    SVG 资产相对引用，这里幂等重跑为无操作）。
    """
    _ = (title, images, charts)
    if tables is not None:
        markdown_text = rewrite_markdown_table_refs(markdown_text, tables)
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


def render_markdown_archive(
    markdown_text: str,
    title: str,
    images: ImageResolver | None,
    archive_name: str,
    extra_assets: dict[str, bytes] | None = None,
) -> bytes | None:
    """Markdown + 站内图片打包为 zip（``<archive_name>.md`` + ``assets/<file_key>``）.

    ``extra_assets``：图表导出侧已改写收集的资产（``assets/chart-<id>.svg`` → 字节），
    一并并入归档（ADR 0048 D6）。

    返回 None 表示正文里没有任何**可解析**的站内图片 / 图表资产，调用方应回退为
    普通 .md 响应（避免为不带图的文档凭空产生 zip，保持既有单文件行为）。
    """
    _ = title
    rewritten, assets = rewrite_markdown_images(markdown_text, images)
    if extra_assets:
        assets.update(extra_assets)
    if not assets:
        return None

    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{archive_name}.md", rewritten.encode("utf-8"))
        for rel, data in sorted(assets.items()):
            zf.writestr(rel, data)
    buf.seek(0)
    return buf.getvalue()


def render_export(
    markdown_text: str,
    fmt: str,
    title: str = "",
    images: ImageResolver | None = None,
    tables: TableResolver | None = None,
    charts: ChartResolver | None = None,
) -> bytes:
    """按格式渲染文档正文.

    Args:
        markdown_text: 文档最新版本正文（Markdown）。
        fmt: 已规范化的格式名（见 {@link normalize_format}）。
        title: 文档标题，用于 DOCX 属性与 PDF 页眉。
        images: 站内图片解析器。
        tables: 数据表引用解析器；提供时 ``{{table:…}}`` 渲染为真实表格。
        charts: 图表引用解析器；提供时 ``{{chart:…}}`` 渲染为整幅图。

    Raises:
        KeyError: 传入未注册的格式名。
    """
    return _EXPORTERS[fmt](markdown_text, title, images, tables, charts)


__all__ = [
    "FORMAT_CONTENT_TYPES",
    "FORMAT_DOCX",
    "FORMAT_EXTENSIONS",
    "FORMAT_MARKDOWN",
    "FORMAT_PDF",
    "SUPPORTED_FORMATS",
    "ChartResolver",
    "ImageResolver",
    "TableResolver",
    "chart_refs",
    "make_chart_resolver",
    "make_image_resolver",
    "make_table_resolver",
    "normalize_format",
    "parse_chart_ref_line",
    "referenced_chart_ids",
    "render_export",
    "render_markdown_archive",
    "rewrite_markdown_chart_refs",
    "rewrite_markdown_table_refs",
]
