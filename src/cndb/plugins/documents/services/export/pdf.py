"""PDF 导出器：reportlab Platypus 框架 + 自动分页 + 页眉页脚.

块级 / 行内语法统一由 :mod:`markdown_blocks` 解析，本模块只负责映射到
Platypus flowable。历史实现逐行判断、表格单元格直接用字符串，导致列表与代码围栏
原样输出、长 URL / 中文不换行压到相邻列；现表格单元格一律用可 CJK 断行的
``Paragraph`` 承载，并按内容比例收敛列宽。
"""

from __future__ import annotations

import io
import re
from typing import Any

from cndb.plugins.documents.services.charts import to_png
from cndb.plugins.documents.services.charts.inline import (
    InlineChartBlock,
    block_error_message,
    render_inline_chart,
    split_inline_chart_segments,
)
from cndb.plugins.documents.services.export.images import ImageResolver
from cndb.plugins.documents.services.export.markdown_blocks import (
    INLINE_BOLD,
    INLINE_BREAK,
    INLINE_CODE,
    INLINE_ITALIC,
    INLINE_LINK,
    INLINE_STRIKE,
    Block,
    CodeBlock,
    HeadingBlock,
    ImageBlock,
    InlineSpan,
    ListBlock,
    PageBreakBlock,
    ParagraphBlock,
    QuoteBlock,
    RuleBlock,
    TableBlock,
    TableRefBlock,
    display_width,
    fit_column_widths,
    parse_blocks,
    parse_inline,
)
from cndb.plugins.documents.services.export.pdf_fonts import _ensure_pdf_font
from cndb.plugins.documents.services.export.table_refs import TableResolver, parse_table_ref_line
from cndb.plugins.documents.services.export.theme import DEFAULT_THEME, ExportTheme

# 图片最大宽度 = A4 宽（595.27pt）减左右各 50pt 页边距
_PDF_MAX_IMAGE_WIDTH = 595.27 - 100

#: H4-H6 沿用正文字号收敛（预览 H4-H6 不再放大，旧实现全部折叠到 H3）
_HEADING_SIZES: tuple[float, ...] = (18.0, 15.0, 13.0, 12.0, 11.0, 10.5)
_HEADING_SPACE_BEFORE: tuple[float, ...] = (14.0, 12.0, 10.0, 9.0, 8.0, 8.0)
_HEADING_SPACE_AFTER: tuple[float, ...] = (8.0, 6.0, 4.0, 3.0, 3.0, 3.0)

_QUOTE_COLOR = "#555555"
_CODE_BG = "#F6F8FA"
_CODE_BORDER = "#E5E7EB"


def _make_pdf_image(resolved: tuple[bytes, str] | None, max_width: float = _PDF_MAX_IMAGE_WIDTH) -> Any:
    """把解析出的图片字节装成 Platypus Image，并等比缩放到给定宽度内（缺省正文宽度）.

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
        scale = min(1.0, max_width / width)
        return PdfImage(io.BytesIO(data), width=width * scale, height=height * scale)
    except Exception:
        return None


def _pdf_escape(text: str) -> str:
    """转义 reportlab RML 特殊字符."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _pdf_spans_rml(spans: tuple[InlineSpan, ...] | list[InlineSpan], cjk_font: str = "Helvetica") -> str:
    """行内片段 → reportlab RML（代码用 cjk_font，Courier 无中文字形）."""
    parts: list[str] = []
    for span in spans:
        text = _pdf_escape(span.text)
        if span.kind == INLINE_BOLD:
            parts.append(f"<b>{text}</b>")
        elif span.kind == INLINE_ITALIC:
            parts.append(f"<i>{text}</i>")
        elif span.kind == INLINE_CODE:
            parts.append(f"<font name='{cjk_font}'><i>{text}</i></font>")
        elif span.kind == INLINE_STRIKE:
            parts.append(f"<strike>{text}</strike>")
        elif span.kind == INLINE_LINK:
            href = _pdf_escape(span.href).replace('"', "&quot;")
            parts.append(f'<link href="{href}" color="#1a6fb5">{text}</link>')
        elif span.kind == INLINE_BREAK:
            parts.append("<br/>")
        else:
            parts.append(text)
    return "".join(parts)


