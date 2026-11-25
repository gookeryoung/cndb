"""DOCX 导出器：Markdown 风格标题/列表/代码/表格 → Word 文档.

块级 / 行内语法统一由 :mod:`markdown_blocks` 解析，本模块只负责映射到
python-docx 对象。历史实现只处理标题 / 加粗 / 行内代码，列表、代码围栏、
引用与分隔线原样落成段落，表格也未固定布局，因此与预览差异明显。
"""

from __future__ import annotations

import io
import logging
from typing import Any, cast

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
from cndb.plugins.documents.services.export.table_refs import (
    ResolvedTable,
    TableResolver,
    parse_table_ref_line,
)
from cndb.plugins.documents.services.export.templates import (
    BUILTIN_TEMPLATES,
    DEFAULT_TEMPLATE_KEY,
    TABLE_CAPTION_RE,
    ExportTemplateConfig,
    ResolvedTemplate,
    advance_counters,
    heading_prefix,
)

logger = logging.getLogger(__name__)

_LINK_COLOR = "1A6FB5"
#: 斑马纹 / 三线表 / 引用块的固定浅色（不作为模板配置项，避免配置面无限膨胀）
_ZEBRA_FILL = "F5F7FA"
_QUOTE_COLOR = "555555"
_CODE_BG = "F6F8FA"
_CODE_BORDER = "E5E7EB"


_PPR_ORDER_TAIL = (
    "w:tabs",
    "w:suppressAutoHyphens",
    "w:kinsoku",
    "w:wordWrap",
    "w:overflowPunct",
    "w:topLinePunct",
    "w:autoSpaceDE",
    "w:autoSpaceDN",
    "w:bidi",
    "w:adjustRightInd",
    "w:snapToGrid",
    "w:spacing",
    "w:ind",
    "w:contextualSpacing",
    "w:mirrorIndents",
    "w:suppressOverlap",
    "w:jc",
    "w:textDirection",
    "w:textAlignment",
    "w:textboxTightWrap",
    "w:outlineLvl",
    "w:divId",
    "w:cnfStyle",
    "w:rPr",
    "w:sectPr",
    "w:pPrChange",
)


