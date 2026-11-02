"""acquisition 规则引擎单测（ADR 0085 §2）：表达式 / 筛选打分 / 去重键."""

from __future__ import annotations

import pytest

from cndb.plugins.acquisition.services.rules import (
    FilterRule,
    RuleError,
    apply_filters,
    dedupe_key,
    evaluate_boolean,
    normalize_url,
    parse_boolean_query,
    render_query,
    substitute_placeholders,
)


class TestBooleanExpr:
    def test_and_or_not_with_parentheses(self) -> None:
        ast = parse_boolean_query('(sulfide OR oxide) AND NOT "solid polymer"')
        assert evaluate_boolean(ast, "oxide electrolyte study") is True
        assert evaluate_boolean(ast, "oxide solid polymer electrolyte") is False
        assert evaluate_boolean(ast, "carbonate electrolyte") is False

    def test_implicit_and(self) -> None:
        ast = parse_boolean_query("solid electrolyte")
        assert evaluate_boolean(ast, "solid sulfide electrolyte") is True
        assert evaluate_boolean(ast, "solid sulfide") is False

    def test_empty_expression_passes_everything(self) -> None:
        assert parse_boolean_query("   ") is None
        assert evaluate_boolean(None, "任意文本") is True

    def test_unbalanced_parenthesis_raises(self) -> None:
        with pytest.raises(RuleError):
            parse_boolean_query("(a OR b")


class TestPlaceholders:
    def test_render_today_and_quoted_placeholder(self) -> None:
        assert render_query("{today}", {"today": "2026-11-02"}) == '"2026-11-02"'
        assert substitute_placeholders('"{topic}" AND x', {"topic": "固态电池"}) == '"固态电池" AND x'

    def test_unknown_placeholder_raises(self) -> None:
        with pytest.raises(RuleError):
            render_query("{missing}", {"today": "x"})


class TestFilterRule:
    def _item(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "title": "硫化物固态电解质界面研究",
            "summary": "界面阻抗降低，离子电导率提升",
            "doi": "10.1/ABC",
            "url": "https://example.com/a?utm_source=x",
            "published_at": "2025-03-01",
            "authors": [{"name": "张三"}],
            "affiliations": ["宁德时代"],
            "categories": ["cond-mat.mtrl-sci"],
            "document_type": "article",
            "citation_count": 30,
            "fulltext_url": "https://example.com/a.pdf",
        }
        base.update(overrides)
        return base

    def test_empty_rule_passes_all(self) -> None:
        outcome = apply_filters([self._item(), self._item(title="其它")], FilterRule())
        assert outcome.passed == 2
        assert outcome.rejected == 0

    def test_three_stage_keywords(self) -> None:
        rule = FilterRule(
            must_have_keywords=("固态电解质",),
            optional_keywords=("界面", "离子电导率"),
            exclude_keywords=("广告",),
        )
        assert apply_filters([self._item()], rule).passed == 1
        assert apply_filters([self._item(title="固态电解质广告")], rule).rejected == 1
        # optional 一个都不命中 → 拒绝
        assert apply_filters([self._item(title="固态电解质研究", summary="与配方无关")], rule).rejected == 1

    def test_boolean_takes_priority_over_must_have(self) -> None:
        rule = FilterRule(must_have_keywords=("不存在的词",), query_boolean="硫化物 OR 氧化物")
        assert apply_filters([self._item()], rule).passed == 1

    def test_hard_conditions(self) -> None:
        assert apply_filters([self._item()], FilterRule(institutions=("宁德时代",))).passed == 1
        assert apply_filters([self._item()], FilterRule(institutions=("比亚迪",))).rejected == 1
        assert apply_filters([self._item()], FilterRule(document_types=("review",))).rejected == 1
        assert apply_filters([self._item()], FilterRule(min_citations=50)).rejected == 1
        assert apply_filters([self._item(fulltext_url="")], FilterRule(require_fulltext=True)).rejected == 1
        assert apply_filters([self._item()], FilterRule(date_from="2025-01-01", date_to="2025-12-31")).passed == 1
        assert apply_filters([self._item()], FilterRule(date_from="2026-01-01")).rejected == 1

    def test_scores_sorted_desc(self) -> None:
        rule = FilterRule(must_have_keywords=("固态电解质",))
        weak = self._item(title="固态电解质", citation_count=0, fulltext_url="", summary="")
        strong = self._item(citation_count=500)
        outcome = apply_filters([weak, strong], rule)
        assert outcome.items[0]["title"] == strong["title"]
        assert 0 <= int(outcome.items[0]["match_score"]) <= 100

    def test_table_row_candidate_uses_string_columns(self) -> None:
        """表类候选没有 title：用全部字符串列做匹配文本（P0 表落点必需）."""
        rule = FilterRule(must_have_keywords=("北京",))
        assert apply_filters([{"city": "北京", "temp": 31.5}], rule).passed == 1
        assert apply_filters([{"city": "上海", "temp": 31.5}], rule).rejected == 1

    def test_validate_rejects_bad_boolean(self) -> None:
        with pytest.raises(RuleError):
            FilterRule(query_boolean="(a OR").validate()


class TestDedupe:
    def test_doi_wins_and_is_normalized(self) -> None:
        item = {"doi": "https://doi.org/10.1/ABC", "url": "https://example.com/a"}
        assert dedupe_key(item) == "doi:10.1/abc"

    def test_url_normalization(self) -> None:
        assert normalize_url("HTTPS://Example.com/a/?utm_source=x&id=1") == "https://example.com/a?id=1"
        item = {"url": "https://example.com/a?utm_source=x"}
        assert dedupe_key(item) == "url:https://example.com/a"

    def test_title_date_fallback_is_stable(self) -> None:
        first = dedupe_key({"title": "同一条 新闻", "published_at": "2026-01-01T08:00:00Z"})
        second = dedupe_key({"title": "同一条  新闻", "published_at": "2026-01-01T09:00:00Z"})
        assert first == second
        assert first.startswith("title:")

    def test_empty_item_still_produces_stable_key(self) -> None:
        assert dedupe_key({}, "job:1") == dedupe_key({}, "job:1")
        assert dedupe_key({}, "job:1").startswith("sha1:")
