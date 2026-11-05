"""``document/sensitive`` 敏感内容检查测试（关键词 / 正则 / 逻辑组合）."""

from __future__ import annotations

from pathlib import Path

import pytest

from cndb.plugins.pipeline.services.checks.base import CheckContext
from cndb.plugins.pipeline.services.checks.document import sensitive
from cndb.plugins.pipeline.services.checks.registry import coerce_params
from cndb.plugins.pipeline.services.dsl.parse import compile_workflow
from cndb.plugins.pipeline.services.errors import CheckError
from tests.pipeline_helpers import make_document, make_user, make_workspace


@pytest.fixture
def owner(db):
    return make_user(db, "sensitive_check_owner")


@pytest.fixture
def ws(db, owner):
    return make_workspace(db, owner, "SensitiveCheckWS")


def _ctx(db, ws) -> CheckContext:
    return CheckContext(db, ws.id)


def _doc(db, ws, owner, content: str, title: str = "文档") -> None:
    make_document(db, ws, title, content, user=owner)


def test_keywords_implicit_rule_reports_configured_keyword_only(db, ws, owner):
    _doc(db, ws, owner, "第一行\n这里提到赌博网站，请勿访问。", title="说明")
    findings = list(sensitive.run(_ctx(db, ws), {"keywords": ["赌博", "诈骗"]}))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.message == "敏感内容命中：「default」关键词「赌博」"
    assert finding.locator == {
        "rule": "default",
        "kind": "keyword",
        "keyword": "赌博",
        "field": "content",
        "line": 2,
    }
    # D7：不回传命中的正文片段（只带配置值与定位）
    assert "网站" not in str(finding.locator)
    assert finding.detail == {"rule": "default", "kind": "keyword", "field": "content"}


def test_single_string_keyword_is_normalized(db, ws, owner):
    _doc(db, ws, owner, "有博彩内容")
    findings = list(sensitive.run(_ctx(db, ws), {"keywords": "博彩"}))
    assert [item.locator["keyword"] for item in findings] == ["博彩"]


def test_keywords_are_case_insensitive(db, ws, owner):
    _doc(db, ws, owner, "Please stop GAMBLING ads.")
    findings = list(sensitive.run(_ctx(db, ws), {"keywords": ["gambling"]}))
    assert [item.locator["keyword"] for item in findings] == ["gambling"]


def test_pattern_implicit_rule_matches_title(db, ws, owner):
    _doc(db, ws, owner, "正文", title="身份证 110101199001011234")
    findings = list(sensitive.run(_ctx(db, ws), {"patterns": [r"\b\d{17}[\dXx]\b"]}))
    assert len(findings) == 1
    assert findings[0].locator == {
        "rule": "default",
        "kind": "pattern",
        "pattern": r"\b\d{17}[\dXx]\b",
        "field": "title",
        "line": 1,
    }
    assert findings[0].message == r"敏感内容命中：「default」正则 /\b\d{17}[\dXx]\b/"


def test_named_rules_with_any_logic(db, ws, owner):
    _doc(db, ws, owner, "这里有博彩链接")
    rules = [
        {"name": "赌博", "keywords": ["博彩", "下注"]},
        {"name": "证件号", "patterns": [r"\b\d{17}[\dXx]\b"]},
    ]
    findings = list(sensitive.run(_ctx(db, ws), {"rules": rules, "logic": "any"}))
    assert [item.locator["rule"] for item in findings] == ["赌博"]


def test_all_logic_requires_every_rule(db, ws, owner):
    _doc(db, ws, owner, "博彩 110101199001011234")
    rules = [
        {"name": "赌博", "keywords": ["博彩"]},
        {"name": "证件号", "patterns": [r"\b\d{17}[\dXx]\b"]},
    ]
    findings = list(sensitive.run(_ctx(db, ws), {"rules": rules, "logic": "all"}))
    assert {item.locator["rule"] for item in findings} == {"赌博", "证件号"}


