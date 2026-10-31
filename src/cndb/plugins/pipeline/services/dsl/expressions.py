"""流水线 DSL 的受限表达式子集（ADR 0076 D3）.

只支持 ``${{ ... }}`` 包裹的白名单表达式，递归下降解析后求值：
字面量、``vars.*`` / ``on.*`` / ``jobs.<id>.conclusion`` 变量路径、
``== != < <= > >= && || !`` 运算符与 ``len / contains / startswith / endswith / to_number``
函数。**不使用 eval / Jinja2**，表达式无法触达 Python 运行时。
"""

from __future__ import annotations

import re
from typing import Any

from cndb.plugins.pipeline.services.errors import DslError

#: 表达式包装前缀 / 后缀
_EXPR_PREFIX = "${{"
_EXPR_SUFFIX = "}}"

_TOKEN_RE = re.compile(
    r"""
    (?P<space>\s+)
  | (?P<number>\d+(?:\.\d+)?)
  | (?P<string>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
  | (?P<operator>==|!=|<=|>=|&&|\|\||[<>!(),])
  | (?P<name>[^\W\d]\w*(?:\.(?:[^\W\d]\w*))*)
    """,
    re.VERBOSE,
)

#: 支持的函数名与参数个数（最小, 最大）
_FUNCTIONS: dict[str, tuple[int, int]] = {
    "len": (1, 1),
    "contains": (2, 2),
    "startswith": (2, 2),
    "endswith": (2, 2),
    "to_number": (1, 1),
}

#: AST 节点统一用 ``(kind, ...)`` 元组表达
ExprNode = tuple[Any, ...]


class ExpressionEvalError(Exception):
    """表达式求值失败（未知变量 / 类型不匹配），运行期按 ``false`` 处理."""


