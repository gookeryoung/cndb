"""标题 / 题注序号单一权威（ADR 0186 / H72）.

判定层：``export/numbering.py`` 的纯函数；
渲染层：docx / pdf 在正文自带序号时让模板编号失效（不叠加、不报错）。
"""

from __future__ import annotations

import io

import pytest

from cndb.plugins.documents.services.export.markdown_blocks import parse_blocks
from cndb.plugins.documents.services.export.numbering import (
    EXPLICIT_CAPTION_PREFIX_RE,
    EXPLICIT_HEADING_PREFIX_RE,
    has_explicit_caption_number,
    has_explicit_heading_numbers,
    resolve_heading_numbering,
)
from cndb.plugins.documents.services.export.templates import (
    BUILTIN_TEMPLATES,
    DEFAULT_TEMPLATE_KEY,
    ExportTemplateConfig,
    NumberingConfig,
    ResolvedTemplate,
)


def _resolved(config: ExportTemplateConfig) -> ResolvedTemplate:
    return ResolvedTemplate(ref="test", name="测试", source="custom", config=config)


def _docx(markdown: str, config: ExportTemplateConfig):
    from docx import Document

    from cndb.plugins.documents.services.export.docx import _render_docx

    data = _render_docx(markdown, template=_resolved(config))
    return Document(io.BytesIO(data))


def _docx_texts(markdown: str, config: ExportTemplateConfig) -> list[str]:
    return [p.text for p in _docx(markdown, config).paragraphs if p.text.strip()]


def _numbering_config(mode: str, heading: str = "arabic_multilevel") -> ExportTemplateConfig:
    config = BUILTIN_TEMPLATES[DEFAULT_TEMPLATE_KEY].config.model_copy(deep=True)
    config.numbering = NumberingConfig(heading=heading, mode=mode)
    return config


class TestHeadingDetection:
    @pytest.mark.parametrize(
        "text",
        [
            "第一章 概述",
            "第一章节",  # 宽松：认「第一章」即为显式
            "第 1 节 背景",
            "一、项目基本信息",
            "十二. 附则",
            "（一）总体目标",
            "(二)具体目标",
            "3.1 总体目标",
            "1.1. 范围",
            "1. 概述",
            "1、概述",
            "1) 概述",
        ],
    )
    def test_detects_explicit_prefix(self, text: str):
        assert EXPLICIT_HEADING_PREFIX_RE.match(text) is not None
        assert has_explicit_heading_numbers(parse_blocks(f"## {text}\n")) is True

    @pytest.mark.parametrize("text", ["项目基本信息", "研究目标与研究内容", "2026 年度计划", "附录 A 说明"])
    def test_plain_heading_not_detected(self, text: str):
        assert EXPLICIT_HEADING_PREFIX_RE.match(text) is None
        assert has_explicit_heading_numbers(parse_blocks(f"## {text}\n")) is False

    def test_list_and_code_blocks_do_not_count(self):
        markdown = "## 项目基本信息\n\n1. 第一条\n2. 第二条\n\n```\n# 一、代码里的示例标题\n```\n"
        assert has_explicit_heading_numbers(parse_blocks(markdown)) is False

    def test_any_level_triggers_whole_document(self):
        markdown = "## 项目基本信息\n\n### 3.1 总体目标\n"
        assert has_explicit_heading_numbers(parse_blocks(markdown)) is True

    def test_empty_document(self):
        assert has_explicit_heading_numbers([]) is False


class TestCaptionDetection:
    @pytest.mark.parametrize("text", ["图 1 系统架构", "图 1-1 系统架构", "表 2 指标", "图2-1-1 示意图"])
    def test_detects_explicit_caption(self, text: str):
        assert has_explicit_caption_number(text) is True

    @pytest.mark.parametrize("text", ["系统架构", "图表设计说明", "表格结构"])
    def test_plain_caption_not_detected(self, text: str):
        assert has_explicit_caption_number(text) is False

    def test_regex_matches_helper(self):
        assert EXPLICIT_CAPTION_PREFIX_RE.match("图 3 说明") is not None


