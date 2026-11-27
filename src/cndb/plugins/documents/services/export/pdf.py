"""PDF 导出器：reportlab Platypus 框架 + 自动分页 + 页眉页脚.

块级 / 行内语法统一由 :mod:`markdown_blocks` 解析，本模块只负责映射到
Platypus flowable。历史实现逐行判断、表格单元格直接用字符串，导致列表与代码围栏
原样输出、长 URL / 中文不换行压到相邻列；现表格单元格一律用可 CJK 断行的
``Paragraph`` 承载，并按内容比例收敛列宽。
"""

from __future__ import annotations

import io
import re
from typing import Any, override

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
    plain_text,
)
from cndb.plugins.documents.services.export.numbering import (
    has_explicit_caption_number,
    heading_level_offset,
    resolve_heading_numbering,
)
from cndb.plugins.documents.services.export.pdf_fonts import _ensure_pdf_font, ensure_pdf_font
from cndb.plugins.documents.services.export.table_refs import TableResolver, parse_table_ref_line
from cndb.plugins.documents.services.export.templates import (
    BUILTIN_TEMPLATES,
    DEFAULT_TEMPLATE_KEY,
    TABLE_CAPTION_RE,
    ExportTemplateConfig,
    ResolvedTemplate,
    TableConfig,
    advance_counters,
    heading_prefix,
)
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
_ZEBRA_FILL = "#F8F9FA"


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


def _pdf_alignment(align: str) -> Any:
    """模板对齐 → reportlab ``TA_*`` 常量（reportlab 只认整数常量）."""
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT

    return {
        "left": TA_LEFT,
        "center": TA_CENTER,
        "right": TA_RIGHT,
        "justify": TA_JUSTIFY,
    }.get(align, TA_LEFT)


def _pdf_text_rml(spans: Any, cjk_font: str, *, bold: bool = False) -> str:
    rml = _pdf_spans_rml(spans, cjk_font)
    return f"<b>{rml}</b>" if bold else rml