def _apply_run_font(
    run: Any,
    font: str,
    size: float | None = None,
    color: str | None = None,
    *,
    east_asia: str | None = None,
    char_spacing: float | None = None,
) -> None:
    """给 run 设置字体名（ascii / hAnsi / eastAsia）、字号、颜色、字间距."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    run.font.name = font
    fonts = run._element.get_or_add_rPr().get_or_add_rFonts()
    fonts.set(qn("w:ascii"), font)
    fonts.set(qn("w:hAnsi"), font)
    fonts.set(qn("w:eastAsia"), east_asia or font)
    if size is not None:
        run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = RGBColor.from_string(color.lstrip("#"))
    if char_spacing:
        # w:spacing 单位是 1/20 pt
        spacing = OxmlElement("w:spacing")
        spacing.set(qn("w:val"), str(int(char_spacing * 20)))
        run._element.get_or_add_rPr().append(spacing)


def _add_hyperlink(paragraph: Any, text: str, href: str, font: str, size: float | None = None) -> bool:
    """向段落追加真实超链接（``w:hyperlink``）；相对锚点等无法建关系时返回 False."""
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    if not href or href.startswith("#"):
        return False
    try:
        rel_id = paragraph.part.relate_to(href, RT.HYPERLINK, is_external=True)
    except Exception:
        return False
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), rel_id)
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia"):
        fonts.set(qn(attr), font)
    properties.append(fonts)
    color = OxmlElement("w:color")
    color.set(qn("w:val"), _LINK_COLOR)
    properties.append(color)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    properties.append(underline)
    if size is not None:
        half_points = OxmlElement("w:sz")
        half_points.set(qn("w:val"), str(int(size * 2)))
        properties.append(half_points)
    run.append(properties)
    text_element = OxmlElement("w:t")
    text_element.set(qn("xml:space"), "preserve")
    text_element.text = text
    run.append(text_element)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)
    return True


def _add_inline_runs(
    paragraph: Any,
    spans: tuple[InlineSpan, ...] | list[InlineSpan],
    body_font: str,
    code_font: str,
    *,
    size: float | None = None,
    color: str | None = None,
    bold: bool = False,
    italic: bool = False,
    east_asia_font: str | None = None,
    code_east_asia_font: str | None = None,
    char_spacing: float | None = None,
) -> None:
    """把行内片段写成 docx run（粗体 / 斜体 / 删除线 / 行内代码 / 链接 / 换行）."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    for span in spans:
        if span.kind == INLINE_BREAK:
            paragraph.add_run().add_break()
            continue
        if span.kind == INLINE_LINK and _add_hyperlink(paragraph, span.text, span.href, body_font, size):
            continue
        run = paragraph.add_run(span.text)
        is_code = span.kind == INLINE_CODE
        font = code_font if is_code else body_font
        _apply_run_font(
            run,
            font,
            size,
            color,
            east_asia=(code_east_asia_font if is_code else east_asia_font) or font,
            char_spacing=None if is_code else char_spacing,
        )
        if bold or span.kind == INLINE_BOLD:
            run.bold = True
        if italic or span.kind == INLINE_ITALIC:
            run.italic = True
        if span.kind == INLINE_STRIKE:
            run.font.strike = True
        if span.kind == INLINE_LINK:
            run.underline = True
            if color is None:
                from docx.shared import RGBColor

                run.font.color.rgb = RGBColor.from_string(_LINK_COLOR)
        if span.kind == INLINE_CODE:
            if size is not None:
                run.font.size = Pt(size - 0.5)
            shaded = OxmlElement("w:shd")
            shaded.set(qn("w:val"), "clear")
            shaded.set(qn("w:color"), "auto")
            shaded.set(qn("w:fill"), _CODE_BG)
            run._element.get_or_add_rPr().append(shaded)


def _add_rich_runs(paragraph: Any, text: str, body_font: str = "Calibri", code_font: str = "Courier New") -> None:
    """兼容入口：把一段 Markdown 行内文本写成 runs."""
    _add_inline_runs(paragraph, parse_inline(text), body_font, code_font)


def _shade_paragraph(paragraph: Any, fill: str) -> None:
    """段落底纹（代码块 / 表头以外的整段背景）."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = paragraph._p.get_or_add_pPr()
    shaded = OxmlElement("w:shd")
    shaded.set(qn("w:val"), "clear")
    shaded.set(qn("w:color"), "auto")
    shaded.set(qn("w:fill"), fill)
    properties.insert_element_before(shaded, "w:tabs", *(_PPR_ORDER_TAIL[1:]))


def _border_paragraph(paragraph: Any, sides: tuple[str, ...], color: str, size: int = 4) -> None:
    """段落边框（引用左边线 / 代码块外框 / 分隔线）."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    for side in sides:
        border = OxmlElement(f"w:{side}")
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), str(size))
        border.set(qn("w:space"), "4")
        border.set(qn("w:color"), color)
        borders.append(border)
    properties.insert_element_before(borders, "w:shd", *_PPR_ORDER_TAIL)


def _set_cell_margins(table: Any) -> None:
    """表格单元格内边距（0.14cm 左右 / 0.07cm 上下，接近预览 6px 12px）."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    margins = OxmlElement("w:tblCellMar")
    for side, width in (("top", 40), ("left", 80), ("bottom", 40), ("right", 80)):
        element = OxmlElement(f"w:{side}")
        element.set(qn("w:w"), str(width))
        element.set(qn("w:type"), "dxa")
        margins.append(element)
    table._tbl.tblPr.insert_element_before(margins, "w:tblLook", "w:tblCaption", "w:tblDescription", "w:tblPrChange")


def _set_table_width_twips(table: Any, total_emu: float) -> None:
    """Markdown 表格按正文可用宽度写 ``w:tblW``（dxa，避免与引用表的百分比串味）."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    table_width = table._tbl.tblPr.find(qn("w:tblW"))
    if table_width is None:
        table_width = OxmlElement("w:tblW")
        table._tbl.tblPr.append(table_width)
    table_width.set(qn("w:type"), "dxa")
    table_width.set(qn("w:w"), str(int(total_emu / 635)))


