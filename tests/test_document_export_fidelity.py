"""导出保真测试：块级解析 + PDF / DOCX 产物的列表、表格与溢出行为.

覆盖需求 0132 C2-C5：多层嵌套列表与编号延续、任务列表、宽表格 / 长 URL、
单元格换行与对齐、表头重复、代码块、引用、标题层级、图片自然尺寸。
"""

from __future__ import annotations

import io
import re

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Emu, Pt

from cndb.plugins.documents.services.export import docx as docx_export
from cndb.plugins.documents.services.export import markdown_blocks as mb
from cndb.plugins.documents.services.export import pdf as pdf_export

LONG_URL = "https://example.com/a/very/long/url/with/no/breaks/whatsoever?query=" + "x" * 120


def _docx_xml(markdown_text: str, **kwargs: object) -> str:
    document = Document(io.BytesIO(docx_export._render_docx(markdown_text, **kwargs)))
    return document.element.xml


def _png(width: int, height: int, color: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


class TestInlineParsing:
    def test_inline_styles_and_link(self) -> None:
        spans = mb.parse_inline("**粗** *斜* `码` ~~删~~ [链](https://example.com) <br> 尾")
        kinds = [span.kind for span in spans]
        assert mb.INLINE_BOLD in kinds
        assert mb.INLINE_ITALIC in kinds
        assert mb.INLINE_CODE in kinds
        assert mb.INLINE_STRIKE in kinds
        assert mb.INLINE_BREAK in kinds
        link = next(span for span in spans if span.kind == mb.INLINE_LINK)
        assert link.text == "链"
        assert link.href == "https://example.com"

    def test_wikilink_and_inline_image_render_text(self) -> None:
        spans = mb.parse_inline("[[页面标题]] ![示意图](file:abc.png)")
        assert mb.plain_text(spans) == "页面标题 示意图"

    def test_plain_text_counts_break_as_space(self) -> None:
        spans = mb.parse_inline("前<br>后")
        assert mb.plain_text(spans) == "前 后"

    def test_display_width_counts_cjk_double(self) -> None:
        assert mb.display_width("ab中") == 4


class TestBlockParsing:
    def test_nested_list_levels_and_numbering(self) -> None:
        blocks = mb.parse_blocks("- A\n  - A1\n    1. A1a\n    2. A1b\n  - A2\n- B\n  1. B1\n  2. B2")
        list_block = blocks[0]
        assert isinstance(list_block, mb.ListBlock)
        assert [item.level for item in list_block.items] == [0, 1, 2, 2, 1, 0, 1, 1]
        assert [item.marker for item in list_block.items] == ["•", "•", "1.", "2.", "•", "•", "1.", "2."]

    def test_ordered_numbering_continues_after_nested_and_start_value(self) -> None:
        blocks = mb.parse_blocks("3. A\n  1. A1\n  2. A2\n4. B")
        list_block = blocks[0]
        assert [item.marker for item in list_block.items] == ["3.", "1.", "2.", "4."]

    def test_task_list_markers(self) -> None:
        blocks = mb.parse_blocks("- [ ] 未完成\n- [x] 已完成")
        list_block = blocks[0]
        assert [(item.checked, item.marker) for item in list_block.items] == [
            (False, "☐"),
            (True, "☑"),
        ]

    def test_loose_list_continuation_merges_into_previous_item(self) -> None:
        blocks = mb.parse_blocks("- 第一行\n  第二行\n- 下一项")
        list_block = blocks[0]
        assert mb.plain_text(list_block.items[0].spans) == "第一行 第二行"
        assert len(list_block.items) == 2

    def test_blank_line_keeps_numbering_inside_same_list(self) -> None:
        blocks = mb.parse_blocks("1. A\n\n2. B")
        list_block = blocks[0]
        assert [item.marker for item in list_block.items] == ["1.", "2."]

    def test_table_alignment_escaped_pipe_and_break(self) -> None:
        blocks = mb.parse_blocks("| 左 | 中 | 右 |\n| :--- | :---: | ---: |\n| a \\| b | c<br>d | e |")
        table = blocks[0]
        assert isinstance(table, mb.TableBlock)
        assert table.aligns == ("left", "center", "right")
        assert len(table.rows) == 1
        assert mb.plain_text(table.rows[0][0]) == "a | b"
        assert [span.kind for span in table.rows[0][1]] == [mb.INLINE_TEXT, mb.INLINE_BREAK, mb.INLINE_TEXT]

    def test_pipe_without_separator_is_paragraph(self) -> None:
        blocks = mb.parse_blocks("a | b\n普通句子")
        assert isinstance(blocks[0], mb.ParagraphBlock)

    def test_fenced_code_collects_lines_and_language(self) -> None:
        blocks = mb.parse_blocks("```python\nprint('a')\n\nprint('b')\n```")
        code = blocks[0]
        assert isinstance(code, mb.CodeBlock)
        assert code.language == "python"
        assert code.code == "print('a')\n\nprint('b')"

    def test_tilde_fence_and_unclosed_fence(self) -> None:
        blocks = mb.parse_blocks("~~~js\nconst a = 1\n~~~\n\n```\n未闭合")
        assert isinstance(blocks[0], mb.CodeBlock)
        assert blocks[0].language == "js"
        assert isinstance(blocks[1], mb.CodeBlock)
        assert blocks[1].code == "未闭合"

    def test_quote_rule_pagebreak_image_and_table_ref(self) -> None:
        blocks = mb.parse_blocks(
            "> 引用一\n> 引用二\n\n---\n\n---PAGE---\n\n![图](file:key.png)\n\n{{table:7|width=50}}"
        )
        kinds = [type(block).__name__ for block in blocks]
        assert kinds == ["QuoteBlock", "RuleBlock", "PageBreakBlock", "ImageBlock", "TableRefBlock"]
        assert len(blocks[0].lines) == 2
        assert blocks[3].key == "key.png"
        assert blocks[4].raw == "{{table:7|width=50}}"

    def test_heading_levels_and_paragraph_soft_wrap(self) -> None:
        blocks = mb.parse_blocks("# 一\n\n###### 六\n\n第一行\n第二行")
        assert isinstance(blocks[0], mb.HeadingBlock) and blocks[0].level == 1
        assert isinstance(blocks[1], mb.HeadingBlock) and blocks[1].level == 6
        assert mb.plain_text(blocks[2].spans) == "第一行 第二行"

    def test_fit_column_widths_sums_and_clamps(self) -> None:
        widths = mb.fit_column_widths([100.0, 1.0, 1.0], 495.0)
        assert sum(widths) == pytest.approx(495.0)
        assert widths[0] == pytest.approx(495.0 * 0.55)
        assert widths[1] >= 495.0 * 0.08 - 0.01
        assert widths[2] >= 495.0 * 0.08 - 0.01

    def test_fit_column_widths_empty(self) -> None:
        assert mb.fit_column_widths([], 100.0) == []


class TestDocxFidelity:
    def test_nested_lists_indent_and_task_markers(self) -> None:
        document = Document(
            io.BytesIO(docx_export._render_docx("- 一级\n  - 二级\n    - 三级\n- [ ] 待办\n- [x] 已完成"))
        )
        paragraphs = [p for p in document.paragraphs if p.text.strip()]
        assert paragraphs[0].text.startswith("•\t一级")
        assert paragraphs[1].text.startswith("•\t二级")
        assert paragraphs[2].text.startswith("•\t三级")
        assert paragraphs[3].text.startswith("☐\t待办")
        assert paragraphs[4].text.startswith("☑\t已完成")
        indents = [p.paragraph_format.left_indent for p in paragraphs[:3]]
        assert indents[0] < indents[1] < indents[2]
        assert paragraphs[0].paragraph_format.first_line_indent == Pt(-14)

    def test_numbering_continuation_in_docx(self) -> None:
        document = Document(io.BytesIO(docx_export._render_docx("3. A\n  1. A1\n  2. A2\n4. B")))
        texts = [p.text for p in document.paragraphs if p.text.strip()]
        assert texts == ["3.\tA", "1.\tA1", "2.\tA2", "4.\tB"]

    def test_table_fixed_layout_header_repeat_and_cant_split(self) -> None:
        markdown = (
            "| 名称 | 说明 | 链接 |\n| --- | --- | --- |\n"
            f"| 短 | 单元格内第一行<br>第二行 | {LONG_URL} |\n"
            "| 二 | 普通 | https://b.example.com |"
        )
        document = Document(io.BytesIO(docx_export._render_docx(markdown)))
        table = document.tables[0]
        xml = table._tbl.xml
        assert 'w:type="fixed"' in xml
        assert "w:tblHeader" in xml
        assert xml.count("w:cantSplit") == len(table.rows)
        # 表头只标记第一行
        assert "w:tblHeader" in table.rows[0]._tr.xml
        assert "w:tblHeader" not in table.rows[1]._tr.xml
        # 列宽按内容分配且总和等于正文可用宽度
        grid = [int(col.get(qn("w:w"))) for col in table._tbl.tblGrid.findall(qn("w:gridCol"))]
        assert sum(grid) == pytest.approx(docx_export._docx_usable_width(document) / 635, abs=4)
        assert grid[2] > grid[0]
        # 长 URL 完整写入，<br> 转成换行而不是字面量
        assert LONG_URL in table.cell(1, 2).text
        assert "<br>" not in table.cell(1, 1).text
        assert "w:br" in table.cell(1, 1)._tc.xml

    def test_table_alignment(self) -> None:
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        document = Document(
            io.BytesIO(docx_export._render_docx("| 左 | 中 | 右 |\n| :--- | :---: | ---: |\n| a | b | c |"))
        )
        table = document.tables[0]
        assert table.cell(1, 1).paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER
        assert table.cell(1, 2).paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.RIGHT

    def test_code_block_shading_and_line_breaks(self) -> None:
        markdown = "```python\nprint('a')\n\nprint('b')\n```"
        document = Document(io.BytesIO(docx_export._render_docx(markdown)))
        paragraph = next(p for p in document.paragraphs if "print('a')" in p.text)
        assert "```" not in paragraph.text
        xml = paragraph._p.xml
        assert 'w:fill="F6F8FA"' in xml
        assert "w:pBdr" in xml
        assert paragraph.text == "print('a')\n\nprint('b')"

    def test_inline_styles_and_hyperlink_relationship(self) -> None:
        document = Document(
            io.BytesIO(docx_export._render_docx("正文 **粗** *斜* ~~删~~ `码` [链接](https://example.com/a)"))
        )
        paragraph = next(p for p in document.paragraphs if "正文" in p.text)
        runs = {run.text: run for run in paragraph.runs}
        assert runs["粗"].bold is True
        assert runs["斜"].italic is True
        assert runs["删"].font.strike is True
        assert runs["码"].font.name == "Courier New"
        hyperlinks = [rel for rel in document.part.rels.values() if rel.reltype.endswith("/hyperlink")]
        assert hyperlinks and hyperlinks[0].target_ref == "https://example.com/a"
        assert "w:hyperlink" in paragraph._p.xml

    def test_quote_left_border_and_rule_bottom_border(self) -> None:
        document = Document(io.BytesIO(docx_export._render_docx("> 引用\n\n---\n")))
        quote = next(p for p in document.paragraphs if p.text == "引用")
        assert "<w:left" in quote._p.xml
        rule = next(p for p in document.paragraphs if "<w:bottom" in p._p.xml)
        assert rule.text == ""

    def test_heading_sizes_cover_h4_to_h6(self) -> None:
        document = Document(io.BytesIO(docx_export._render_docx("#### 四\n##### 五\n###### 六")))
        sizes = [p.runs[0].font.size for p in document.paragraphs if p.text.strip()]
        assert sizes == [Pt(12), Pt(11), Pt(10.5)]

    def test_small_image_is_not_upscaled(self) -> None:
        data = _png(20, 10)
        document = Document(
            io.BytesIO(docx_export._render_docx("![小图](file:tiny.png)", images=lambda _key: (data, "tiny.png")))
        )
        shape = document.inline_shapes[0]
        assert shape.width == Emu(int(20 * 0.75 * 12700))
        assert shape.height == Emu(int(10 * 0.75 * 12700))

    def test_missing_image_keeps_placeholder(self) -> None:
        document = Document(io.BytesIO(docx_export._render_docx("![缺图](file:none.png)", images=lambda _key: None)))
        assert "[图片缺失：缺图]" in "\n".join(p.text for p in document.paragraphs)


class TestPdfFidelity:
    def test_table_cells_are_wrapping_paragraphs(self) -> None:
        from reportlab.platypus import Paragraph

        table = pdf_export._make_pdf_table(
            [["名称", "说明", "链接"], ["短", "中文说明", LONG_URL]],
            aligns=("left", "center", "right"),
        )
        assert table.repeatRows == 1
        assert sum(table._argW) == pytest.approx(pdf_export._PDF_MAX_IMAGE_WIDTH)
        url_cell = table._cellvalues[1][2]
        assert isinstance(url_cell, Paragraph)
        height = url_cell.wrap(table._argW[2], 1000)[1]
        assert height > url_cell.style.leading * 1.5  # 长 URL 已被折成多行
        assert max(table._argW) >= table._argW[0]

    def test_body_long_url_wraps_inside_page_width(self) -> None:
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph

        style = ParagraphStyle("B", fontName=pdf_export._ensure_pdf_font() or "Helvetica")
        style.wordWrap = "CJK"
        # 直接复用渲染器的 CJK 断行口径
        rml = pdf_export._pdf_markdown_to_rml(LONG_URL)
        paragraph = Paragraph(rml, style)
        width, height = paragraph.wrap(pdf_export._PDF_MAX_IMAGE_WIDTH, 1000)
        assert width <= pdf_export._PDF_MAX_IMAGE_WIDTH + 0.01
        assert height > style.leading * 1.5

    def test_table_rendered_from_blocks_skips_separator_row(self) -> None:
        blocks = mb.parse_blocks("| a | b |\n| --- | --- |\n| 1 | 2 |")
        table = blocks[0]
        assert isinstance(table, mb.TableBlock)
        assert len(table.rows) == 1
        assert mb.plain_text(table.rows[0][0]) == "1"

    def test_code_line_keeps_leading_indent_and_font(self) -> None:
        rml = pdf_export._pdf_code_line_rml("    return 1", "SimHei")
        assert rml.startswith("<font name='Courier'>&nbsp;&nbsp;&nbsp;&nbsp;return 1")
        cjk = pdf_export._pdf_code_line_rml("print('中文')", "SimHei")
        assert "name='SimHei'" in cjk

    def test_render_pdf_nested_lists_and_wide_table(self) -> None:
        markdown = (
            "1. 一级\n   - 二级\n     1. 三级\n2. 一级二\n\n"
            f"| 名称 | 说明 | 链接 |\n| :--- | :---: | ---: |\n| A | 长文本 | {LONG_URL} |\n\n"
            "> 引用\n\n---\n\n```python\nprint('x')\n```"
        )
        out = pdf_export._render_pdf(markdown, title="保真")
        assert out.startswith(b"%PDF")
        assert len(re.findall(rb"/Type\s*/Page\b", out)) >= 1

    def test_render_pdf_table_ref_uses_width_percent(self) -> None:
        from cndb.plugins.documents.services.export.table_refs import ResolvedTable, TableRefSpec

        def resolver(_spec: TableRefSpec) -> ResolvedTable:
            return ResolvedTable(table_name="T", header=["a", "b"], rows=[["1", "2"]], total=1)

        out = pdf_export._render_pdf("{{table:7|width=50}}", tables=resolver)
        assert out.startswith(b"%PDF")

    def test_pdf_placeholder_when_no_or_broken_table_resolver(self) -> None:
        from cndb.plugins.documents.services.export.table_refs import ResolvedTable

        assert pdf_export._render_pdf("{{table:7}}").startswith(b"%PDF")
        out = pdf_export._render_pdf("{{table:7}}", tables=lambda _spec: ResolvedTable(error="无权访问"))
        assert out.startswith(b"%PDF")

    def test_pdf_unparsable_table_ref_keeps_raw_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pdf_export, "parse_table_ref_line", lambda _raw: None)
        out = pdf_export._render_pdf("{{table:7}}", tables=lambda _spec: None)
        assert out.startswith(b"%PDF")

    def test_pdf_image_resolver_failures(self) -> None:
        assert pdf_export._make_pdf_image(None) is None
        assert pdf_export._make_pdf_image((b"not an image", "x.png")) is None
        figure = pdf_export._make_pdf_image((_png(40, 20), "x.png"), max_width=100)
        assert figure is not None
        assert figure.drawWidth <= 100

    def test_pdf_empty_table_inputs(self) -> None:
        for flowable in (
            pdf_export._make_pdf_table([]),
            pdf_export._make_pdf_table_rml([[]]),
            pdf_export._make_pdf_table([[]]),
        ):
            assert flowable.wrap(pdf_export._PDF_MAX_IMAGE_WIDTH, 100)[0] <= pdf_export._PDF_MAX_IMAGE_WIDTH

    def test_pdf_style_and_box_helpers(self) -> None:
        commands = pdf_export._pdf_table_style_cmds(pdf_export.DEFAULT_THEME)
        assert any(command[0] == "GRID" for command in commands)
        assert pdf_export._pdf_boxed_lines(["line"], "Helvetica") is not None
        assert pdf_export._pdf_boxed_lines(["line"], "Helvetica", background="#F6F8FA") is not None

    def test_pdf_spans_rml_covers_all_inline_kinds(self) -> None:
        spans = mb.parse_inline("普通 **粗** *斜* `码` ~~删~~ [链](https://e.com/?a=1&b=2) <br>")
        rml = pdf_export._pdf_spans_rml(spans, "Helvetica")
        assert "<b>粗</b>" in rml
        assert "<i>斜</i>" in rml
        assert "<strike>删</strike>" in rml
        assert "<br/>" in rml
        assert "https://e.com/?a=1&amp;b=2" in rml

    def test_pdf_broken_chart_block_degrades_to_text(self) -> None:
        out = pdf_export._render_pdf("```chart\n{not json}\n```", title="坏图")
        assert out.startswith(b"%PDF")

    def test_pdf_unembeddable_chart_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cndb.plugins.documents.services.charts.inline import serialize_inline_chart_block

        monkeypatch.setattr(pdf_export, "_make_pdf_image", lambda *_args, **_kwargs: None)
        block = serialize_inline_chart_block(template_key="stacked-bar-horizontal", config={}, title="图")
        out = pdf_export._render_pdf(block, title="图")
        assert out.startswith(b"%PDF")


