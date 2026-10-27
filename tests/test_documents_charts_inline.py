"""正文内嵌图表块判定层测试（ADR 0052 I1–I5 / P0）.

覆盖：围栏识别与段落独占、JSON 往返、字段默认与非法回退、版本 / 模板 / 体积 /
数量上限、指纹稳定性、坏块错误码与降级、Markdown 导出改写与旧引用迁移。
"""

from __future__ import annotations

import json

import pytest

from cndb.plugins.documents.services import charts
from cndb.plugins.documents.services.charts.inline import (
    ERROR_CONFIG_INVALID,
    ERROR_JSON_INVALID,
    ERROR_TEMPLATE_MISSING,
    ERROR_TOO_LARGE,
    ERROR_VERSION_UNSUPPORTED,
    INLINE_CHART_VERSION,
    MAX_BLOCK_BYTES,
    MAX_BLOCKS_PER_DOC,
    block_error_message,
    chart_fingerprint,
    iter_inline_chart_blocks,
    migrate_legacy_chart_refs,
    parse_inline_chart_block,
    render_inline_chart,
    render_inline_chart_svg,
    rewrite_markdown_chart_blocks,
    serialize_inline_chart_block,
    split_inline_chart_segments,
    validate_document_blocks,
)

TEMPLATE = "stacked-bar-horizontal"


def _block(**overrides) -> str:
    payload = {
        "version": 1,
        "template": TEMPLATE,
        "title": "市场规模",
        "width": 60,
        "config": {},
    }
    payload.update(overrides)
    return "```chart\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


class TestParse:
    @pytest.mark.parametrize("fence", ["```", "````"])
    def test_fence_length_3_or_more(self, fence):
        source = f"{fence}chart\n" + json.dumps({"version": 1, "template": TEMPLATE, "config": {}}) + f"\n{fence}"
        block = parse_inline_chart_block(source)
        assert block is not None
        assert block.error is None
        assert block.template_key == TEMPLATE

    def test_defaults(self):
        block = parse_inline_chart_block(_block())
        assert block is not None
        assert block.title == "市场规模"
        assert block.width == 60
        assert block.version == INLINE_CHART_VERSION
        assert block.fingerprint

    @pytest.mark.parametrize("raw,expected", [("120", 75), ("20", 75), ("abc", 75), (None, 75), (33, 33)])
    def test_width_fallback(self, raw, expected):
        block = parse_inline_chart_block(_block(width=raw))
        assert block is not None
        assert block.width == expected

    def test_inline_mixed_not_parsed(self):
        content = f"前文 ```chart\n{json.dumps({'version': 1, 'template': TEMPLATE, 'config': {}})}\n``` 后文"
        assert parse_inline_chart_block(content) is None
        assert list(iter_inline_chart_blocks(content)) == []

    def test_unclosed_fence_not_parsed(self):
        assert parse_inline_chart_block(f"```chart\n{json.dumps({'template': TEMPLATE})}") is None

    def test_plain_code_block_not_parsed(self):
        assert parse_inline_chart_block("```json\n{}\n```") is None

    def test_paragraph_split_segments(self):
        content = "标题\n\n" + _block() + "\n\n正文\n"
        segments = split_inline_chart_segments(content)
        assert isinstance(segments[0], str) and "标题" in segments[0]
        assert not isinstance(segments[1], str)
        assert "正文" in segments[-1]


class TestErrors:
    @pytest.mark.parametrize(
        "source,code",
        [
            ("```chart\n{bad json}\n```", ERROR_JSON_INVALID),
            ("```chart\n[]\n```", ERROR_JSON_INVALID),
            (_block(version=2), ERROR_VERSION_UNSUPPORTED),
            (_block(template="removed-template"), ERROR_TEMPLATE_MISSING),
            (_block(template=""), ERROR_TEMPLATE_MISSING),
            (_block(config="bad"), ERROR_CONFIG_INVALID),
        ],
    )
    def test_error_codes(self, source, code):
        block = parse_inline_chart_block(source)
        assert block is not None
        assert block.error == code
        assert block_error_message(code) in block_error_message(block.error)

    def test_too_large(self):
        source = _block(config={"x": "a" * MAX_BLOCK_BYTES})
        block = parse_inline_chart_block(source)
        assert block is not None
        assert block.error == ERROR_TOO_LARGE

    def test_bad_block_degrades_to_svg(self):
        block = parse_inline_chart_block("```chart\n{bad}\n```")
        assert block is not None
        svg = render_inline_chart_svg(block)
        assert svg.startswith("<svg")

    def test_offline_template_degrades(self, monkeypatch):
        block = parse_inline_chart_block(_block())
        assert block is not None

        def _raise(*_args, **_kwargs):
            raise charts.BadRequestTemplateError("下线")

        monkeypatch.setattr(charts, "get_template", lambda _key: object())
        monkeypatch.setattr(charts, "render_chart", _raise)
        svg = render_inline_chart_svg(block)
        assert svg.startswith("<svg")
        assert "模板不存在或已下线" in svg