def _make_pdf_table_rml(
    rml_rows: list[list[str]],
    preset: ExportTheme | None = None,
    cjk_font: str = "Helvetica",
    width_percent: int = 100,
    aligns: tuple[str, ...] | None = None,
    *,
    table_cfg: TableConfig | None = None,
    usable_width: float | None = None,
) -> Any:
    """用可换行段落构造 PDF 表格（按内容分配列宽 + 表头重复 + 允许行内分页）."""
    from reportlab.lib import colors
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

    if table_cfg is not None:
        body_size = table_cfg.size
        header_size = table_cfg.size
        header_bg = table_cfg.header_bg
        header_color = table_cfg.header_color
        border_color = table_cfg.border_color
        three_line = table_cfg.style == "three_line"
        zebra = table_cfg.zebra
        valign = "MIDDLE" if table_cfg.cell_valign == "center" else "TOP"
        repeat_rows = 1 if table_cfg.header_repeat else 0
    else:
        body_size = 9.0
        header_size = 10.0
        header_bg = active.table_header_bg
        header_color = active.table_header_color
        border_color = "#808080"
        three_line = False
        zebra = True
        valign = "TOP"
        repeat_rows = 1

    weights = [max(_cell_weight(row[col]) for row in norm_rows) for col in range(max_cols)]
    total_width = (usable_width or _PDF_MAX_IMAGE_WIDTH) * width_percent / 100
    col_widths = fit_column_widths(weights, total_width)

    base = ParagraphStyle(
        "PdfCell",
        fontName=cjk_font,
        fontSize=body_size,
        leading=body_size * 1.35,
        wordWrap="CJK",
        spaceBefore=0,
        spaceAfter=0,
    )
    header_base = ParagraphStyle("PdfCellHeader", parent=base, fontSize=header_size, leading=header_size * 1.35)
    alignment = {name: _pdf_alignment(name) for name in ("left", "center", "right", "justify")}
    body_styles = [
        ParagraphStyle(f"PdfCell{col}", parent=base, alignment=alignment[col_aligns[col]]) for col in range(max_cols)
    ]
    header_styles = [
        ParagraphStyle(
            f"PdfCellHeader{col}",
            parent=header_base,
            alignment=alignment[col_aligns[col]],
            textColor=colors.HexColor(header_color),
        )
        for col in range(max_cols)
    ]

    cells: list[list[Any]] = []
    for row_index, row in enumerate(norm_rows):
        styles = header_styles if row_index == 0 else body_styles
        cells.append([Paragraph(row[col] or "&nbsp;", styles[col]) for col in range(max_cols)])

    table = Table(
        cells,
        repeatRows=repeat_rows,
        splitByRow=1,
        splitInRow=1,
        hAlign="LEFT",
        colWidths=col_widths,
    )
    commands: list[tuple[Any, ...]] = [
        ("VALIGN", (0, 0), (-1, -1), valign),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if three_line:
        # 三线表：表格顶线 / 表头下横线 / 表格底线，无竖线
        commands += [
            ("LINEABOVE", (0, 0), (-1, 0), 1.2, colors.HexColor(border_color)),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(border_color)),
            ("LINEBELOW", (0, -1), (-1, -1), 1.2, colors.HexColor(border_color)),
        ]
    else:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(border_color)),
        ]
        if zebra and len(norm_rows) > 1:
            commands.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(_ZEBRA_FILL)]))
    table.setStyle(TableStyle(commands))
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
    *,
    table_cfg: TableConfig | None = None,
    usable_width: float | None = None,
) -> Any:
    """构造 reportlab Table（纯文本入口，数据表引用与兼容调用使用）.

    ``width_percent`` 按正文可用宽度的百分比设置总列宽（数据表引用，缺省 100）。
    """
    if not rows:
        return _make_pdf_table_rml(
            [], preset, cjk_font, width_percent, aligns, table_cfg=table_cfg, usable_width=usable_width
        )
    rml_rows = [[_pdf_escape(str(cell)) for cell in row] for row in rows]
    return _make_pdf_table_rml(
        rml_rows, preset, cjk_font, width_percent, aligns, table_cfg=table_cfg, usable_width=usable_width
    )


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
    max_width: float | None = None,
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
    table = Table(rows, colWidths=[max_width or _PDF_MAX_IMAGE_WIDTH], hAlign="LEFT", splitByRow=1)
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


def _pdf_pagesize(cfg: ExportTemplateConfig) -> tuple[tuple[float, float], float]:
    """模板纸张 → reportlab pagesize 与页宽."""
    from reportlab.lib.pagesizes import A3, A4, LETTER

    pagesize = {"A4": A4, "A3": A3, "Letter": LETTER}.get(cfg.page.paper, A4)
    return pagesize, float(pagesize[0])


def _pdf_usable_width(cfg: ExportTemplateConfig) -> float:
    """正文可用宽度（页宽 - 左右页边距，1cm = 28.35pt）."""
    from reportlab.lib.units import cm

    _, width = _pdf_pagesize(cfg)
    usable = width - (cfg.page.margin_left + cfg.page.margin_right) * cm
    return float(max(120.0, usable))