def _set_table_ref_width(table: Any, percent: int) -> None:
    """按正文宽度的百分比设置 DOCX 表宽（``w:tblW`` 用 1/50 百分比单位）."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:type"), "pct")
    # Word 的 pct 单位是 1/50 百分比：75% → 3750
    tbl_w.set(qn("w:w"), str(int(percent * 50)))


def _mark_header_row(row: Any) -> None:
    """表头跨页重复（``w:tblHeader``）."""
    from docx.oxml import OxmlElement

    row._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))


def _prevent_row_split(row: Any) -> None:
    """禁止单元格内容跨页切断（``w:cantSplit``），整行过高时由 Word 兜底分页."""
    from docx.oxml import OxmlElement

    row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))


def _docx_usable_width(doc: Any) -> int:
    """正文可用宽度（EMU）；取不到时回退 14cm."""
    from docx.shared import Cm

    try:
        section = doc.sections[0]
        usable = section.page_width - section.left_margin - section.right_margin
        if usable and usable > 0:
            return int(usable)
    except (IndexError, AttributeError):  # pragma: no cover - 极端文档结构
        pass
    return int(Cm(14))


def _docx_image_width(doc: Any, percent: int = 100) -> Any:
    """图片宽度 = 正文可用宽度 × 百分比（缺省 100）；取不到时回退 14cm 的对应比例."""
    return int(_docx_usable_width(doc) * percent / 100)


def _docx_natural_width(data: bytes) -> int | None:
    """图片像素宽度换算成 EMU（按 96dpi：1px = 0.75pt）；解码失败返回 None."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return int(image.width * 0.75 * 12700)
    except Exception:
        return None


def _add_field(paragraph: Any, instruction: str, font: str, size: float, east_asia: str | None = None) -> None:
    """插入 Word 域（``PAGE`` / ``NUMPAGES``），页码在打开文档时由 Word 计算."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = paragraph.add_run()
    _apply_run_font(run, font, size, east_asia=east_asia)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction_el = OxmlElement("w:instrText")
    instruction_el.set(qn("xml:space"), "preserve")
    instruction_el.text = instruction
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    placeholder = OxmlElement("w:t")
    placeholder.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for element in (begin, instruction_el, separate, placeholder, end):
        run._r.append(element)


def _set_first_line_indent(paragraph: Any, chars: float, size: float) -> None:
    """首行缩进按**字符**（``w:firstLineChars``），换字号时缩进不漂移."""
    if chars <= 0:
        return
    from docx.oxml.ns import qn
    from docx.shared import Pt

    paragraph.paragraph_format.first_line_indent = Pt(chars * size)
    ind = paragraph._p.get_or_add_pPr().find(qn("w:ind"))
    if ind is not None:  # pragma: no branch - first_line_indent 必产生 w:ind
        ind.set(qn("w:firstLineChars"), str(int(chars * 100)))


def _set_table_borders(table: Any, color: str, style: str) -> None:
    """表格边框：``single`` 全网格；``three_line`` 只保留表格顶 / 底两条横线."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tbl_pr = table._tbl.tblPr
    existing = tbl_pr.find(qn("w:tblBorders"))
    if existing is not None:
        tbl_pr.remove(existing)
    borders = OxmlElement("w:tblBorders")
    spec = (
        {"top": 12, "bottom": 12, "insideH": 4, "left": 4, "right": 4, "insideV": 4}
        if style == "single"
        else {"top": 12, "bottom": 12, "insideH": 0, "left": 0, "right": 0, "insideV": 0}
    )
    for side, width in spec.items():
        border = OxmlElement(f"w:{side}")
        if width == 0:
            border.set(qn("w:val"), "nil")
        else:
            border.set(qn("w:val"), "single")
            border.set(qn("w:sz"), str(width))
            border.set(qn("w:space"), "0")
            border.set(qn("w:color"), color.lstrip("#"))
        borders.append(border)
    tbl_pr.insert_element_before(
        borders,
        "w:shd",
        "w:tblLayout",
        "w:tblCellMar",
        "w:tblLook",
        "w:tblCaption",
        "w:tblDescription",
        "w:tblPrChange",
    )