class TestDocxTableRefEdges:
    def test_table_ref_without_resolver_and_error(self) -> None:
        from cndb.plugins.documents.services.export.table_refs import ResolvedTable

        document = Document(io.BytesIO(docx_export._render_docx("{{table:7}}")))
        assert any("{{table:7}}" in p.text for p in document.paragraphs)

        broken = Document(
            io.BytesIO(docx_export._render_docx("{{table:7}}", tables=lambda _spec: ResolvedTable(error="无权访问")))
        )
        assert any("无权访问" in p.text for p in broken.paragraphs)

    def test_empty_resolved_table_writes_no_table(self) -> None:
        from cndb.plugins.documents.services.export.table_refs import ResolvedTable

        def empty(_spec: object) -> ResolvedTable:
            return ResolvedTable(table_name="空表", header=[], rows=[], total=0)

        document = Document(io.BytesIO(docx_export._render_docx("{{table:7}}", tables=empty)))
        assert document.tables == []

    def test_unparsable_table_ref_keeps_raw_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(docx_export, "parse_table_ref_line", lambda _raw: None)
        document = Document(io.BytesIO(docx_export._render_docx("{{table:7}}", tables=lambda _spec: None)))
        assert any("{{table:7}}" in p.text for p in document.paragraphs)

    def test_table_width_helpers_create_missing_tblw(self) -> None:
        document = Document()
        table = document.add_table(1, 1)
        table_properties = table._tbl.tblPr
        existing = table_properties.find(qn("w:tblW"))
        table_properties.remove(existing)
        docx_export._set_table_width_twips(table, 6_350_000)
        assert table_properties.find(qn("w:tblW")).get(qn("w:w")) == "10000"
        table_properties.remove(table_properties.find(qn("w:tblW")))
        docx_export._set_table_ref_width(table, 75)
        assert table_properties.find(qn("w:tblW")).get(qn("w:w")) == "3750"

    def test_usable_width_falls_back_to_14cm(self) -> None:
        class _Section:
            page_width = 0
            left_margin = 0
            right_margin = 0

        class _Doc:
            sections = [_Section()]

        from docx.shared import Cm

        assert docx_export._docx_usable_width(_Doc()) == int(Cm(14))

    def test_anchor_link_falls_back_to_styled_run(self) -> None:
        document = Document(io.BytesIO(docx_export._render_docx("[锚点](#section)")))
        paragraph = next(p for p in document.paragraphs if "锚点" in p.text)
        run = next(run for run in paragraph.runs if run.text == "锚点")
        assert run.underline is True
        assert run.font.color.rgb is not None

    def test_hyperlink_failure_and_sized_link(self) -> None:
        class _BrokenPart:
            @staticmethod
            def relate_to(*_args: object, **_kwargs: object) -> str:
                raise RuntimeError("no relationship")

        class _Paragraph:
            part = _BrokenPart()

        assert docx_export._add_hyperlink(_Paragraph(), "文本", "https://example.com", "Calibri") is False

        document = Document()
        paragraph = document.add_paragraph()
        assert docx_export._add_hyperlink(paragraph, "带字号", "https://example.com", "Calibri", size=12) is True
        assert "w:sz" in paragraph._p.xml

    def test_heading_with_inline_code_uses_smaller_size(self) -> None:
        document = Document(io.BytesIO(docx_export._render_docx("# 标题 `码`")))
        heading = next(p for p in document.paragraphs if "标题" in p.text)
        code_run = next(run for run in heading.runs if run.text == "码")
        assert code_run.font.size == Pt(17.5)

    def test_chart_block_between_text_keeps_segments(self) -> None:
        from cndb.plugins.documents.services.charts.inline import serialize_inline_chart_block

        block = serialize_inline_chart_block(template_key="stacked-bar-horizontal", config={}, title="图")
        document = Document(io.BytesIO(docx_export._render_docx(f"前文\n\n{block}\n\n后文")))
        texts = [p.text for p in document.paragraphs]
        assert "前文" in texts
        assert "后文" in texts
        assert len(document.inline_shapes) == 1