class TestResolveNumbering:
    def test_off_never_numbers(self):
        assert resolve_heading_numbering("off", "arabic_multilevel", parse_blocks("## 背景\n")) == "none"

    def test_force_always_uses_scheme(self):
        blocks = parse_blocks("## 一、背景\n")
        assert resolve_heading_numbering("force", "arabic_multilevel", blocks) == "arabic_multilevel"

    def test_auto_yields_when_explicit(self):
        blocks = parse_blocks("## 一、背景\n")
        assert resolve_heading_numbering("auto", "arabic_multilevel", blocks) == "none"

    def test_auto_uses_scheme_when_clean(self):
        blocks = parse_blocks("## 背景\n")
        assert resolve_heading_numbering("auto", "arabic_multilevel", blocks) == "arabic_multilevel"

    def test_unknown_mode_falls_back_to_auto(self):
        assert resolve_heading_numbering("weird", "arabic_multilevel", parse_blocks("## 一、背景\n")) == "none"


class TestConfigDefault:
    def test_mode_defaults_to_auto(self):
        config = ExportTemplateConfig.model_validate({"numbering": {"heading": "arabic_multilevel"}})
        assert config.numbering.mode == "auto"

    def test_mode_roundtrip(self):
        config = ExportTemplateConfig.model_validate({"numbering": {"heading": "none", "mode": "force"}})
        assert config.numbering.mode == "force"

    def test_mode_rejects_unknown(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ExportTemplateConfig.model_validate({"numbering": {"heading": "none", "mode": "always"}})

    def test_builtin_presets_all_auto(self):
        for template in BUILTIN_TEMPLATES.values():
            assert template.config.numbering.mode == "auto", template.key


class TestDocxRendering:
    def test_auto_yields_for_handwritten_numbers(self):
        texts = _docx_texts("## 一、项目基本信息\n\n### 3.1 总体目标\n", _numbering_config("auto"))
        headings = [text for text in texts if "项目基本信息" in text or "总体目标" in text]
        assert headings[0].count("一") == 1
        assert not headings[0].startswith("1.")
        assert headings[1].strip().startswith("3.1")

    def test_auto_numbers_clean_body(self):
        texts = _docx_texts("## 项目基本信息\n\n### 总体目标\n", _numbering_config("auto"))
        assert texts[0].startswith("1 ")
        assert texts[1].startswith("1.1 ")

    def test_force_reproduces_old_behaviour(self):
        texts = _docx_texts("## 一、项目基本信息\n", _numbering_config("force"))
        assert texts[0].startswith("1 ") and "一、项目基本信息" in texts[0]

    def test_off_never_numbers(self):
        texts = _docx_texts("## 项目基本信息\n", _numbering_config("off"))
        assert texts[0] == "项目基本信息"

    def test_caption_is_not_doubled(self):
        config = _numbering_config("auto")
        config.captions.table.enabled = True
        markdown = "表：示例数据\n\n| 名称 | 数量 |\n| --- | ---: |\n| A | 1 |\n"
        texts = _docx_texts(markdown, config)
        assert any(text.startswith("表 1") for text in texts)
        assert not any(text.startswith("表 1 表 1") for text in texts)

    def test_caption_with_explicit_number_kept_as_is(self):
        config = _numbering_config("auto")
        config.captions.table.enabled = True
        markdown = "表 2-1 指标\n\n| 名称 | 数量 |\n| --- | ---: |\n| A | 1 |\n"
        texts = _docx_texts(markdown, config)
        assert not any(text.startswith("表 1 表 2-1") for text in texts)


class TestPdfRendering:
    def _pdf_paragraphs(self, markdown: str, config: ExportTemplateConfig) -> list[str]:
        from pypdf import PdfReader

        from cndb.plugins.documents.services.export.pdf import _render_pdf

        data = _render_pdf(markdown, template=_resolved(config))
        reader = PdfReader(io.BytesIO(data))
        return [page.extract_text() or "" for page in reader.pages]

    def test_auto_yields_for_handwritten_numbers(self):
        pages = self._pdf_paragraphs("## 一、项目基本信息\n", _numbering_config("auto"))
        joined = "\n".join(pages)
        assert "项目基本信息" in joined
        assert "一、一、" not in joined
        assert "1 一、项目基本信息" not in joined

    def test_auto_numbers_clean_body(self):
        pages = self._pdf_paragraphs("## 项目基本信息\n", _numbering_config("auto"))
        assert any(text.startswith("1 ") for text in "".join(pages).split("\n") if text.strip())

    def test_off_never_numbers(self):
        pages = self._pdf_paragraphs("## 项目基本信息\n", _numbering_config("off"))
        joined = "\n".join(pages)
        assert "1 项目基本信息" not in joined