def _cell_bottom_border(cell: Any, color: str, width: int = 8) -> None:
    """三线表的表头下横线（单元格级，避免影响其它行的边框）."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tc_pr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(width))
    bottom.set(qn("w:space"), "0")
    bottom.set(qn("w:color"), color.lstrip("#"))
    borders.append(bottom)
    tc_pr.insert_element_before(borders, "w:shd", "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign")


_PAPER_SIZES_CM: dict[str, tuple[float, float]] = {
    "A4": (21.0, 29.7),
    "A3": (29.7, 42.0),
    "Letter": (21.59, 27.94),
}


def _configure_section(doc: Any, cfg: ExportTemplateConfig, title: str) -> None:
    """页面尺寸 / 页边距 / 页眉文字 / 页脚页码（仅模板启用时才创建对应部件）."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm

    _ = title
    section = doc.sections[0]
    width_cm, height_cm = _PAPER_SIZES_CM.get(cfg.page.paper, _PAPER_SIZES_CM["A4"])
    section.page_width = Cm(width_cm)
    section.page_height = Cm(height_cm)
    section.top_margin = Cm(cfg.page.margin_top)
    section.bottom_margin = Cm(cfg.page.margin_bottom)
    section.left_margin = Cm(cfg.page.margin_left)
    section.right_margin = Cm(cfg.page.margin_right)

    header_footer = cfg.header_footer
    body = cfg.body
    if header_footer.header_text:
        paragraph = section.header.paragraphs[0]
        for run in list(paragraph.runs):
            run._element.getparent().remove(run._element)
        run = paragraph.add_run(header_footer.header_text)
        _apply_run_font(run, body.latin_font, header_footer.font_size, east_asia=body.east_asia_font)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if header_footer.page_number == "none":
        return
    if header_footer.first_page_different:
        section.different_first_page_header_footer = True
    paragraph = section.footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    mode = header_footer.page_number
    size = header_footer.font_size

    def _text(value: str) -> None:
        run = paragraph.add_run(value)
        _apply_run_font(run, body.latin_font, size, east_asia=body.east_asia_font)

    if mode == "page":
        _text("第 ")
    _add_field(paragraph, "PAGE", body.latin_font, size, east_asia=body.east_asia_font)
    if mode == "page":
        _text(" 页")
    elif mode == "page_of_total":
        _text(" 页 共 ")
        _add_field(paragraph, "NUMPAGES", body.latin_font, size, east_asia=body.east_asia_font)
        _text(" 页")