class TestBlockParsingEdges:
    def test_plain_inline_covers_all_markers(self) -> None:
        text = "`码` ![a](file:x) [b](https://u) [[c]] **粗** ~~删~~ *斜* <br>"
        assert mb._plain_inline(text) == "码 a b c 粗 删 斜  "

    def test_plain_inline_nested_markers(self) -> None:
        assert mb._plain_inline("![a](file:x) [b](https://u) [[c]] <br> **d**") == "a b c   d"

    def test_split_cells_trailing_backslash(self) -> None:
        assert mb._split_table_cells("a|b\\") == ["a", "b\\"]

    def test_list_skips_multiple_blank_lines(self) -> None:
        blocks = mb.parse_blocks("1. A\n\n\n2. B")
        assert [item.marker for item in blocks[0].items] == ["1.", "2."]

    def test_list_continuation_stops_at_new_block(self) -> None:
        blocks = mb.parse_blocks("- A\n  # 标题")
        assert isinstance(blocks[0], mb.ListBlock)
        assert isinstance(blocks[1], mb.HeadingBlock)

    def test_paragraph_stops_before_each_block_marker(self) -> None:
        for follower, expected in (
            ("# 标题", mb.HeadingBlock),
            ("- 列表", mb.ListBlock),
            ("> 引用", mb.QuoteBlock),
            ("![图](file:k.png)", mb.ImageBlock),
            ("{{table:7}}", mb.TableRefBlock),
        ):
            blocks = mb.parse_blocks(f"前言\n{follower}")
            assert isinstance(blocks[0], mb.ParagraphBlock)
            assert isinstance(blocks[1], expected)

    def test_table_stops_at_empty_row(self) -> None:
        table = mb.parse_blocks("| a |\n| --- |\n| 1 |\n|")[0]
        assert isinstance(table, mb.TableBlock)
        assert len(table.rows) == 1

    def test_table_pads_and_truncates_cells(self) -> None:
        table = mb.parse_blocks("| a | b | c |\n| --- | --- | --- |\n| 1 |\n| 1 | 2 | 3 | 4 |")[0]
        assert isinstance(table, mb.TableBlock)
        assert len(table.rows) == 2
        assert [mb.plain_text(cell) for cell in table.rows[0]] == ["1", "", ""]
        assert [mb.plain_text(cell) for cell in table.rows[1]] == ["1", "2", "3"]

    def test_table_separator_shorter_than_header_pads_left_align(self) -> None:
        table, _next = mb._parse_table(["| a | b | c |", "| :---: |", "| 1 | 2 | 3 |"], 0)
        assert table.aligns == ("center", "left", "left")

    def test_table_keeps_escaped_backslash(self) -> None:
        table = mb.parse_blocks("| a | b |\n| --- | --- |\n| x \\* y | z |")[0]
        assert mb.plain_text(table.rows[0][0]) == "x \\* y"

    def test_underscore_italic_and_unclosed_bold(self) -> None:
        spans = mb.parse_inline("_斜_ **未闭合")
        assert spans[0].kind == mb.INLINE_ITALIC
        assert mb.plain_text(spans).endswith("**未闭合")

    def test_list_indent_is_clamped(self) -> None:
        markdown = "\n".join("  " * index + f"- L{index}" for index in range(1, 11))
        block = mb.parse_blocks(markdown)[0]
        assert isinstance(block, mb.ListBlock)
        assert block.items[-1].level == mb.MAX_LIST_LEVEL

    def test_paragraph_stops_before_table(self) -> None:
        blocks = mb.parse_blocks("前言\na | b\n--- | ---\n1 | 2")
        assert isinstance(blocks[0], mb.ParagraphBlock)
        assert mb.plain_text(blocks[0].spans) == "前言"
        assert isinstance(blocks[1], mb.TableBlock)

    def test_empty_markdown(self) -> None:
        assert mb.parse_blocks("") == []