def test_all_logic_skips_document_missing_a_rule(db, ws, owner):
    _doc(db, ws, owner, "只有证件号 110101199001011234")
    rules = [
        {"name": "赌博", "keywords": ["博彩"]},
        {"name": "证件号", "patterns": [r"\b\d{17}[\dXx]\b"]},
    ]
    assert list(sensitive.run(_ctx(db, ws), {"rules": rules, "logic": "all"})) == []


def test_logic_expression_and_parentheses(db, ws, owner):
    _doc(db, ws, owner, "赌博广告，附证件号 110101199001011234")
    rules = [
        {"name": "赌博", "keywords": ["赌博"]},
        {"name": "诈骗", "keywords": ["中奖"]},
        {"name": "证件号", "patterns": [r"\b\d{17}[\dXx]\b"]},
    ]
    findings = list(sensitive.run(_ctx(db, ws), {"rules": rules, "logic": "赌博 and (诈骗 or 证件号)"}))
    assert {item.locator["rule"] for item in findings} == {"赌博", "证件号"}

    other_ws = make_workspace(db, owner, "SensitiveCheckWS2")
    _doc(db, other_ws, owner, "赌博活动")
    assert list(sensitive.run(_ctx(db, other_ws), {"rules": rules, "logic": "赌博 and (诈骗 or 证件号)"})) == []


def test_logic_not_and_symbol_aliases(db, ws, owner):
    _doc(db, ws, owner, "博彩活动，已加入白名单")
    rules = [
        {"name": "赌博", "keywords": ["博彩"]},
        {"name": "白名单", "keywords": ["白名单"]},
    ]
    assert list(sensitive.run(_ctx(db, ws), {"rules": rules, "logic": "赌博 and not 白名单"})) == []

    _doc(db, ws, owner, "博彩活动，尚未审核")
    findings = list(sensitive.run(_ctx(db, ws), {"rules": rules, "logic": "赌博 && !白名单"}))
    assert [item.locator["rule"] for item in findings] == ["赌博"]

    findings = list(sensitive.run(_ctx(db, ws), {"rules": rules, "logic": "白名单 || 赌博"}))
    assert {item.locator["rule"] for item in findings} == {"赌博", "白名单"}


def test_implicit_and_named_rules_can_be_combined(db, ws, owner):
    _doc(db, ws, owner, "赌博 110101199001011234")
    findings = list(
        sensitive.run(
            _ctx(db, ws),
            {
                "keywords": ["赌博"],
                "rules": [{"name": "证件号", "patterns": [r"\b\d{17}[\dXx]\b"]}],
                "logic": "default and (default or 证件号)",
            },
        )
    )
    assert {item.locator["rule"] for item in findings} == {"default", "证件号"}


def test_only_referenced_rules_emit_findings(db, ws, owner):
    _doc(db, ws, owner, "赌博与诈骗")
    rules = [
        {"name": "赌博", "keywords": ["赌博"]},
        {"name": "诈骗", "keywords": ["诈骗"]},
    ]
    findings = list(sensitive.run(_ctx(db, ws), {"rules": rules, "logic": "赌博"}))
    assert [item.locator["rule"] for item in findings] == ["赌博"]