class TestSerializeAndFingerprint:
    def test_roundtrip(self):
        source = serialize_inline_chart_block(
            template_key=TEMPLATE, config={"data": {"rows": []}}, width=80, title="标题"
        )
        block = parse_inline_chart_block(source)
        assert block is not None and block.error is None
        assert block.width == 80
        assert block.title == "标题"
        assert block.config == {"data": {"rows": []}}

    def test_fingerprint_stable_across_key_order(self):
        left = chart_fingerprint(TEMPLATE, {"a": 1, "b": 2}, 75, "t")
        right = chart_fingerprint(TEMPLATE, {"b": 2, "a": 1}, 75, "t")
        assert left == right
        assert left != chart_fingerprint(TEMPLATE, {"a": 1}, 75, "t")
        assert left != chart_fingerprint(TEMPLATE, {"a": 1, "b": 2}, 50, "t")

    def test_legacy_id_not_in_fingerprint(self):
        source = serialize_inline_chart_block(template_key=TEMPLATE, config={}, legacy_id=7)
        block = parse_inline_chart_block(source)
        assert block is not None and block.legacy_id == 7
        assert block.fingerprint == chart_fingerprint(TEMPLATE, {}, 75, "")

    def test_unknown_top_level_keys_preserved(self):
        source = _block(note="手写字段")
        block = parse_inline_chart_block(source)
        assert block is not None
        assert block.extra == {"note": "手写字段"}
        again = serialize_inline_chart_block(
            template_key=block.template_key,
            config=block.config,
            width=block.width,
            title=block.title,
            extra=block.extra,
        )
        assert "手写字段" in again


class TestLimits:
    def test_document_warning_for_bad_block(self):
        warnings = validate_document_blocks("正文\n\n```chart\n{bad}\n```")
        assert warnings

    def test_block_count_limit(self):
        content = "\n\n".join(_block(title=f"图{i}") for i in range(MAX_BLOCKS_PER_DOC + 1))
        warnings = validate_document_blocks(content)
        assert any("上限" in w for w in warnings)

    def test_valid_document_has_no_warnings(self):
        assert validate_document_blocks(f"正文\n\n{_block()}") == []


class TestRender:
    def test_render_inline_matches_render_chart(self):
        block = parse_inline_chart_block(_block())
        assert block is not None
        inline = render_inline_chart(block)
        direct = charts.render_chart(TEMPLATE, {})
        assert charts.to_svg(inline) == charts.to_svg(direct)

    def test_svg_escapes_title(self):
        block = parse_inline_chart_block(_block(title="<script>"))
        assert block is not None
        svg = render_inline_chart_svg(block)
        assert "<script>" not in svg


class TestMarkdownRewrite:
    def test_block_preserved_and_asset_appended(self):
        content = f"# 报表\n\n{_block()}\n\n正文\n"
        rewritten, assets = rewrite_markdown_chart_blocks(content)
        block = parse_inline_chart_block(_block())
        assert block is not None
        rel = f"assets/chart-{block.fingerprint}.svg"
        assert _block() in rewritten
        assert f"![市场规模]({rel})" in rewritten
        assert list(assets) == [rel]
        assert assets[rel].startswith(b"<svg")

    def test_duplicate_definition_single_asset(self):
        content = f"{_block()}\n\n{_block()}"
        rewritten, assets = rewrite_markdown_chart_blocks(content)
        assert len(assets) == 1
        assert rewritten.count("```chart") == 2

    def test_title_participates_in_fingerprint(self):
        """标题不同 → 指纹不同（alt 文案与缓存键随定义变化）."""
        first = parse_inline_chart_block(_block())
        second = parse_inline_chart_block(_block(title="另一标题"))
        assert first is not None and second is not None
        assert first.fingerprint != second.fingerprint

    def test_broken_block_kept_without_asset(self):
        content = "前文\n\n```chart\n{bad}\n```\n\n后文"
        rewritten, assets = rewrite_markdown_chart_blocks(content)
        assert rewritten == content
        assert assets == {}

    def test_empty_content(self):
        assert rewrite_markdown_chart_blocks("") == ("", {})


class TestLegacyMigration:
    def test_expand_reference(self):
        content = "前文\n\n{{chart:7|width=50}}\n\n后文"
        new, changed = migrate_legacy_chart_refs(content, lambda cid, width: (1, "旧图", TEMPLATE, {"a": 1}))
        assert changed == 1
        segments = split_inline_chart_segments(new)
        block = segments[1]
        assert block is not None and not isinstance(block, str)
        assert block.legacy_id == 7
        assert block.width == 50
        assert block.title == "旧图"

    def test_missing_reference_degrades(self):
        new, changed = migrate_legacy_chart_refs("{{chart:99}}", lambda *_args: None)
        assert changed == 1
        assert "图表引用无效" in new
        assert "99" in new

    def test_no_legacy_reference_untouched(self):
        content = "普通正文\n\n{{table:1}}"
        assert migrate_legacy_chart_refs(content, lambda *_args: None) == (content, 0)
