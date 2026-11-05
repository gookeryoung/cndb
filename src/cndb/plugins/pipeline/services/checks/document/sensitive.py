"""``document/sensitive`` —— 文档敏感内容检查（关键词 / 正则 / 逻辑组合）.

配置（``with``）：

- ``keywords`` / ``patterns``：简写，合并为名为 ``default`` 的隐式规则；
- ``rules``：命名规则映射或数组，每项 ``{name, keywords?, patterns?}``，任一关键词或正则命中
  即算该规则命中；单规则直接写映射即可；规则名不能含空白与括号（便于在 ``logic`` 中引用）；
- ``logic``：``any``（默认，任一规则命中）/ ``all``（全部规则命中）/ 布尔表达式，
  支持 ``and`` / ``or`` / ``not`` / 括号（也可写 ``&&`` / ``||`` / ``!``）。

检查扫描标题与正文：关键词不区分大小写，正则按 Python ``re`` 语义（``(?i)`` 可控大小写）。
发现物带规则名、命中的配置值（关键词 / 正则原文）、文档标题、正文行号与**有界上下文片段**
（命中行前后各 80 字符、单段不超过 240 字符，前端按高亮渲染，便于像 GitHub 注解一样定位）；
不返回整篇正文；文档不可见时由接口层按文档可见性裁剪上下文（draft 不对普通成员暴露）。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from cndb.plugins.pipeline.services.checks.base import (
    INPUT_JSON,
    INPUT_STRING,
    INPUT_STRING_LIST,
    CheckContext,
    CheckInput,
    CheckSpec,
    FindingDraft,
)
from cndb.plugins.pipeline.services.checks.registry import register_check
from cndb.plugins.pipeline.services.errors import CheckError

#: 单次检查最多规则数（防止逻辑组合与正则数量失控）
MAX_RULES = 50

#: 命名规则允许的键
_RULE_KEYS = {"name", "keywords", "patterns"}

#: 上下文片段：命中位置前后各保留的字符数
CONTEXT_CHARS = 80
#: 上下文片段最大长度（单行内截断，避免大表格行整段回传）
MAX_SNIPPET_CHARS = 240


@dataclass(frozen=True)
class _Rule:
    """一条敏感检查规则：任一关键词或正则命中即算命中."""

    name: str
    keywords: tuple[tuple[str, re.Pattern[str]], ...]
    patterns: tuple[tuple[str, re.Pattern[str]], ...]


@dataclass(frozen=True)
class _Hit:
    """规则命中的首个位置（配置值 + 文本区间，用于生成有界上下文）."""

    kind: str  # keyword / pattern
    value: str  # 命中的关键词原文或正则原文
    field: str  # title / content
    line: int
    start: int
    end: int
    text: str  # 命中所在文本（title / content），仅用于生成片段


SPEC = CheckSpec(
    uses="document/sensitive",
    title="敏感内容检查",
    category="document",
    inputs=(
        CheckInput(
            "keywords",
            INPUT_STRING_LIST,
            description="关键词列表（不区分大小写；任一命中算 default 规则命中）",
        ),
        CheckInput(
            "patterns",
            INPUT_STRING_LIST,
            description="正则表达式列表（任一命中算 default 规则命中；可用 (?i) 忽略大小写）",
        ),
        CheckInput(
            "rules",
            INPUT_JSON,
            description="命名规则数组：[{name, keywords?, patterns?}]，任一关键词 / 正则命中即算该规则命中",
        ),
        CheckInput(
            "logic",
            INPUT_STRING,
            description="规则逻辑组合：any（默认）/ all / 布尔表达式（如 `PII and (赌博 or 诈骗)`）",
            default="any",
        ),
    ),
    default_severity="warn",
    target_types=("document",),
)


def run(ctx: CheckContext, params: dict[str, Any]) -> Iterable[FindingDraft]:
    """逐文档检查敏感内容命中，并按 ``logic`` 组合规则结论."""
    rules = _parse_rules(params)
    names = [rule.name for rule in rules]
    logic = _parse_logic(str(params.get("logic") or "any"), names)
    referenced = _referenced_names(logic, names)

    findings: list[FindingDraft] = []
    for doc, content in ctx.iter_documents():
        states: dict[str, bool] = {}
        hits: dict[str, _Hit] = {}
        for rule in rules:
            hit = _match_rule(rule, doc.title or "", content or "")
            states[rule.name] = hit is not None
            if hit is not None:
                hits[rule.name] = hit
        if not _evaluate(logic, states):
            continue
        for rule in rules:
            hit = hits.get(rule.name)
            if hit is None or rule.name not in referenced:
                continue
            findings.append(
                FindingDraft(
                    message=_message(rule, hit),
                    target_type="document",
                    target_id=doc.id,
                    locator=_locator(rule, hit),
                    detail=_detail(rule, hit, doc.title or f"文档 #{doc.id}"),
                )
            )
    return findings


def _parse_rules(params: dict[str, Any]) -> list[_Rule]:
    """校验并展开 ``keywords`` / ``patterns`` / ``rules`` 为规则列表."""
    rules: list[_Rule] = []
    implicit_keywords = _as_string_list(params.get("keywords"), "keywords")
    implicit_patterns = _as_string_list(params.get("patterns"), "patterns")
    if implicit_keywords or implicit_patterns:
        rules.append(_build_rule("default", implicit_keywords, implicit_patterns, "default"))

    raw_rules = params.get("rules")
    if raw_rules is not None:
        # 单规则允许直接写映射（rules: {name: 证件号, patterns: [...]}），等价于单元素数组
        if isinstance(raw_rules, dict):
            raw_rules = [raw_rules]
        if not isinstance(raw_rules, list):
            raise CheckError("document/sensitive 参数 rules 必须是规则映射或规则数组")
        for index, raw in enumerate(raw_rules, start=1):
            if not isinstance(raw, dict):
                raise CheckError(f"document/sensitive rules 第 {index} 项必须是映射")
            unknown = sorted(set(raw) - _RULE_KEYS)
            if unknown:
                raise CheckError(f"document/sensitive rules 第 {index} 项不支持键：{', '.join(unknown)}")
            name = str(raw.get("name") or "").strip()
            if not name:
                raise CheckError(f"document/sensitive rules 第 {index} 项缺少 name")
            rules.append(
                _build_rule(
                    name,
                    _as_string_list(raw.get("keywords"), f"rules 第 {index} 项 keywords"),
                    _as_string_list(raw.get("patterns"), f"rules 第 {index} 项 patterns"),
                    f"rules 第 {index} 项（{name}）",
                )
            )

    if not rules:
        raise CheckError("document/sensitive 至少需要 keywords / patterns / rules 之一")
    if len(rules) > MAX_RULES:
        raise CheckError(f"document/sensitive 规则数 {len(rules)} 超过上限 {MAX_RULES}")
    names = [rule.name for rule in rules]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise CheckError(f"document/sensitive 规则名重复：{', '.join(duplicates)}")
    return rules


def _as_string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CheckError(f"document/sensitive {label} 必须是字符串或字符串列表")
    return [item.strip() for item in value if item.strip()]


def _build_rule(name: str, keywords: list[str], patterns: list[str], label: str) -> _Rule:
    if any(ch.isspace() or ch in "()" for ch in name):
        raise CheckError(f"document/sensitive 规则名不能含空白或括号：{name}")
    compiled_keywords = tuple(
        (keyword, re.compile(re.escape(keyword), re.IGNORECASE)) for keyword in dict.fromkeys(keywords)
    )
    compiled_patterns: list[tuple[str, re.Pattern[str]]] = []
    for pattern in dict.fromkeys(patterns):
        try:
            compiled_patterns.append((pattern, re.compile(pattern)))
        except re.error as exc:
            raise CheckError(f"document/sensitive {label} 的正则不合法：{pattern}（{exc}）") from exc
    if not compiled_keywords and not compiled_patterns:
        raise CheckError(f"document/sensitive {label} 至少需要 keywords 或 patterns 之一")
    return _Rule(name=name, keywords=compiled_keywords, patterns=tuple(compiled_patterns))


# ── 逻辑组合 ─────────────────────────────────────

#: 逻辑表达式节点：("rule", 名称) / ("not", 子节点) / ("and"|"or", 左, 右)
_Node = tuple[Any, ...]


def _parse_logic(raw: str, names: list[str]) -> _Node:
    text = raw.strip() or "any"
    lowered = text.lower()
    if lowered == "any":
        node: _Node = ("rule", names[0])
        for name in names[1:]:
            node = ("or", node, ("rule", name))
        return node
    if lowered == "all":
        node = ("rule", names[0])
        for name in names[1:]:
            node = ("and", node, ("rule", name))
        return node
    tokens = _tokenize_logic(text)
    parser = _LogicParser(tokens, names)
    node = parser.parse()
    return node


def _tokenize_logic(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char in "()":
            tokens.append(char)
            index += 1
            continue
        if text.startswith("&&", index):
            tokens.append("and")
            index += 2
            continue
        if text.startswith("||", index):
            tokens.append("or")
            index += 2
            continue
        if char == "!":
            tokens.append("not")
            index += 1
            continue
        end = index
        while end < len(text) and not text[end].isspace() and text[end] not in "()!&|":
            end += 1
        token = text[index:end]
        tokens.append(token.lower() if token.lower() in {"and", "or", "not"} else token)
        index = end
    return tokens


class _LogicParser:
    """递归下降解析 ``logic``：or < and < not < 原子."""

    def __init__(self, tokens: list[str], names: list[str]) -> None:
        self.tokens = tokens
        self.names = set(names)
        self.pos = 0

    def parse(self) -> _Node:
        node = self._parse_or()
        if self.pos != len(self.tokens):
            raise CheckError(f"document/sensitive logic 存在多余内容：{self.tokens[self.pos]}")
        return node

    def _peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _take(self) -> str:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def _parse_or(self) -> _Node:
        node = self._parse_and()
        while self._peek() == "or":
            self._take()
            node = ("or", node, self._parse_and())
        return node

    def _parse_and(self) -> _Node:
        node = self._parse_unary()
        while self._peek() == "and":
            self._take()
            node = ("and", node, self._parse_unary())
        return node

    def _parse_unary(self) -> _Node:
        token = self._peek()
        if token is None:
            raise CheckError("document/sensitive logic 表达式不完整")
        if token == "not":
            self._take()
            return ("not", self._parse_unary())
        if token == "(":
            self._take()
            node = self._parse_or()
            if self._peek() != ")":
                raise CheckError("document/sensitive logic 括号不匹配")
            self._take()
            return node
        if token in {")", "and", "or"}:
            raise CheckError(f"document/sensitive logic 在 {token} 处缺少规则名")
        self._take()
        if token not in self.names:
            available = "、".join(sorted(self.names))
            raise CheckError(f"document/sensitive logic 引用了不存在的规则：{token}（可用：{available}）")
        return ("rule", token)


def _evaluate(node: _Node, states: dict[str, bool]) -> bool:
    operator = node[0]
    if operator == "rule":
        return bool(states[node[1]])
    if operator == "not":
        return not _evaluate(node[1], states)
    if operator == "and":
        return _evaluate(node[1], states) and _evaluate(node[2], states)
    return _evaluate(node[1], states) or _evaluate(node[2], states)


def _referenced_names(node: _Node, order: list[str]) -> set[str]:
    names: set[str] = set()

    def visit(current: _Node) -> None:
        if current[0] == "rule":
            names.add(current[1])
        else:
            for child in current[1:]:
                if isinstance(child, tuple):
                    visit(child)

    visit(node)
    return names & set(order)


# ── 匹配与发现物 ─────────────────────────────────


def _match_rule(rule: _Rule, title: str, content: str) -> _Hit | None:
    for field, text in (("title", title), ("content", content)):
        if not text:
            continue
        for keyword, compiled in rule.keywords:
            match = compiled.search(text)
            if match is not None:
                return _Hit(
                    "keyword",
                    keyword,
                    field,
                    _line_of(text, match.start()),
                    match.start(),
                    match.end(),
                    text,
                )
        for raw, compiled in rule.patterns:
            match = compiled.search(text)
            if match is not None:
                return _Hit(
                    "pattern",
                    raw,
                    field,
                    _line_of(text, match.start()),
                    match.start(),
                    match.end(),
                    text,
                )
    return None


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _message(rule: _Rule, hit: _Hit) -> str:
    if hit.kind == "keyword":
        return f"敏感内容命中：「{rule.name}」关键词「{hit.value}」"
    return f"敏感内容命中：「{rule.name}」正则 /{hit.value}/"


def _locator(rule: _Rule, hit: _Hit) -> dict[str, Any]:
    return {
        "rule": rule.name,
        "kind": hit.kind,
        f"{hit.kind}": hit.value,
        "field": hit.field,
        "line": hit.line,
    }


def _detail(rule: _Rule, hit: _Hit, document_title: str) -> dict[str, Any]:
    """发现物 detail：规则口径 + 文档标题 + 有界上下文（命中位置按片段内偏移标注）."""
    snippet, match, match_start, match_end = _context(hit)
    return {
        "rule": rule.name,
        "kind": hit.kind,
        "field": hit.field,
        "document_title": document_title,
        "line": hit.line,
        "snippet": snippet,
        "match": match,
        "match_start": match_start,
        "match_end": match_end,
    }


def _context(hit: _Hit) -> tuple[str, str, int, int]:
    """截取命中行内的一段上下文（带省略号），返回 ``(snippet, match, 起点, 终点)``."""
    text = hit.text
    line_start = text.rfind("\n", 0, hit.start) + 1
    line_end = text.find("\n", hit.end)
    if line_end < 0:
        line_end = len(text)
    window_start = max(line_start, hit.start - CONTEXT_CHARS)
    window_end = min(line_end, max(hit.end, hit.start) + CONTEXT_CHARS, window_start + MAX_SNIPPET_CHARS)
    match_end = min(hit.end, window_end)
    snippet = text[window_start:window_end]
    offset = 0
    if window_start > line_start:
        snippet = "…" + snippet
        offset = 1
    if window_end < line_end:
        snippet = snippet + "…"
    match_start_in_snippet = hit.start - window_start + offset
    match_end_in_snippet = match_end - window_start + offset
    match = text[hit.start : match_end]
    if match_end < hit.end:
        match += "…"
    return snippet, match, match_start_in_snippet, match_end_in_snippet


register_check(SPEC, run)

__all__ = ["MAX_RULES", "SPEC", "run"]
