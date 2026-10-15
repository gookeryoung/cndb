"""PDF 导出器：reportlab Platypus 框架 + 自动分页 + 页眉页脚。"""

from __future__ import annotations

import io
from typing import Any

from cndb.plugins.documents.services.export.images import IMAGE_LINE_RE, ImageResolver
from cndb.plugins.documents.services.export.markdown_style import _MD_BOLD_RE, _MD_CODE_RE, _MD_HEADING_RE
from cndb.plugins.documents.services.export.pdf_fonts import _ensure_pdf_font
from cndb.plugins.documents.services.export.theme import DEFAULT_THEME, ExportTheme

# 图片最大宽度 = A4 宽（595.27pt）减左右各 50pt 页边距
_PDF_MAX_IMAGE_WIDTH = 595.27 - 100


def _make_pdf_image(resolved: tuple[bytes, str] | None) -> Any:
    """把解析出的图片字节装成 Platypus Image，并等比缩放到正文宽度内.

    返回 None 表示无法嵌入（未解析到文件 / 格式不被 reportlab 支持）。
    """
    if resolved is None:
        return None
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image as PdfImage

    data, _name = resolved
    try:
        reader = ImageReader(io.BytesIO(data))
        width, height = reader.getSize()
        if not width or not height:  # pragma: no cover - 异常图片元数据
            return None
        scale = min(1.0, _PDF_MAX_IMAGE_WIDTH / width)
        return PdfImage(io.BytesIO(data), width=width * scale, height=height * scale)
    except Exception:
        return None


def _render_pdf(markdown_text: str, title: str = "", images: ImageResolver | None = None) -> bytes:
    # images：站内图片解析器；``![alt](file:<key>)`` 独占一行时嵌入真实图片
    """把文档 Markdown 正文渲染为 .pdf 字节流.

    Platypus 框架 + 自动分页 + 页眉页脚；中文字符依赖 ``_ensure_pdf_font``
    注册的系统 CJK 字体，注册失败时回退 Helvetica（此时中文可能乱码但不崩溃）。
    """
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    cjk_font = _ensure_pdf_font() or "Helvetica"
    preset = DEFAULT_THEME
    buf = io.BytesIO()
    title = title or "Document"

    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName=cjk_font,
        fontSize=preset.body_size,
        leading=preset.body_size * 1.5,
        spaceAfter=4,
    )
    heading_styles = {
        i + 1: ParagraphStyle(
            f"H{i + 1}",
            parent=styles[f"Heading{i + 1}"],
            fontName=cjk_font,
            fontSize=preset.heading_sizes[i],
            leading=preset.heading_sizes[i] * 1.25,
            spaceBefore=12 - i * 2,
            spaceAfter=8 - i * 2,
            textColor=HexColor(preset.heading_colors[i]),
        )
        for i in range(3)
    }

    story: list[Any] = []
    table_buffer: list[list[str]] = []
    in_table = False

    for raw_line in markdown_text.split("\n"):
        line = raw_line.rstrip()

        # 表格行：以 | 分隔
        if line.strip().startswith("|") and line.strip().endswith("|"):
            if not in_table:
                in_table = True
                table_buffer = []
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            table_buffer.append(cells)
            continue
        elif in_table:
            # 表格结束，提交表格
            if table_buffer:
                story.append(_make_pdf_table(table_buffer, preset, cjk_font))
            in_table = False
            table_buffer = []
            # 继续处理当前这行

        # 空行
        if not line.strip():
            story.append(Spacer(1, 6))
            continue

        # 标题行
        m = _MD_HEADING_RE.match(line)
        if m:
            level = min(len(m.group(1)), 3)
            text = m.group(2).strip()
            style = heading_styles.get(level, heading_styles[3])
            story.append(Paragraph(_pdf_escape(text), style))
            continue

        # 换页标记
        if line.strip() == "---PAGE---":
            story.append(PageBreak())
            continue

        # 站内图片：独占一行时嵌入真实图片（等比缩放到正文宽度内）
        img_match = IMAGE_LINE_RE.match(line)
        if img_match:
            alt = img_match.group("alt") or "图片"
            resolved = images(img_match.group("key")) if images is not None else None
            figure = _make_pdf_image(resolved)
            if figure is None:
                story.append(Paragraph(_pdf_escape(f"[图片缺失：{alt}]"), body_style))
            else:
                story.append(figure)
                story.append(Spacer(1, 6))
            continue

        # 普通段落（处理粗体）
        story.append(Paragraph(_pdf_markdown_to_rml(line, cjk_font), body_style))

    # 收尾：提交剩余表格
    if in_table and table_buffer:
        story.append(_make_pdf_table(table_buffer, preset, cjk_font))

    # 分页回调（页眉 + 页脚页码）
    def _on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(cjk_font, 8)
        # 页眉
        canvas.drawString(50, A4[1] - 30, str(title))
        canvas.drawRightString(A4[0] - 50, A4[1] - 30, _export_timestamp())
        # 页脚
        canvas.drawCentredString(A4[0] / 2, 30, f"第 {doc.page} 页")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=50,
        rightMargin=50,
        topMargin=50,
        bottomMargin=50,
        title=str(title),
    )
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    buf.seek(0)
    return buf.getvalue()


def _export_timestamp() -> str:
    """PDF 页眉右侧固定文本（导出时刻）."""
    import datetime as dt

    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def _pdf_escape(text: str) -> str:
    """转义 reportlab RML 特殊字符."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _pdf_markdown_to_rml(text: str, cjk_font: str = "Helvetica") -> str:
    """将 Markdown 粗体/代码转为 reportlab RML（代码字体用 cjk_font，Courier 无中文字形）."""
    escaped = _pdf_escape(text)
    escaped = _MD_BOLD_RE.sub(r"<b>\1</b>", escaped)
    escaped = _MD_CODE_RE.sub(rf"<font name='{cjk_font}'><i>\1</i></font>", escaped)
    return escaped


def _pdf_table_style_cmds(preset: ExportTheme, cjk_font: str = "Helvetica") -> list[tuple[Any, ...]]:
    """按预设构造 PDF 表格样式命令列表（表头底色/文字色 + 斑马纹 + 网格 + 中文字体）."""
    from reportlab.lib import colors

    return [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(preset.table_header_bg)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(preset.table_header_color)),
        ("FONTNAME", (0, 0), (-1, 0), cjk_font),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTNAME", (0, 1), (-1, -1), cjk_font),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
    ]


def _make_pdf_table(rows: list[list[str]], preset: ExportTheme | None = None, cjk_font: str = "Helvetica") -> Any:
    """构造 reportlab Table（带表头样式 + 中文字体 + 跨页重复）."""
    from reportlab.platypus import Table, TableStyle

    if not rows:
        return Table([[]])
    # 确保每行等宽
    max_cols = max(len(r) for r in rows)
    norm_rows = [r + [""] * (max_cols - len(r)) for r in rows]
    table = Table(norm_rows, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle(_pdf_table_style_cmds(preset or DEFAULT_THEME, cjk_font)))
    return table


__all__ = [
    "_export_timestamp",
    "_make_pdf_table",
    "_pdf_escape",
    "_pdf_markdown_to_rml",
    "_pdf_table_style_cmds",
    "_render_pdf",
]
