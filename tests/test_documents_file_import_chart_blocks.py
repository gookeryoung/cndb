"""Markdown 导入图表块测试（ADR 0052 D7 / P2）.

覆盖：正文定义块原样保留、导出时追加的配对静态图被剥离、指纹不匹配的图片保留、
坏块 / 未知模板给出导入告警但不阻断整篇。
"""

from __future__ import annotations

from cndb.plugins.documents.services.charts.inline import (
    MAX_BLOCKS_PER_DOC,
    parse_inline_chart_block,
    serialize_inline_chart_block,
)
from cndb.plugins.documents.services.importers import markdown as markdown_converter

TEMPLATE = "stacked-bar-horizontal"


def _block(title: str = "市场规模", template: str = TEMPLATE) -> str:
    return serialize_inline_chart_block(template_key=template, config={}, width=60, title=title)


def _paired(rel: str, alt: str = "市场规模") -> str:
    return f"\n\n![{alt}]({rel})"


class TestChartBlocksPreserved:
    def test_block_kept_verbatim(self):
        block = _block()
        _title, body, warnings = markdown_converter.convert_markdown(f"# 报表\n\n{block}\n\n正文\n".encode(), "a.md")
        assert block in body
        assert warnings == ["标题取自正文首个一级标题，已从正文剥离"]

    def test_paired_image_stripped(self):
        block = _block()
        parsed = parse_inline_chart_block(block)
        assert parsed is not None
        text = f"# 报表\n\n{block}{_paired(f'assets/chart-{parsed.fingerprint}.svg')}\n\n正文\n"
        _title, body, warnings = markdown_converter.convert_markdown(text.encode("utf-8"), "a.md")
        assert "assets/chart-" not in body
        assert block in body
        assert not any("图表定义无效" in w for w in warnings)

    def test_mismatched_fingerprint_image_kept(self):
        block = _block()
        text = f"# 报表\n\n{block}{_paired('assets/chart-000000000000.svg')}\n\n正文\n"
        _title, body, _warnings = markdown_converter.convert_markdown(text.encode("utf-8"), "a.md")
        assert "assets/chart-000000000000.svg" in body

    def test_user_uploaded_chart_named_image_kept(self):
        """无定义块的 ``assets/chart-*.svg`` 是普通图片，不剥离."""
        text = "# 报表\n\n![自有图](assets/chart-abc123.svg)\n"
        _title, body, _warnings = markdown_converter.convert_markdown(text.encode("utf-8"), "a.md")
        assert "assets/chart-abc123.svg" in body


class TestImportWarnings:
    def test_broken_block_warns_but_keeps_text(self):
        broken = "```chart\n{bad json}\n```"
        _title, body, warnings = markdown_converter.convert_markdown(f"# 报表\n\n{broken}\n\n正文\n".encode(), "a.md")
        assert broken in body
        assert any("图表定义无效" in w for w in warnings)

    def test_unknown_template_warns(self):
        block = _block(template="retired-template")
        _title, body, warnings = markdown_converter.convert_markdown(f"# 报表\n\n{block}\n".encode(), "a.md")
        assert block in body
        assert any("模板不存在或已下线" in w for w in warnings)

    def test_too_many_blocks_warns(self):
        blocks = "\n\n".join(_block(title=f"图{i}") for i in range(MAX_BLOCKS_PER_DOC + 1))
        _title, body, warnings = markdown_converter.convert_markdown(f"# 报表\n\n{blocks}\n".encode(), "a.md")
        assert body.count("```chart") == MAX_BLOCKS_PER_DOC + 1
        assert any("上限" in w for w in warnings)