def is_expression(value: object) -> bool:
    """判断值是否是 ``${{ ... }}`` 表达式字符串（首尾必须恰好包裹）."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    return text.startswith(_EXPR_PREFIX) and text.endswith(_EXPR_SUFFIX)


def _unwrap(value: str) -> str:
    """去掉 ``${{ }}`` 包装；不是包装形式则原样返回（供内部 / 测试直接解析裸表达式）."""
    text = value.strip()
    if text.startswith(_EXPR_PREFIX) and text.endswith(_EXPR_SUFFIX):
        return text[len(_EXPR_PREFIX) : -len(_EXPR_SUFFIX)].strip()
    return text


def _tokenize(source: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(source):
        match = _TOKEN_RE.match(source, pos)
        if match is None:
            raise DslError(f"表达式语法错误：无法识别 {source[pos : pos + 12]!r}")
        kind = match.lastgroup or ""
        if kind != "space":
            tokens.append((kind, match.group(kind)))
        pos = match.end()
    return tokens


class _Parser:
    """递归下降解析器：or → and → not → comparison → primary."""

    def __init__(self, tokens: list[tuple[str, str]], source: str) -> None:
        self._tokens = tokens
        self._pos = 0
        self._source = source

    def _peek(self) -> tuple[str, str] | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _advance(self) -> tuple[str, str]:
        token = self._peek()
        if token is None:
            raise DslError(f"表达式语法错误：内容不完整（{self._source}）")
        self._pos += 1
        return token

    def _match_operator(self, *values: str) -> str | None:
        token = self._peek()
        if token is not None and token[0] == "operator" and token[1] in values:
            self._pos += 1
            return token[1]
        return None

    def parse(self) -> ExprNode:
        node = self._parse_or()
        if self._peek() is not None:
            raise DslError(f"表达式语法错误：多余内容 {self._peek()}（{self._source}）")
        return node

    def _parse_or(self) -> ExprNode:
        node = self._parse_and()
        while self._match_operator("||") is not None:
            node = ("or", node, self._parse_and())
        return node

    def _parse_and(self) -> ExprNode:
        node = self._parse_not()
        while self._match_operator("&&") is not None:
            node = ("and", node, self._parse_not())
        return node

    def _parse_not(self) -> ExprNode:
        if self._match_operator("!") is not None:
            return ("not", self._parse_not())
        return self._parse_comparison()

    def _parse_comparison(self) -> ExprNode:
        node = self._parse_primary()
        op = self._match_operator("==", "!=", "<", "<=", ">", ">=")
        if op is not None:
            return ("cmp", op, node, self._parse_primary())
        return node

    def _parse_primary(self) -> ExprNode:
        token = self._advance()
        kind, value = token
        if kind == "number":
            return ("lit", float(value) if "." in value else int(value))
        if kind == "string":
            return ("lit", _unquote(value))
        if kind == "name":
            if self._match_operator("(") is None:
                return _parse_name(value)
            return self._parse_call(value)
        if kind == "operator" and value == "(":
            node = self._parse_or()
            if self._match_operator(")") is None:
                raise DslError(f"表达式语法错误：缺少右括号（{self._source}）")
            return node
        raise DslError(f"表达式语法错误：非法记号 {value!r}（{self._source}）")

    def _parse_call(self, name: str) -> ExprNode:
        if name not in _FUNCTIONS:
            raise DslError(f"表达式使用了不支持的函数: {name}")
        args: list[ExprNode] = []
        if self._match_operator(")") is None:
            args.append(self._parse_or())
            while self._match_operator(",") is not None:
                args.append(self._parse_or())
            if self._match_operator(")") is None:
                raise DslError(f"表达式语法错误：函数缺少右括号（{self._source}）")
        low, high = _FUNCTIONS[name]
        if not low <= len(args) <= high:
            raise DslError(f"函数 {name} 参数个数不合法：{len(args)}")
        return ("call", name, args)


def _parse_name(value: str) -> ExprNode:
    """变量路径节点；``true`` / ``false`` / ``null`` 作字面量."""
    lowered = value.lower()
    if lowered == "true":
        return ("lit", True)
    if lowered == "false":
        return ("lit", False)
    if lowered == "null":
        return ("lit", None)
    return ("var", value.split("."))


def _unquote(value: str) -> str:
    """去掉字符串字面量的引号并还原常见转义."""
    body = value[1:-1]
    return body.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")


def parse_expression(source: str) -> ExprNode:
    """解析表达式（接受 ``${{ ... }}`` 包装形式或裸表达式），返回 AST.

    Raises:
        DslError: 语法错误 / 使用了不支持的函数。
    """
    raw = _unwrap(source)
    if not raw:
        raise DslError("表达式不能为空")
    tokens = _tokenize(raw)
    if not tokens:
        raise DslError("表达式不能为空")
    return _Parser(tokens, raw).parse()


def _resolve_var(parts: list[str], context: dict[str, Any]) -> Any:
    current: Any = context
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            raise ExpressionEvalError("表达式引用了未知变量: " + ".".join(parts))
        current = current[part]
    return current


def _compare(op: str, left: Any, right: Any) -> bool:
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    try:
        if op == "<":
            return bool(left < right)
        if op == "<=":
            return bool(left <= right)
        if op == ">":
            return bool(left > right)
        if op == ">=":
            return bool(left >= right)
    except TypeError as exc:
        raise ExpressionEvalError(f"表达式比较类型不匹配: {op}") from exc
    raise ExpressionEvalError(f"未知比较运算符: {op}")


def _call(name: str, args: list[Any]) -> Any:
    if name == "len":
        try:
            return len(args[0])
        except TypeError as exc:
            raise ExpressionEvalError("len() 参数不可计数") from exc
    if name == "contains":
        try:
            return args[1] in args[0]
        except TypeError as exc:
            raise ExpressionEvalError("contains() 参数类型不匹配") from exc
    if name == "startswith":
        return str(args[0]).startswith(str(args[1]))
    if name == "endswith":
        return str(args[0]).endswith(str(args[1]))
    if name == "to_number":
        try:
            return float(args[0])
        except (TypeError, ValueError) as exc:
            raise ExpressionEvalError("to_number() 无法转换为数值") from exc
    raise ExpressionEvalError(f"未知函数: {name}")


def _eval(node: ExprNode, context: dict[str, Any]) -> Any:
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "var":
        return _resolve_var(node[1], context)
    if kind == "not":
        return not bool(_eval(node[1], context))
    if kind == "and":
        return bool(_eval(node[1], context)) and bool(_eval(node[2], context))
    if kind == "or":
        return bool(_eval(node[1], context)) or bool(_eval(node[2], context))
    if kind == "cmp":
        return _compare(str(node[1]), _eval(node[2], context), _eval(node[3], context))
    if kind == "call":
        args = [_eval(arg, context) for arg in node[2]]
        return _call(str(node[1]), args)
    raise ExpressionEvalError(f"未知语法节点: {kind}")


def evaluate_expression(source: str, context: dict[str, Any]) -> Any:
    """解析并求值表达式（每次解析，表达式很短且无副作用）.

    Raises:
        ExpressionEvalError: 变量缺失 / 类型不匹配。
    """
    return _eval(parse_expression(source), context)


__all__ = [
    "ExprNode",
    "ExpressionEvalError",
    "evaluate_expression",
    "is_expression",
    "parse_expression",
]