def _make_footer_canvas_class(draw_footer: Any) -> Any:
    """生成延迟落页脚（「共 Y 页」需要总页数）的 canvas 子类."""
    from reportlab.pdfgen import canvas as canvas_module

    class _FooterCanvas(canvas_module.Canvas):
        """save 时已知总页数，因此可在最后一刻写「第 X 页 共 Y 页」."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._page_states: list[dict[str, Any]] = []

        @override
        def showPage(self) -> None:
            self._page_states.append(dict(self.__dict__))
            self._startPage()  # pyrefly: ignore[missing-attribute]

        @override
        def save(self) -> None:
            total = len(self._page_states)
            for state in self._page_states:
                self.__dict__.update(state)
                self.saveState()
                draw_footer(self, int(getattr(self, "_pageNumber", 0)), total)
                self.restoreState()
                canvas_module.Canvas.showPage(self)
            canvas_module.Canvas.save(self)

    return _FooterCanvas


def _render_pdf(
    markdown_text: str,
    title: str = "",
    images: ImageResolver | None = None,
    tables: TableResolver | None = None,
    template: ResolvedTemplate | None = None,
) -> bytes:
    # images：站内图片解析器；``![alt](file:<key>)`` 独占一行时嵌入真实图片
    # tables：数据表引用解析器；``{{table:…}}`` 独占一行时渲染为真实表格
    # 图表：正文 `` ```chart `` 内嵌块渲染为整幅图 PNG（ADR 0052，2 倍分辨率）
    """把文档 Markdown 正文渲染为 .pdf 字节流.

    排版参数来自导出模板（ADR 0152，与 docx 共用一份配置）。PDF 侧的限制：
    字体族按服务器已装 CJK 字体最佳匹配（``ensure_pdf_font``）并回落默认字体；
    字间距与域类特性（目录、Word 题注域）不可表达时静默跳过（D7）。
    """
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    cfg: ExportTemplateConfig = (
        template.config if template is not None else BUILTIN_TEMPLATES[DEFAULT_TEMPLATE_KEY].config
    )
    body = cfg.body
    table_cfg = cfg.table
    code_cfg = cfg.code
    list_cfg = cfg.lists
    header_footer = cfg.header_footer

    pagesize, page_width = _pdf_pagesize(cfg)
    usable_width = _pdf_usable_width(cfg)

    base_font = ensure_pdf_font(body.east_asia_font) or "Helvetica"
    heading_fonts = {level: ensure_pdf_font(cfg.heading(level).east_asia_font) or base_font for level in range(1, 7)}
    table_font = ensure_pdf_font(table_cfg.east_asia_font) or base_font
    code_font = ensure_pdf_font(code_cfg.east_asia_font) or base_font

    buf = io.BytesIO()
    title = title or "Document"

    styles = getSampleStyleSheet()
    body_leading = body.line_spacing_pt if body.line_spacing_rule == "fixed" else body.size * body.line_spacing
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=body.size,
        leading=body_leading,
        spaceBefore=body.space_before,
        spaceAfter=body.space_after,
        firstLineIndent=body.first_line_indent_chars * body.size,
        alignment=_pdf_alignment(body.align),
        wordWrap="CJK",
    )
    heading_styles: dict[int, Any] = {}
    for level in range(1, 7):
        heading_cfg = cfg.heading(level)
        heading_styles[level] = ParagraphStyle(
            f"H{level}",
            parent=styles["Normal"],
            fontName=heading_fonts[level],
            fontSize=heading_cfg.size,
            leading=heading_cfg.size * 1.3,
            spaceBefore=heading_cfg.space_before,
            spaceAfter=heading_cfg.space_after,
            firstLineIndent=heading_cfg.first_line_indent_chars * heading_cfg.size,
            alignment=_pdf_alignment(heading_cfg.align),
            textColor=HexColor(heading_cfg.color),
            wordWrap="CJK",
        )
    list_styles: dict[int, Any] = {}
    for level in range(8):
        list_styles[level] = ParagraphStyle(
            f"List{level}",
            parent=body_style,
            leftIndent=list_cfg.indent_pt * (level + 1),
            bulletIndent=list_cfg.indent_pt * level,
            firstLineIndent=0,
            spaceAfter=list_cfg.space_after,
            bulletFontName=base_font,
            bulletFontSize=body.size,
        )

    story: list[Any] = []
    counters = [0] * 6
    figure_no = 0
    table_no = 0
    segments = split_inline_chart_segments(markdown_text)
    plain_blocks = [parse_blocks(segment) for segment in segments if isinstance(segment, str)]

    # 编号权威判定（ADR 0186 I1 / I2）：全篇只看一次，正文自带序号则模板编号让位
    all_blocks = [block for blocks_ in plain_blocks for block in blocks_]
    heading_scheme = resolve_heading_numbering(cfg.numbering.mode, cfg.numbering.heading, all_blocks)
    # 正文最高一级标题视为编号第 1 级（文档标题由文件名 / core_properties.title 承担）
    number_offset = heading_level_offset(all_blocks)

    def _caption_text(kind: str, style_cfg: Any, number: int, text: str) -> str:
        if has_explicit_caption_number(text):  # 正文已自带「图 1」，不叠加
            return text.strip()
        label = "图" if kind == "figure" else "表"
        if style_cfg.numbering == "n-n":
            return f"{label} {counters[0] or 1}-{number}　{text}".strip()
        return f"{label} {number}　{text}".strip()

    def _caption_style(style_cfg: Any) -> Any:
        return ParagraphStyle(
            "Caption",
            parent=styles["Normal"],
            fontName=base_font,
            fontSize=style_cfg.size,
            leading=style_cfg.size * 1.4,
            spaceBefore=2,
            spaceAfter=6,
            alignment=_pdf_alignment(style_cfg.align),
            wordWrap="CJK",
        )

    def _add_caption(kind: str, style_cfg: Any, number: int, text: str) -> None:
        if not text:
            return
        caption = _caption_text(kind, style_cfg, number, text)
        story.append(Paragraph(_pdf_escape(caption), _caption_style(style_cfg)))

    def _add_chart_block(block: InlineChartBlock) -> None:
        """内嵌图表块 → 整幅图 PNG；坏块降级为占位段落（ADR 0052 D11）."""
        if block.error:
            story.append(Paragraph(_pdf_escape(block_error_message(block.error)), body_style))
            return
        fallback = f"[图表无法嵌入：{block.title or '图表'}]"
        try:
            rendered = render_inline_chart(block)
            figure = _make_pdf_image(
                (to_png(rendered, scale=2), "chart.png"), max_width=usable_width * block.width / 100
            )
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
                cjk_font=table_font,
                width_percent=spec.width,
                table_cfg=table_cfg,
                usable_width=usable_width,
            )
        )
        story.append(Spacer(1, 6))

    def _add_image(block: ImageBlock) -> None:
        nonlocal figure_no
        resolved = images(block.key) if images is not None else None
        caption_cfg = cfg.captions.figure
        text = (block.alt or "").strip()
        figure = _make_pdf_image(resolved, max_width=usable_width)
        if figure is None:
            story.append(Paragraph(_pdf_escape(f"[图片缺失：{block.alt}]"), body_style))
            return
        if caption_cfg.enabled and text:
            figure_no += 1
            if caption_cfg.position == "above":
                _add_caption("figure", caption_cfg, figure_no, text)
        story.append(figure)
        if caption_cfg.enabled and text and caption_cfg.position == "below":
            _add_caption("figure", caption_cfg, figure_no, text)
        story.append(Spacer(1, 6))

    def _add_code(block: CodeBlock) -> None:
        lines = [_pdf_code_line_rml(line, code_font) for line in block.code.split("\n")]
        story.append(
            _pdf_boxed_lines(
                lines,
                code_font,
                background=code_cfg.bg,
                left_bar=code_cfg.border if code_cfg.left_bar else None,
                font_size=code_cfg.size,
                max_width=usable_width,
            )
        )
        story.append(Spacer(1, 6))

    def _add_quote(block: QuoteBlock) -> None:
        lines = [_pdf_spans_rml(line, base_font) for line in block.lines]
        story.append(
            _pdf_boxed_lines(
                lines, base_font, left_bar="#D0D0D0", color=_QUOTE_COLOR, italic=True, max_width=usable_width
            )
        )

    def _add_heading(block: HeadingBlock) -> None:
        level = min(max(block.level, 1), 6)
        advance_counters(counters, max(level - number_offset, 1))
        prefix = heading_prefix(heading_scheme, max(level - number_offset, 1), counters)
        text = _pdf_text_rml(block.spans, heading_fonts[level], bold=cfg.heading(level).bold)
        if prefix:
            text = f"{_pdf_escape(prefix)} {text}"
        story.append(Paragraph(text, heading_styles[level]))

    def _add_blocks(blocks: list[Block]) -> None:
        nonlocal table_no
        caption_cfg = cfg.captions.table
        skip_indexes: set[int] = set()
        captions: dict[int, str] = {}
        if caption_cfg.enabled:
            for index, block in enumerate(blocks):
                if not isinstance(block, (TableBlock, TableRefBlock)) or index == 0:
                    continue
                previous = blocks[index - 1]
                if not isinstance(previous, ParagraphBlock):
                    continue
                match = TABLE_CAPTION_RE.match(plain_text(previous.spans).strip())
                if match is None:
                    continue
                skip_indexes.add(index - 1)
                captions[index] = match.group("text").strip()
        for index, block in enumerate(blocks):
            if index in skip_indexes:
                continue
            table_caption = captions.get(index)
            if table_caption and caption_cfg.position == "above":
                table_no += 1
                _add_caption("table", caption_cfg, table_no, table_caption)
            if isinstance(block, HeadingBlock):
                _add_heading(block)
            elif isinstance(block, ParagraphBlock):
                story.append(Paragraph(_pdf_text_rml(block.spans, base_font, bold=body.bold), body_style))
            elif isinstance(block, ListBlock):
                for item in block.items:
                    story.append(
                        Paragraph(
                            _pdf_text_rml(item.spans, base_font, bold=body.bold),
                            list_styles[min(item.level, len(list_styles) - 1)],
                            bulletText=item.marker,
                        )
                    )
            elif isinstance(block, TableBlock):
                story.append(
                    _make_pdf_table_rml(
                        [
                            [_pdf_spans_rml(cell, table_font) for cell in block.header],
                            *[[_pdf_spans_rml(cell, table_font) for cell in row] for row in block.rows],
                        ],
                        cjk_font=table_font,
                        aligns=block.aligns,
                        table_cfg=table_cfg,
                        usable_width=usable_width,
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
            if table_caption and caption_cfg.position == "below":
                _add_caption("table", caption_cfg, table_no, table_caption)

    for segment in segments:
        if isinstance(segment, str):
            _add_blocks(parse_blocks(segment))
            continue
        _add_chart_block(segment)

    footer_font = ensure_pdf_font(body.east_asia_font) or "Helvetica"

    def _draw_footer(canvas_obj: Any, page: int, total: int) -> None:
        mode = header_footer.page_number
        if mode == "none" or (header_footer.first_page_different and page == 1):
            return
        canvas_obj.setFont(footer_font, header_footer.font_size)
        if mode == "plain":
            text = str(page)
        elif mode == "page":
            text = f"第 {page} 页"
        else:
            text = f"第 {page} 页 共 {total} 页"
        canvas_obj.drawCentredString(page_width / 2, 1.5 * cm, text)

    def _on_page(canvas_obj: Any, doc: Any) -> None:
        """页眉（页脚由 canvas 收尾时统一绘制，见 _draw_footer）."""
        canvas_obj.saveState()
        if header_footer.header_text and not (header_footer.first_page_different and doc.page == 1):
            canvas_obj.setFont(footer_font, header_footer.font_size)
            canvas_obj.drawCentredString(page_width / 2, pagesize[1] - 1.5 * cm, header_footer.header_text)
        canvas_obj.restoreState()

    def _draw_everything(canvas_obj: Any, doc: Any) -> None:
        _on_page(canvas_obj, doc)
        canvas_obj.saveState()
        _draw_footer(canvas_obj, doc.page, 0)
        canvas_obj.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=pagesize,
        leftMargin=cfg.page.margin_left * cm,
        rightMargin=cfg.page.margin_right * cm,
        topMargin=cfg.page.margin_top * cm,
        bottomMargin=cfg.page.margin_bottom * cm,
        title=str(title),
    )
    if header_footer.page_number == "page_of_total":
        # 「共 Y 页」需要总页数：延迟 showPage，在 save 时统一写页脚
        doc.build(
            story,
            onFirstPage=_on_page,
            onLaterPages=_on_page,
            canvasmaker=_make_footer_canvas_class(_draw_footer),
        )
    else:
        doc.build(story, onFirstPage=_draw_everything, onLaterPages=_draw_everything)
    buf.seek(0)
    return buf.getvalue()


def _export_timestamp() -> str:
    """PDF 页眉右侧固定文本（导出时刻）."""
    import datetime as dt

    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


__all__ = [
    "_ensure_pdf_font",
    "_export_timestamp",
    "_make_pdf_table",
    "_pdf_escape",
    "_pdf_markdown_to_rml",
    "_pdf_table_style_cmds",
    "_render_pdf",
]