@pytest.mark.parametrize(
    ("params", "match"),
    [
        ({}, "至少需要"),
        ({"rules": []}, "至少需要"),
        ({"rules": "赌博"}, "必须是规则数组"),
        ({"rules": ["赌博"]}, "必须是映射"),
        ({"rules": [{"keywords": ["赌博"]}]}, "缺少 name"),
        ({"rules": [{"name": "a"}]}, "至少需要 keywords 或 patterns"),
        ({"rules": [{"name": "a", "keywords": ["x"]}, {"name": "a", "keywords": ["y"]}]}, "规则名重复"),
        ({"rules": [{"name": "a b", "keywords": ["x"]}]}, "不能含空白"),
        ({"rules": [{"name": "a", "patterns": ["("]}]}, "正则不合法"),
        ({"rules": [{"name": "a", "keywords": ["x"], "extra": 1}]}, "不支持键"),
        ({"rules": [{"name": "a", "keywords": 1}]}, "必须是字符串或字符串列表"),
        ({"rules": [{"name": "a", "keywords": ["  "]}]}, "至少需要 keywords 或 patterns"),
        ({"keywords": ["x"], "logic": "不存在"}, "引用了不存在的规则"),
        ({"keywords": ["x"], "logic": "and default"}, "缺少规则名"),
        ({"keywords": ["x"], "logic": "(default"}, "括号不匹配"),
        ({"keywords": ["x"], "logic": "default)"}, "多余内容"),
        ({"keywords": ["x"], "logic": "not"}, "表达式不完整"),
    ],
)
def test_invalid_params_raise_check_error(db, ws, params, match):
    with pytest.raises(CheckError) as excinfo:
        list(sensitive.run(_ctx(db, ws), params))
    if match:
        assert match in str(excinfo.value)


def test_empty_title_and_content_are_skipped(db, ws, owner):
    make_document(db, ws, "", "", user=owner)
    assert list(sensitive.run(_ctx(db, ws), {"keywords": ["x"]})) == []


def test_rule_count_limit(db, ws):
    rules = [{"name": f"r{index}", "keywords": ["x"]} for index in range(sensitive.MAX_RULES + 1)]
    with pytest.raises(CheckError, match="超过上限"):
        list(sensitive.run(_ctx(db, ws), {"rules": rules}))


def test_seed_example_pipeline_flags_example_document(db, ws, owner):
    root = Path(__file__).resolve().parents[1]
    workflow = (
        root / "examples" / "datasets" / "工作区-某企业销售管理" / "pipelines" / "文档敏感内容巡检.yaml"
    ).read_text(encoding="utf-8")
    ir = compile_workflow(workflow)
    params = ir.jobs[0].steps[0].params

    content = (
        root
        / "examples"
        / "datasets"
        / "工作区-某企业销售管理"
        / "documents"
        / "02-交付与协作"
        / "04-客户资料交接（敏感内容示例）.md"
    ).read_text(encoding="utf-8")
    doc = make_document(db, ws, "客户资料交接（敏感内容示例）", content, user=owner)

    findings = list(sensitive.run(_ctx(db, ws), params))
    assert {item.locator["rule"] for item in findings} == {"身份证号", "邮箱地址", "内部资料"}
    assert len(findings) == 3
    assert {item.target_id for item in findings} == {doc.id}


def test_compiled_dsl_accepts_structured_rules():
    content = """
name: 敏感内容巡检
on:
  manual: true
jobs:
  文档:
    steps:
      - uses: document/sensitive
        with:
          rules:
            - name: 赌博
              keywords: [博彩, 下注]
            - name: 证件号
              patterns: ['\\b\\d{17}[\\dXx]\\b']
          logic: 赌博 and 证件号
"""
    ir = compile_workflow(content)
    params = ir.jobs[0].steps[0].params
    assert params["logic"] == "赌博 and 证件号"
    assert params["rules"][0]["name"] == "赌博"


def test_compiled_dsl_rejects_non_json_value_for_json_param():
    content = """
name: 日期不是 JSON
jobs:
  文档:
    steps:
      - uses: document/sensitive
        with:
          rules: {2026-01-01: x}
"""
    with pytest.raises(CheckError, match="类型不匹配"):
        compile_workflow(content)


def test_coerce_json_params_keeps_structure():
    rules = [{"name": "赌博", "keywords": ["博彩"]}]
    coerced = coerce_params(sensitive.SPEC, {"rules": rules, "logic": "any"})
    assert coerced == {"rules": rules, "logic": "any"}


def test_compiled_dsl_rejects_structured_value_for_non_json_param():
    content = """
name: 坏参数
jobs:
  文档:
    steps:
      - uses: document/links
        with:
          anything: {nested: 1}
"""
    with pytest.raises(CheckError, match="不支持参数"):
        compile_workflow(content)