def _render_docx(
    markdown_text: str,
    title: str = "",
    images: ImageResolver | None = None,
    tables: TableResolver | None = None,
    template: ResolvedTemplate | None = None,
) -> bytes:
    """把文档 Markdown 正文渲染为 .docx 字节流（ADR 0152）.

    - images：站内图片解析器；``![alt](file:<key>)`` 独占一行时嵌入真实图片
    - tables：数据表引用解析器；``{{table:…}}`` 独占一行时渲染为真实表格
    - 图表：正文 `` ```chart `` 内嵌块渲染为整幅图 PNG（ADR 0052）
    - template：导出模板（``None`` = 内置 ``research``（研究报告））
    """
    from docx import Document
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Emu, Pt
    from docx.styles.style import ParagraphStyle as DocxParagraphStyle

    cfg: ExportTemplateConfig = (
        template.config if template is not None else BUILTIN_TEMPLATES[DEFAULT_TEMPLATE_KEY].config
    )
    body = cfg.body
    table_cfg = cfg.table
    code_cfg = cfg.code
    list_cfg = cfg.lists
    doc = Document()
    if title:
        doc.core_properties.title = title

    _configure_section(doc, cfg, title)

    # 全局正文样式（Normal）：中西文分列字体，保留东亚映射
    normal = cast(DocxParagraphStyle, doc.styles["Normal"])
    normal.font.name = body.latin_font
    normal.font.size = Pt(body.size)
    normal.font.bold = body.bold
    normal_fonts = normal.element.get_or_add_rPr().get_or_add_rFonts()
    normal_fonts.set(qn("w:ascii"), body.latin_font)
    normal_fonts.set(qn("w:hAnsi"), body.latin_font)
    normal_fonts.set(qn("w:eastAsia"), body.east_asia_font)

    align_map = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }

    def _body_runs(paragraph: Any, spans: Any, *, size: float | None = None, color: str | None = None) -> None:
        _add_inline_runs(
            paragraph,
            spans,
            body.latin_font,
            code_cfg.latin_font,
            size=size if size is not None else body.size,
            color=color,
            bold=body.bold,
            east_asia_font=body.east_asia_font,
            code_east_asia_font=code_cfg.east_asia_font,
            char_spacing=body.char_spacing,
        )

    def _apply_body_format(paragraph: Any) -> None:
        formatting = paragraph.paragraph_format
        paragraph.alignment = align_map[body.align]
        if body.line_spacing_rule == "fixed":
            formatting.line_spacing = Pt(body.line_spacing_pt)
        else:
            formatting.line_spacing = body.line_spacing
        formatting.space_before = Pt(body.space_before)
        formatting.space_after = Pt(body.space_after)
        formatting.widow_control = body.widow_control
        formatting.keep_with_next = body.keep_with_next
        _set_first_line_indent(paragraph, body.first_line_indent_chars, body.size)

    counters = [0] * 6
    figure_no = 0
    table_no = 0

    def _caption_text(kind: str, style_cfg: Any, number: int, text: str) -> str:
        label = "图" if kind == "figure" else "表"
        if style_cfg.numbering == "n-n":
            chapter = counters[0] or 1
            return f"{label} {chapter}-{number}　{text}".strip()
        return f"{label} {number}　{text}".strip()

    def _add_caption(kind: str, style_cfg: Any, number: int, text: str) -> None:
        if not text:
            return
        paragraph = doc.add_paragraph()
        paragraph.alignment = align_map.get(style_cfg.align, WD_ALIGN_PARAGRAPH.CENTER)
        formatting = paragraph.paragraph_format
        formatting.space_before = Pt(2)
        formatting.space_after = Pt(6)
        run = paragraph.add_run(_caption_text(kind, style_cfg, number, text))
        _apply_run_font(run, body.latin_font, style_cfg.size, east_asia=body.east_asia_font)

    def _add_heading(block: HeadingBlock) -> None:
        level = min(max(block.level, 1), 6)
        heading_cfg = cfg.heading(level)
        advance_counters(counters, level)
        prefix = heading_prefix(cfg.numbering.heading, level, counters)
        try:
            paragraph = doc.add_heading("", level=level)
        except (KeyError, ValueError):  # pragma: no cover - 某些 Word 模板缺少 Heading 5+
            paragraph = doc.add_paragraph()
        paragraph.alignment = align_map[heading_cfg.align]
        formatting = paragraph.paragraph_format
        formatting.space_before = Pt(heading_cfg.space_before)
        formatting.space_after = Pt(heading_cfg.space_after)
        formatting.keep_with_next = heading_cfg.keep_with_next
        _set_first_line_indent(paragraph, heading_cfg.first_line_indent_chars, heading_cfg.size)
        if prefix:
            prefix_run = paragraph.add_run(f"{prefix} ")
            _apply_run_font(
                prefix_run,
                heading_cfg.latin_font,
                heading_cfg.size,
                heading_cfg.color,
                east_asia=heading_cfg.east_asia_font,
            )
            prefix_run.bold = heading_cfg.bold
        _add_inline_runs(
            paragraph,
            block.spans,
            heading_cfg.latin_font,
            code_cfg.latin_font,
            size=heading_cfg.size,
            color=heading_cfg.color,
            bold=heading_cfg.bold,
            east_asia_font=heading_cfg.east_asia_font,
            code_east_asia_font=code_cfg.east_asia_font,
        )

    def _add_paragraph(block: ParagraphBlock) -> None:
        paragraph = doc.add_paragraph()
        _apply_body_format(paragraph)
        _body_runs(paragraph, block.spans)

    def _add_list(block: ListBlock) -> None:
        marker_map = {"dash": "-", "dot": "·"}
        for item in block.items:
            paragraph = doc.add_paragraph()
            paragraph.alignment = align_map[body.align]
            formatting = paragraph.paragraph_format
            left = Pt(list_cfg.indent_pt * (item.level + 1))
            formatting.left_indent = left
            formatting.first_line_indent = Pt(-list_cfg.hanging_pt)
            formatting.space_before = Pt(0)
            formatting.space_after = Pt(list_cfg.space_after)
            formatting.widow_control = body.widow_control
            formatting.tab_stops.add_tab_stop(left)
            marker_text = item.marker
            if marker_text == "•" and list_cfg.marker in marker_map:
                marker_text = marker_map[list_cfg.marker]
            marker = paragraph.add_run(f"{marker_text}\t")
            _apply_run_font(marker, body.latin_font, body.size, east_asia=body.east_asia_font)
            _body_runs(paragraph, item.spans)

    def _add_code(block: CodeBlock) -> None:
        paragraph = doc.add_paragraph()
        formatting = paragraph.paragraph_format
        formatting.left_indent = Pt(6)
        formatting.right_indent = Pt(6)
        formatting.space_before = Pt(4)
        formatting.space_after = Pt(8)
        formatting.line_spacing = 1.0
        if code_cfg.left_bar:
            _border_paragraph(paragraph, ("left",), code_cfg.border, size=18)
        else:
            _border_paragraph(paragraph, ("top", "left", "bottom", "right"), code_cfg.border)
        _shade_paragraph(paragraph, code_cfg.bg.lstrip("#"))
        for index, line in enumerate(block.code.split("\n")):
            if index:
                paragraph.add_run().add_break()
            run = paragraph.add_run(line or (" " if not block.code else ""))
            _apply_run_font(run, code_cfg.latin_font, code_cfg.size, east_asia=code_cfg.east_asia_font)

    def _add_quote(block: QuoteBlock) -> None:
        for spans in block.lines:
            paragraph = doc.add_paragraph()
            formatting = paragraph.paragraph_format
            formatting.left_indent = Pt(12)
            formatting.right_indent = Pt(6)
            formatting.space_before = Pt(0)
            formatting.space_after = Pt(2)
            _border_paragraph(paragraph, ("left",), "#D0D0D0", size=18)
            _add_inline_runs(
                paragraph,
                spans or (InlineSpan("text", " "),),
                body.latin_font,
                code_cfg.latin_font,
                size=body.size,
                color=f"#{_QUOTE_COLOR}",
                italic=True,
                east_asia_font=body.east_asia_font,
                code_east_asia_font=code_cfg.east_asia_font,
            )

    def _add_rule() -> None:
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(2)
        paragraph.paragraph_format.space_after = Pt(8)
        _border_paragraph(paragraph, ("bottom",), "#DDDDDD", size=6)

    def _add_picture(data: bytes, alt: str, percent: int = 100) -> None:
        natural = _docx_natural_width(data)
        width = _docx_image_width(doc, percent)
        if natural is not None:
            width = min(width, natural)
        try:
            doc.add_picture(io.BytesIO(data), width=Emu(int(width)))
        except Exception:
            doc.add_paragraph(f"[图片无法嵌入：{alt}]")

    def _add_image(block: ImageBlock) -> None:
        nonlocal figure_no
        resolved = images(block.key) if images is not None else None
        if resolved is None:
            doc.add_paragraph(f"[图片缺失：{block.alt}]")
            return
        caption_cfg = cfg.captions.figure
        text = (block.alt or "").strip()
        if caption_cfg.enabled and text:
            figure_no += 1
            if caption_cfg.position == "above":
                _add_caption("figure", caption_cfg, figure_no, text)
        _add_picture(resolved[0], block.alt)
        if caption_cfg.enabled and text and caption_cfg.position == "below":
            _add_caption("figure", caption_cfg, figure_no, text)

    def _cell_width(spans: tuple[InlineSpan, ...]) -> float:
        return float(max(6, display_width(plain_text(spans))))

    def _create_table(row_count: int, col_count: int, weights: list[float], width_percent: int | None) -> Any:
        usable = _docx_usable_width(doc)
        total = usable * (width_percent if width_percent is not None else 100) / 100
        widths = fit_column_widths(weights, total)
        table = doc.add_table(rows=row_count, cols=col_count)
        table.style = "Table Grid"
        table.autofit = False
        _set_cell_margins(table)
        _set_table_borders(table, table_cfg.border_color, table_cfg.style)
        if width_percent is not None:
            _set_table_ref_width(table, width_percent)
        else:
            _set_table_width_twips(table, total)
        for column, width in zip(table.columns, widths, strict=True):
            column.width = Emu(int(width))
            for cell in column.cells:
                cell.width = Emu(int(width))
        for row in table.rows:
            _prevent_row_split(row)
        if table_cfg.header_repeat:
            _mark_header_row(table.rows[0])
        return table

    def _format_cell(cell: Any, align: str) -> Any:
        paragraph = cell.paragraphs[0]
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing = 1.15
        paragraph.alignment = align_map.get(align, WD_ALIGN_PARAGRAPH.LEFT)
        cell.vertical_alignment = (
            WD_CELL_VERTICAL_ALIGNMENT.CENTER if table_cfg.cell_valign == "center" else WD_CELL_VERTICAL_ALIGNMENT.TOP
        )
        return paragraph

    def _shade_cell(cell: Any, fill: str) -> None:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        shaded = OxmlElement("w:shd")
        shaded.set(qn("w:val"), "clear")
        shaded.set(qn("w:color"), "auto")
        shaded.set(qn("w:fill"), fill.lstrip("#"))
        cell._tc.get_or_add_tcPr().append(shaded)

    def _decorate_body_row(cell: Any, row_index: int) -> None:
        if table_cfg.zebra and row_index > 0 and row_index % 2 == 1:
            _shade_cell(cell, _ZEBRA_FILL)

    def _decorate_header_cell(cell: Any) -> None:
        if table_cfg.style == "single":
            _shade_cell(cell, table_cfg.header_bg)
        else:
            _cell_bottom_border(cell, table_cfg.border_color)

    def _write_markdown_table(block: TableBlock) -> None:
        columns = len(block.header)
        rows = [block.header, *block.rows]
        weights = [max(_cell_width(row[col]) for row in rows) for col in range(columns)]
        table = _create_table(len(rows), columns, weights, None)
        for row_index, row in enumerate(rows):
            for col in range(columns):
                cell = table.cell(row_index, col)
                paragraph = _format_cell(cell, block.aligns[col] if col < len(block.aligns) else "left")
                spans = row[col] if col < len(row) else (InlineSpan("text", ""),)
                if row_index == 0:
                    _decorate_header_cell(cell)
                    _add_inline_runs(
                        paragraph,
                        spans,
                        table_cfg.latin_font,
                        code_cfg.latin_font,
                        size=table_cfg.size,
                        color=table_cfg.header_color,
                        bold=table_cfg.header_bold,
                        east_asia_font=table_cfg.east_asia_font,
                        code_east_asia_font=code_cfg.east_asia_font,
                    )
                else:
                    _decorate_body_row(cell, row_index)
                    _add_inline_runs(
                        paragraph,
                        spans,
                        table_cfg.latin_font,
                        code_cfg.latin_font,
                        size=table_cfg.size,
                        bold=body.bold,
                        east_asia_font=table_cfg.east_asia_font,
                        code_east_asia_font=code_cfg.east_asia_font,
                    )

    def _write_plain_table(rows: list[list[str]], width_percent: int | None = None) -> None:
        """数据表引用：单元格按纯文本写入（数值里的 * / ` 不当 Markdown 解释）."""
        columns = max(len(row) for row in rows)
        if columns == 0:
            return
        normalized = [row + [""] * (columns - len(row)) for row in rows]
        weights = [float(max(6, *(display_width(row[col]) for row in normalized))) for col in range(columns)]
        table = _create_table(len(normalized), columns, weights, width_percent)
        for row_index, row in enumerate(normalized):
            for col in range(columns):
                cell = table.cell(row_index, col)
                paragraph = _format_cell(cell, "left")
                run = paragraph.add_run(row[col])
                if row_index == 0:
                    run.bold = table_cfg.header_bold
                    _decorate_header_cell(cell)
                    _apply_run_font(
                        run,
                        table_cfg.latin_font,
                        table_cfg.size,
                        color=table_cfg.header_color,
                        east_asia=table_cfg.east_asia_font,
                    )
                else:
                    _decorate_body_row(cell, row_index)
                    _apply_run_font(run, table_cfg.latin_font, table_cfg.size, east_asia=table_cfg.east_asia_font)

    def _add_table_ref(block: TableRefBlock) -> None:
        """渲染数据表引用：坏引用降级为占位段落，正常引用输出说明行 + 表格."""
        spec = parse_table_ref_line(block.raw) if tables is not None else None
        if spec is None or tables is None:
            doc.add_paragraph(block.raw)
            return
        resolved: ResolvedTable = tables(spec)
        if resolved.error:
            doc.add_paragraph(resolved.error)
            return
        caption = doc.add_paragraph()
        run = caption.add_run(resolved.caption)
        run.italic = True
        _apply_run_font(run, body.latin_font, body.size - 1, east_asia=body.east_asia_font)
        _write_plain_table([resolved.header or [], *(resolved.rows or [])], width_percent=spec.width)

    def _add_chart_block(block: InlineChartBlock) -> None:
        """渲染内嵌图表块：坏块降级为占位段落，正常块嵌入整幅图 PNG（D6，2 倍分辨率）."""
        if block.error:
            doc.add_paragraph(block_error_message(block.error))
            return
        try:
            rendered = render_inline_chart(block)
            doc.add_picture(io.BytesIO(to_png(rendered, scale=2)), width=_docx_image_width(doc, block.width))
        except Exception:  # pragma: no cover - Pillow 绘制失败兜底
            doc.add_paragraph(f"[图表无法嵌入：{block.title or '图表'}]")

    def _add_blocks(blocks: list[Block]) -> None:
        nonlocal table_no
        caption_cfg = cfg.captions.table
        # 表格题注：紧邻表格前的「表：说明」段落被提取为题注，不再按正文渲染
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
                _add_paragraph(block)
            elif isinstance(block, ListBlock):
                _add_list(block)
            elif isinstance(block, TableBlock):
                _write_markdown_table(block)
            elif isinstance(block, TableRefBlock):
                _add_table_ref(block)
            elif isinstance(block, CodeBlock):
                _add_code(block)
            elif isinstance(block, QuoteBlock):
                _add_quote(block)
            elif isinstance(block, RuleBlock):
                _add_rule()
            elif isinstance(block, PageBreakBlock):
                doc.add_page_break()
            elif isinstance(block, ImageBlock):
                _add_image(block)
            if table_caption and caption_cfg.position == "below":
                _add_caption("table", caption_cfg, table_no, table_caption)

    for segment in split_inline_chart_segments(markdown_text):
        if isinstance(segment, str):
            _add_blocks(parse_blocks(segment))
            continue
        _add_chart_block(segment)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


__all__ = ["_add_rich_runs", "_docx_image_width", "_render_docx"]
