"""布尔检索表达式：解析 / 求值 / 占位符渲染（ADR 0085 §2，口径对齐 endo intel_filter）.

支持：

- 关键词（含引号包裹的短语）；
- ``AND`` / ``OR`` / ``NOT`` 运算符（大小写不敏感）与括号优先级；
- 隐式 ``AND``（相邻项视为 AND）；
- 占位符 ``{topic}`` / ``{today}`` / ``{entrant}``，渲染时按上下文替换。

解析失败抛 :class:`RuleError`（创建 / 更新期直接回 400，不留到运行期）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

__all__ = [
    "RuleError",
    "evaluate_boolean",
    "extract_terms",
    "parse_boolean_query",
    "render_query",
    "substitute_placeholders",
]


class RuleError(ValueError):
    """规则声明错误（表达式不合法 / 占位符未提供等）."""


_TOK_LPAREN = "LPAREN"
_TOK_RPAREN = "RPAREN"
_TOK_AND = "AND"
_TOK_OR = "OR"
_TOK_NOT = "NOT"
_TOK_TERM = "TERM"
_TOK_EOF = "EOF"
_OPERATORS = (_TOK_AND, _TOK_OR, _TOK_NOT)

_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<LPAREN>\() |
        (?P<RPAREN>\)) |
        (?P<AND>AND\b) |
        (?P<OR>OR\b) |
        (?P<NOT>NOT\b) |
        (?P<TERM>"[^"]*" | '[^']*' | [^\s()]+)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


@dataclass(frozen=True, slots=True)
class _Term:
    value: str


@dataclass(frozen=True, slots=True)
class _Not:
    child: Any


@dataclass(frozen=True, slots=True)
class _And:
    left: Any
    right: Any


@dataclass(frozen=True, slots=True)
class _Or:
    left: Any
    right: Any


def _tokenize(expr: str) -> list[tuple[str, str]]:
    """把表达式切分为 ``(类型, 值)`` 列表（去引号 / 运算符大写化）."""
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        match = _TOKEN_RE.match(expr, pos)
        if match is None:
            pos += 1  # 无法识别的字符直接跳过，保持宽容
            continue
        pos = match.end()
        for kind in (_TOK_LPAREN, _TOK_RPAREN, _TOK_AND, _TOK_OR, _TOK_NOT, _TOK_TERM):
            value = match.group(kind)
            if value is None:
                continue
            if kind in _OPERATORS:
                tokens.append((kind, value.upper()))
            else:
                if kind == _TOK_TERM and len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
                    value = value[1:-1]
                tokens.append((kind, value))
            break
    tokens.append((_TOK_EOF, ""))
    return tokens


class _Parser:
    """递归下降：expr := or ; or := and (OR and)* ; and := not ((AND)? not)* ; not := NOT not | atom."""

    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> tuple[str, str]:
        return self._tokens[self._pos]

    def _advance(self) -> tuple[str, str]:
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def parse(self) -> Any:
        node = self._parse_or()
        if self._peek()[0] != _TOK_EOF:
            raise RuleError(f"表达式存在未消费的片段: {self._peek()[1]!r}")
        return node

    def _parse_or(self) -> Any:
        node = self._parse_and()
        while self._peek()[0] == _TOK_OR:
            self._advance()
            node = _Or(node, self._parse_and())
        return node

    def _parse_and(self) -> Any:
        node = self._parse_not()
        while True:
            kind = self._peek()[0]
            if kind == _TOK_AND:
                self._advance()
                node = _And(node, self._parse_not())
            elif kind in (_TOK_TERM, _TOK_LPAREN, _TOK_NOT):
                node = _And(node, self._parse_not())
            else:
                return node

    def _parse_not(self) -> Any:
        if self._peek()[0] == _TOK_NOT:
            self._advance()
            return _Not(self._parse_not())
        return self._parse_atom()

    def _parse_atom(self) -> Any:
        kind, value = self._peek()
        if kind == _TOK_TERM:
            self._advance()
            return _Term(value)
        if kind == _TOK_LPAREN:
            self._advance()
            node = self._parse_or()
            if self._peek()[0] != _TOK_RPAREN:
                raise RuleError("表达式缺少右括号")
            self._advance()
            return node
        raise RuleError(f"表达式存在意外片段: {value!r}")


def parse_boolean_query(expr: str) -> Any:
    """解析布尔表达式为 AST；空串返回 ``None``（表示不过滤）."""
    if not expr or not expr.strip():
        return None
    return _Parser(_tokenize(expr)).parse()


def evaluate_boolean(node: Any, text: str) -> bool:
    """在给定文本上求值（大小写不敏感的子串匹配）."""
    if node is None:
        return True
    lowered = text.lower()
    if isinstance(node, _Term):
        return node.value.lower() in lowered
    if isinstance(node, _Not):
        return not evaluate_boolean(node.child, text)
    if isinstance(node, _And):
        return evaluate_boolean(node.left, text) and evaluate_boolean(node.right, text)
    if isinstance(node, _Or):
        return evaluate_boolean(node.left, text) or evaluate_boolean(node.right, text)
    return False


def extract_terms(node: Any) -> list[str]:
    """从 AST 提取全部词项（用于 fallback 简单查询 / 打分加权）."""
    if node is None:
        return []
    if isinstance(node, _Term):
        return [node.value]
    if isinstance(node, _Not):
        return extract_terms(node.child)
    if isinstance(node, (_And, _Or)):
        return [*extract_terms(node.left), *extract_terms(node.right)]
    return []


def substitute_placeholders(expr: str, context: dict[str, Any]) -> str:
    """替换 ``{key}`` 占位符；已带引号的占位符保留引号，未带的自动加双引号.

    Raises:
        RuleError: 占位符在上下文中不存在（配置写错应在保存期暴露）。
    """
    if not expr:
        return expr

    def _replace(match: re.Match[str]) -> str:
        quote = match.group(1) or ""
        key = match.group(2).strip()
        if key not in context:
            raise RuleError(f"未知占位符: {{{key}}}")
        value = str(context[key])
        return f"{quote}{value}{quote}" if quote else f'"{value}"'

    return re.sub(r'(["\']?)\{([^{}]+)\}\1', _replace, expr)


def render_query(expr: str, context: dict[str, Any]) -> str:
    """渲染检索式：空串原样返回，占位符按上下文替换."""
    return substitute_placeholders(expr or "", context).strip()
