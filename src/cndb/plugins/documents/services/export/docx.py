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
from cndb.plugins.documents.services.export.theme import DEFAULT_THEME

logger = logging.getLogger(__name__)

#: H4-H6 字号（预览不再放大，旧实现统一折叠到 H3）
_HEADING_SIZES: tuple[float, ...] = (18.0, 15.0, 13.0, 12.0, 11.0, 10.5)
_LINK_COLOR = "1A6FB5"
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


def _apply_run_font(run: Any, font: str, size: float | None = None, color: str | None = None) -> None:
    """给 run 设置字体名（含东亚映射）、字号、颜色."""
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    run.font.name = font
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), font)
    if size is not None:
        run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = RGBColor.from_string(color.lstrip("#"))


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
        font = code_font if span.kind == INLINE_CODE else body_font
        _apply_run_font(run, font, size, color)
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


def _render_docx(
    markdown_text: str,
    title: str = "",
    images: ImageResolver | None = None,
    tables: TableResolver | None = None,
) -> bytes:
    # images：站内图片解析器；``![alt](file:<key>)`` 独占一行时嵌入真实图片，
    # 解析失败写占位文字，避免导出物静默丢图
    # tables：数据表引用解析器；``{{table:…}}`` 独占一行时渲染为真实表格
    # 图表：正文 `` ```chart `` 内嵌块渲染为整幅图 PNG（ADR 0052，2 倍分辨率）
    """把文档 Markdown 正文渲染为 .docx 字节流.

    支持标题 / 列表 / 引用 / 代码块 / GFM 表格 / 图表块 / ``---PAGE---`` 换页，
    并按默认导出预设应用字体、字号与表头配色。
    """
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Emu, Pt
    from docx.styles.style import ParagraphStyle as DocxParagraphStyle

    preset = DEFAULT_THEME
    doc = Document()
    if title:
        doc.core_properties.title = title

    # 全局正文样式（Normal）应用主题正文字体/字号，含中文东亚字体映射
    normal = cast(DocxParagraphStyle, doc.styles["Normal"])
    normal.font.name = preset.body_font
    normal.font.size = Pt(preset.body_size)
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), preset.body_font)

    align_map = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
    }

    def _add_heading(block: HeadingBlock) -> None:
        level = min(max(block.level, 1), 6)
        size = _HEADING_SIZES[level - 1]
        color = preset.heading_colors[level - 1] if level <= 3 else "#000000"
        try:
            paragraph = doc.add_heading("", level=level)
        except (KeyError, ValueError):  # pragma: no cover - 某些 Word 模板缺少 Heading 5+
            paragraph = doc.add_paragraph()
            _add_inline_runs(
                paragraph, block.spans, preset.heading_font, preset.code_font, size=size, color=color, bold=True
            )
            return
        _add_inline_runs(paragraph, block.spans, preset.heading_font, preset.code_font, size=size, color=color)

    def _add_paragraph(block: ParagraphBlock) -> None:
        paragraph = doc.add_paragraph()
        _add_inline_runs(paragraph, block.spans, preset.body_font, preset.code_font)

    def _add_list(block: ListBlock) -> None:
        for item in block.items:
            paragraph = doc.add_paragraph()
            formatting = paragraph.paragraph_format
            left = Pt(16 * (item.level + 1))
            formatting.left_indent = left
            formatting.first_line_indent = Pt(-14)
            formatting.space_before = Pt(0)
            formatting.space_after = Pt(2)
            formatting.tab_stops.add_tab_stop(left)
            marker = paragraph.add_run(f"{item.marker}\t")
            _apply_run_font(marker, preset.body_font, preset.body_size)
            _add_inline_runs(paragraph, item.spans, preset.body_font, preset.code_font)

    def _add_code(block: CodeBlock) -> None:
        paragraph = doc.add_paragraph()
        formatting = paragraph.paragraph_format
        formatting.left_indent = Pt(6)
        formatting.right_indent = Pt(6)
        formatting.space_before = Pt(4)
        formatting.space_after = Pt(8)
        formatting.line_spacing = 1.0
        _border_paragraph(paragraph, ("top", "left", "bottom", "right"), _CODE_BORDER)
        _shade_paragraph(paragraph, _CODE_BG)
        for index, line in enumerate(block.code.split("\n")):
            if index:
                paragraph.add_run().add_break()
            run = paragraph.add_run(line or (" " if not block.code else ""))
            _apply_run_font(run, preset.code_font, 9)

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
                preset.body_font,
                preset.code_font,
                color="#555555",
                italic=True,
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
        resolved = images(block.key) if images is not None else None
        if resolved is None:
            doc.add_paragraph(f"[图片缺失：{block.alt}]")
            return
        _add_picture(resolved[0], block.alt)

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
        _mark_header_row(table.rows[0])
        return table

    def _format_cell(cell: Any, align: str) -> Any:
        paragraph = cell.paragraphs[0]
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing = 1.15
        paragraph.alignment = align_map.get(align, WD_ALIGN_PARAGRAPH.LEFT)
        return paragraph

    def _shade_cell(cell: Any, fill: str) -> None:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        shaded = OxmlElement("w:shd")
        shaded.set(qn("w:val"), "clear")
        shaded.set(qn("w:color"), "auto")
        shaded.set(qn("w:fill"), fill.lstrip("#"))
        cell._tc.get_or_add_tcPr().append(shaded)

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
                    _shade_cell(cell, preset.table_header_bg)
                    _add_inline_runs(
                        paragraph,
                        spans,
                        preset.body_font,
                        preset.code_font,
                        color=preset.table_header_color,
                        bold=True,
                    )
                else:
                    _add_inline_runs(paragraph, spans, preset.body_font, preset.code_font)

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
                    run.bold = True
                    _shade_cell(cell, preset.table_header_bg)
                    _apply_run_font(run, preset.body_font, color=preset.table_header_color)
                else:
                    _apply_run_font(run, preset.body_font)

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
        _apply_run_font(run, preset.body_font, preset.body_size - 1)
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
        for block in blocks:
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