def _pdf_markdown_to_rml(text: str, cjk_font: str = "Helvetica") -> str:
    """将 Markdown 行内语法转为 reportlab RML."""
    return _pdf_spans_rml(parse_inline(text), cjk_font)


def _cell_weight(rml: str) -> float:
    """按纯文本显示宽度估算列权重（CJK 记 2，HTML 标签不计）."""
    plain = re.sub(r"<[^>]+>", "", rml)
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"), ("&nbsp;", " ")):
        plain = plain.replace(entity, char)
    return float(max(6, display_width(plain)))


def _make_pdf_table_rml(
    rml_rows: list[list[str]],
    preset: ExportTheme | None = None,
    cjk_font: str = "Helvetica",
    width_percent: int = 100,
    aligns: tuple[str, ...] | None = None,
) -> Any:
    """用可换行段落构造 PDF 表格（按内容分配列宽 + 表头重复 + 允许行内分页）."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    if not rml_rows:
        return Spacer(1, 0)
    active = preset or DEFAULT_THEME
    max_cols = max(len(row) for row in rml_rows)
    if max_cols == 0:
        return Spacer(1, 0)
    norm_rows = [row + [""] * (max_cols - len(row)) for row in rml_rows]
    col_aligns = list(aligns or ())
    col_aligns = (col_aligns + ["left"] * max_cols)[:max_cols]

    weights = [max(_cell_weight(row[col]) for row in norm_rows) for col in range(max_cols)]
    total_width = _PDF_MAX_IMAGE_WIDTH * width_percent / 100
    col_widths = fit_column_widths(weights, total_width)

    base = ParagraphStyle(
        "PdfCell",
        fontName=cjk_font,
        fontSize=9,
        leading=12.5,
        wordWrap="CJK",
        spaceBefore=0,
        spaceAfter=0,
    )
    header_base = ParagraphStyle("PdfCellHeader", parent=base, fontSize=10, leading=13.5)
    # reportlab 的 alignment 只认 TA_* 整数常量（传字符串会让 Paragraph.draw 失效）
    alignment: dict[str, Any] = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}
    body_styles = [
        ParagraphStyle(f"PdfCell{col}", parent=base, alignment=alignment[col_aligns[col]]) for col in range(max_cols)
    ]
    header_styles = [
        ParagraphStyle(
            f"PdfCellHeader{col}",
            parent=header_base,
            alignment=alignment[col_aligns[col]],
            textColor=colors.HexColor(active.table_header_color),
        )
        for col in range(max_cols)
    ]

    cells: list[list[Any]] = []
    for row_index, row in enumerate(norm_rows):
        styles = header_styles if row_index == 0 else body_styles
        cells.append([Paragraph(row[col] or "&nbsp;", styles[col]) for col in range(max_cols)])

    table = Table(
        cells,
        repeatRows=1,
        splitByRow=1,
        splitInRow=1,
        hAlign="LEFT",
        colWidths=col_widths,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(active.table_header_bg)),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


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


def _make_pdf_table(
    rows: list[list[str]],
    preset: ExportTheme | None = None,
    cjk_font: str = "Helvetica",
    width_percent: int = 100,
    aligns: tuple[str, ...] | None = None,
) -> Any:
    """构造 reportlab Table（纯文本入口，数据表引用与兼容调用使用）.

    ``width_percent`` 按正文可用宽度的百分比设置总列宽（数据表引用，缺省 100）。
    """
    if not rows:
        return _make_pdf_table_rml([], preset, cjk_font, width_percent, aligns)
    rml_rows = [[_pdf_escape(str(cell)) for cell in row] for row in rows]
    return _make_pdf_table_rml(rml_rows, preset, cjk_font, width_percent, aligns)


def _pdf_code_line_rml(line: str, cjk_font: str) -> str:
    """代码行 RML：保留行首缩进（空格转 nbsp），纯 ASCII 行走 Courier."""
    expanded = line.expandtabs(4)
    leading = len(expanded) - len(expanded.lstrip(" "))
    font = "Courier" if expanded.isascii() else cjk_font
    body = _pdf_escape(expanded)
    if leading:
        body = "&nbsp;" * leading + body[leading:]
    return f"<font name='{font}'>{body or '&nbsp;'}</font>"


def _pdf_boxed_lines(
    lines_rml: list[str],
    cjk_font: str,
    *,
    background: str | None = None,
    left_bar: str | None = None,
    color: str = "#333333",
    font_size: float = 8.5,
    italic: bool = False,
) -> Any:
    """把多行 RML 装进可跨页的单列表格（代码块 / 引用共用）."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Table, TableStyle

    style = ParagraphStyle(
        "PdfBoxLine",
        fontName=cjk_font,
        fontSize=font_size,
        leading=font_size * 1.45,
        wordWrap="CJK",
        textColor=colors.HexColor(color),
        spaceBefore=0,
        spaceAfter=0,
    )
    content = [(f"<i>{line}</i>" if italic else line) or "&nbsp;" for line in lines_rml]
    rows = [[Paragraph(line, style)] for line in content] or [[Paragraph("&nbsp;", style)]]
    table = Table(rows, colWidths=[_PDF_MAX_IMAGE_WIDTH], hAlign="LEFT", splitByRow=1)
    commands: list[tuple[Any, ...]] = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]
    if background:
        commands.append(("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(background)))
    if left_bar:
        commands.append(("LINEBEFORE", (0, 0), (0, -1), 2.5, colors.HexColor(left_bar)))
        commands.append(("LEFTPADDING", (0, 0), (-1, -1), 12))
    table.setStyle(TableStyle(commands))
    return table


def _render_pdf(
    markdown_text: str,
    title: str = "",
    images: ImageResolver | None = None,
    tables: TableResolver | None = None,
) -> bytes:
    # images：站内图片解析器；``![alt](file:<key>)`` 独占一行时嵌入真实图片
    # tables：数据表引用解析器；``{{table:…}}`` 独占一行时渲染为真实表格
    # 图表：正文 `` ```chart `` 内嵌块渲染为整幅图 PNG（ADR 0052，2 倍分辨率）
    """把文档 Markdown 正文渲染为 .pdf 字节流.

    Platypus 框架 + 自动分页 + 页眉页脚；中文字符依赖 ``_ensure_pdf_font``
    注册的系统 CJK 字体，注册失败时回退 Helvetica（此时中文可能乱码但不崩溃）。
    """
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        HRFlowable,
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
        spaceAfter=6,
        wordWrap="CJK",
    )
    heading_styles = {
        level: ParagraphStyle(
            f"H{level}",
            parent=styles["Normal"],
            fontName=cjk_font,
            fontSize=_HEADING_SIZES[level - 1],
            leading=_HEADING_SIZES[level - 1] * 1.25,
            spaceBefore=_HEADING_SPACE_BEFORE[level - 1],
            spaceAfter=_HEADING_SPACE_AFTER[level - 1],
            textColor=HexColor("#000000"),
        )
        for level in range(1, 7)
    }
    list_styles = {
        level: ParagraphStyle(
            f"List{level}",
            parent=body_style,
            leftIndent=16 * (level + 1),
            bulletIndent=16 * level,
            spaceAfter=2,
            bulletFontName=cjk_font,
            bulletFontSize=preset.body_size,
        )
        for level in range(8)
    }

    story: list[Any] = []

    def _add_chart_block(block: InlineChartBlock) -> None:
        """内嵌图表块 → 整幅图 PNG；坏块降级为占位段落（ADR 0052 D11）."""
        if block.error:
            story.append(Paragraph(_pdf_escape(block_error_message(block.error)), body_style))
            return
        fallback = f"[图表无法嵌入：{block.title or '图表'}]"
        try:
            rendered = render_inline_chart(block)
            max_width = _PDF_MAX_IMAGE_WIDTH * block.width / 100
            figure = _make_pdf_image((to_png(rendered, scale=2), "chart.png"), max_width=max_width)
        except Exception:  # pragma: no cover - 渲染器契约保证 PNG 可解析
            figure = None
        if figure is None:
            story.append(Paragraph(_pdf_escape(fallback), body_style))
        else:
            story.append(figure)
            story.append(Spacer(1, 6))

    def _add_table_ref(block: TableRefBlock) -> None:
        if tables is None:
            story.append(Paragraph(_pdf_escape(block.raw), body_style))
            return
        spec = parse_table_ref_line(block.raw)
        if spec is None:
            story.append(Paragraph(_pdf_escape(block.raw), body_style))
            return
        resolved = tables(spec)
        if resolved.error:
            story.append(Paragraph(_pdf_escape(resolved.error), body_style))
            return
        story.append(Paragraph(f"<i>{_pdf_escape(resolved.caption)}</i>", body_style))
        story.append(
            _make_pdf_table(
                [resolved.header or [], *(resolved.rows or [])],
                preset,
                cjk_font,
                width_percent=spec.width,
            )
        )
        story.append(Spacer(1, 6))

    def _add_image(block: ImageBlock) -> None:
        resolved = images(block.key) if images is not None else None
        figure = _make_pdf_image(resolved)
        if figure is None:
            story.append(Paragraph(_pdf_escape(f"[图片缺失：{block.alt}]"), body_style))
            return
        story.append(figure)
        story.append(Spacer(1, 6))

    def _add_code(block: CodeBlock) -> None:
        lines = [_pdf_code_line_rml(line, cjk_font) for line in block.code.split("\n")]
        story.append(_pdf_boxed_lines(lines, cjk_font, background=_CODE_BG, left_bar=_CODE_BORDER))
        story.append(Spacer(1, 6))

    def _add_quote(block: QuoteBlock) -> None:
        lines = [_pdf_spans_rml(line, cjk_font) for line in block.lines]
        story.append(_pdf_boxed_lines(lines, cjk_font, left_bar="#D0D0D0", color=_QUOTE_COLOR, italic=True))
        story.append(Spacer(1, 6))

    def _add_blocks(blocks: list[Block]) -> None:
        for block in blocks:
            if isinstance(block, HeadingBlock):
                story.append(Paragraph(_pdf_spans_rml(block.spans, cjk_font), heading_styles[block.level]))
            elif isinstance(block, ParagraphBlock):
                story.append(Paragraph(_pdf_spans_rml(block.spans, cjk_font), body_style))
            elif isinstance(block, ListBlock):
                for item in block.items:
                    story.append(
                        Paragraph(
                            _pdf_spans_rml(item.spans, cjk_font),
                            list_styles[min(item.level, len(list_styles) - 1)],
                            bulletText=item.marker,
                        )
                    )
            elif isinstance(block, TableBlock):
                story.append(
                    _make_pdf_table_rml(
                        [
                            [_pdf_spans_rml(cell, cjk_font) for cell in block.header],
                            *[[_pdf_spans_rml(cell, cjk_font) for cell in row] for row in block.rows],
                        ],
                        preset,
                        cjk_font,
                        aligns=block.aligns,
                    )
                )
                story.append(Spacer(1, 6))
            elif isinstance(block, TableRefBlock):
                _add_table_ref(block)
            elif isinstance(block, CodeBlock):
                _add_code(block)
            elif isinstance(block, QuoteBlock):
                _add_quote(block)
            elif isinstance(block, RuleBlock):
                story.append(
                    HRFlowable(width="100%", thickness=0.6, color=HexColor("#DDDDDD"), spaceBefore=4, spaceAfter=6)
                )
            elif isinstance(block, PageBreakBlock):
                story.append(PageBreak())
            elif isinstance(block, ImageBlock):
                _add_image(block)

    for segment in split_inline_chart_segments(markdown_text):
        if isinstance(segment, str):
            _add_blocks(parse_blocks(segment))
            continue
        _add_chart_block(segment)

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


__all__ = [
    "_export_timestamp",
    "_make_pdf_table",
    "_pdf_escape",
    "_pdf_markdown_to_rml",
    "_pdf_table_style_cmds",
    "_render_pdf",
]
