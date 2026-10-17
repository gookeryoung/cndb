"""受限公式表达式引擎 —— 自定义计算模板的核心.

安全约束（硬性）：
- **不使用 `eval` / `exec`**；全部走自实现的 tokenizer + 递归下降解析器，
  只生成白名单 AST 节点，再按白名单求值；
- 只允许：数字字面量、字段引用 `[字段名]`、`+ - * /`、一元 `+/-`、后缀 `%`（百分号）、
  括号与白名单函数；任何其它字符 / 标识符 / 函数名一律抛 `FormulaError`。

语义（逐行求值 + 聚合看整列）：
- `[字段名]` 取当前行的数值，非数值 / 空值 → 该行结果为 `None`（不参与聚合）；
- 聚合函数 `sum/avg/count/min/max` 的参数必须是字段引用，作用域是**整列**
  （对所有行的该字段求值），返回一个常量，参与当前行表达式；
- 例：`round([合格数] / [产量] * 100, 2)` 逐行算合格率；
      `round(sum([合格数]) / sum([产量]) * 100, 2)` 逐行给出整体合格率（常量）。

数值口径：非有限值（NaN / ±Inf / 除零）一律输出 `None`；`count` 计有效数值个数。
"""

from __future__ import annotations

import math
import re
from typing import Any, Final

# 表达式长度上限（防超长串拖垮解析）
MAX_EXPR_LENGTH: Final = 500

# 白名单函数：名称 → (最少参数, 最多参数)
_SCALAR_FUNCS: Final[dict[str, tuple[int, int]]] = {
    "round": (1, 2),
    "abs": (1, 1),
    "sqrt": (1, 1),
    "pow": (2, 2),
    "ceil": (1, 1),
    "floor": (1, 1),
}
# 聚合函数：参数必须是单个字段引用，作用域为整列
_AGG_FUNCS: Final[dict[str, tuple[int, int]]] = {
    "sum": (1, 1),
    "avg": (1, 1),
    "count": (1, 1),
    "min": (1, 1),
    "max": (1, 1),
}
_ALL_FUNCS: Final[dict[str, tuple[int, int]]] = {**_SCALAR_FUNCS, **_AGG_FUNCS}


class FormulaError(ValueError):
    """公式非法（语法错误 / 未知字段 / 未知函数 / 参数不合法 / 超出白名单）."""


# ── Tokenizer ─────────────────────────────────────────

_NUMBER_RE: Final = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_IDENT_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# token 类型：num / ident / field / op / eof
Token = tuple[str, Any]


def _tokenize(expr: str) -> list[Token]:
    """把表达式串切分为 token 序列（空白忽略；无注释 / 字符串字面量）."""
    tokens: list[Token] = []
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "[":
            end = expr.find("]", i + 1)
            if end == -1:
                raise FormulaError("字段引用缺少右括号 ]")
            name = expr[i + 1 : end].strip()
            if not name:
                raise FormulaError("字段引用不能为空")
            tokens.append(("field", name))
            i = end + 1
            continue
        m = _NUMBER_RE.match(expr, i)
        if m:
            tokens.append(("num", float(m.group(0))))
            i = m.end()
            continue
        m = _IDENT_RE.match(expr, i)
        if m:
            tokens.append(("ident", m.group(0)))
            i = m.end()
            continue
        if ch in "+-*/(),%":
            tokens.append(("op", ch))
            i += 1
            continue
        raise FormulaError(f"非法字符: {ch!r}")
    tokens.append(("eof", None))
    return tokens


# ── Parser（递归下降） ─────────────────────────────────
# 文法：
#   expr    := term (('+' | '-') term)*
#   term    := unary (('*' | '/') unary)*
#   unary   := ('+' | '-') unary | postfix
#   postfix := primary '%'*
#   primary := NUMBER | FIELD | IDENT '(' [expr (',' expr)*] ')' | '(' expr ')'

# AST 节点为元组：(kind, ...)
Node = tuple[Any, ...]


class _Parser:
    """把 token 序列解析为白名单 AST."""

    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _next(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect_op(self, op: str) -> None:
        kind, value = self._peek()
        if kind != "op" or value != op:
            raise FormulaError(f"缺少 {op!r}")
        self._next()

    def parse(self) -> Node:
        node = self._parse_expr()
        kind, _ = self._peek()
        if kind != "eof":
            raise FormulaError("表达式存在多余内容")
        return node

    def _parse_expr(self) -> Node:
        node = self._parse_term()
        while True:
            kind, value = self._peek()
            if kind == "op" and value in ("+", "-"):
                self._next()
                node = ("binary", value, node, self._parse_term())
            else:
                return node

    def _parse_term(self) -> Node:
        node = self._parse_unary()
        while True:
            kind, value = self._peek()
            if kind == "op" and value in ("*", "/"):
                self._next()
                node = ("binary", value, node, self._parse_unary())
            else:
                return node

    def _parse_unary(self) -> Node:
        kind, value = self._peek()
        if kind == "op" and value in ("+", "-"):
            self._next()
            return ("unary", value, self._parse_unary())
        return self._parse_postfix()

    def _parse_postfix(self) -> Node:
        node = self._parse_primary()
        while True:
            kind, value = self._peek()
            if kind == "op" and value == "%":
                self._next()
                node = ("percent", node)
            else:
                return node

    def _parse_primary(self) -> Node:
        kind, value = self._next()
        if kind == "num":
            return ("num", float(value))
        if kind == "field":
            return ("field", str(value))
        if kind == "ident":
            # 标识符必须是函数调用
            k, v = self._peek()
            if k != "op" or v != "(":
                raise FormulaError(f"未知标识符: {value}")
            self._next()  # 吃掉 (
            args: list[Node] = []
            if not (self._peek()[0] == "op" and self._peek()[1] == ")"):
                args.append(self._parse_expr())
                while self._peek()[0] == "op" and self._peek()[1] == ",":
                    self._next()
                    args.append(self._parse_expr())
            self._expect_op(")")
            func = str(value).lower()
            spec = _ALL_FUNCS.get(func)
            if spec is None:
                raise FormulaError(f"未知函数: {value}")
            lo, hi = spec
            if not (lo <= len(args) <= hi):
                raise FormulaError(f"函数 {func} 参数个数不合法（需 {lo}~{hi} 个）")
            if func in _AGG_FUNCS and (len(args) != 1 or args[0][0] != "field"):
                raise FormulaError(f"聚合函数 {func} 的参数必须是字段引用，如 {func}([字段名])")
            return ("call", func, args)
        if kind == "op" and value == "(":
            node = self._parse_expr()
            self._expect_op(")")
            return node
        raise FormulaError("表达式不完整")


def parse(expr: str) -> Node:
    """解析公式串为 AST；非法时抛 ``FormulaError``."""
    if not isinstance(expr, str) or not expr.strip():
        raise FormulaError("公式不能为空")
    if len(expr) > MAX_EXPR_LENGTH:
        raise FormulaError(f"公式过长（上限 {MAX_EXPR_LENGTH} 字符）")
    return _Parser(_tokenize(expr)).parse()


def referenced_fields(node: Node) -> set[str]:
    """收集 AST 中引用的全部字段名（含聚合函数参数）."""
    kind = node[0]
    if kind == "field":
        return {node[1]}
    if kind == "num":
        return set()
    if kind == "unary":
        return referenced_fields(node[2])
    if kind == "percent":
        return referenced_fields(node[1])
    if kind == "binary":
        return referenced_fields(node[2]) | referenced_fields(node[3])
    if kind == "call":
        out: set[str] = set()
        for arg in node[2]:
            out |= referenced_fields(arg)
        return out
    return set()  # pragma: no cover - AST 由本模块构造，kind 必属白名单


def validate_formula(expr: str) -> None:
    """仅做语法 / 白名单校验（保存模板时调用），非法抛 ``FormulaError``."""
    parse(expr)


# ── 求值 ──────────────────────────────────────────────


def _to_number(value: Any) -> float | None:
    """任意单元格值 → 有限数值；不可转 / 非有限返回 None."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        if not s:
            return None
        try:
            f = float(s)
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    return None


class _Context:
    """求值上下文：当前行 + 整列（惰性缓存，聚合函数复用）."""

    def __init__(self, rows: list[dict[str, Any]], field_names: set[str]) -> None:
        self._rows = rows
        self._field_names = field_names
        self._columns: dict[str, list[float]] = {}
        self.row: dict[str, Any] = {}

    def scalar(self, name: str) -> float | None:
        if name not in self._field_names:
            raise FormulaError(f"未知字段: {name}")
        return _to_number(self.row.get(name))

    def column(self, name: str) -> list[float]:
        if name not in self._field_names:
            raise FormulaError(f"未知字段: {name}")
        cached = self._columns.get(name)
        if cached is None:
            vals: list[float] = []
            for r in self._rows:
                v = _to_number(r.get(name))
                if v is not None:
                    vals.append(v)
            self._columns[name] = vals
            cached = vals
        return cached


def _eval(node: Node, ctx: _Context, *, vector: bool = False) -> float | list[float] | None:
    """求值单节点；``vector=True`` 时字段引用返回整列数值列表（仅供聚合函数）."""
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "field":
        return ctx.column(node[1]) if vector else ctx.scalar(node[1])
    if kind == "unary":
        v = _eval(node[2], ctx)
        if v is None or isinstance(v, list):
            return None
        return -v if node[1] == "-" else v
    if kind == "percent":
        v = _eval(node[1], ctx)
        if v is None or isinstance(v, list):
            return None
        return v / 100.0
    if kind == "binary":
        a = _eval(node[2], ctx)
        b = _eval(node[3], ctx)
        if a is None or b is None or isinstance(a, list) or isinstance(b, list):
            return None
        op = node[1]
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            return None if b == 0 else a / b
        return None  # pragma: no cover - parser 只产出 + - * /
    if kind == "call":
        func, args = node[1], node[2]
        if func in _AGG_FUNCS:
            column = _eval(args[0], ctx, vector=True)
            values: list[float] = column if isinstance(column, list) else []
            if func == "count":
                return float(len(values))
            if not values:
                return None
            if func == "sum":
                return float(sum(values))
            if func == "avg":
                return sum(values) / len(values)
            if func == "min":
                return min(values)
            return max(values)
        # 标量函数
        argv: list[float] = []
        for a in args:
            v = _eval(a, ctx)
            if v is None or isinstance(v, list):
                return None
            argv.append(v)
        return _apply_scalar(func, argv)
    return None  # pragma: no cover - AST 由本模块构造


def _apply_scalar(func: str, argv: list[float]) -> float | None:
    """白名单标量函数求值（除零 / 定义域外返回 None）."""
    if func == "round":
        digits = int(argv[1]) if len(argv) > 1 else 0
        return round(argv[0], digits)
    if func == "abs":
        return abs(argv[0])
    if func == "sqrt":
        return math.sqrt(argv[0]) if argv[0] >= 0 else None
    if func == "pow":
        try:
            return float(argv[0] ** argv[1])
        except (OverflowError, ValueError):  # pragma: no cover - 极端指数
            return None
    if func == "ceil":
        return float(math.ceil(argv[0]))
    if func == "floor":
        return float(math.floor(argv[0]))
    return None  # pragma: no cover - parser 已限制函数白名单


def evaluate_column(
    expr: str,
    rows: list[dict[str, Any]],
    field_names: list[str] | set[str],
) -> list[float | None]:
    """逐行求值，返回与 ``rows`` 等长的一列结果（非法 / 不可数值化 → None）.

    Args:
        expr: 公式串（如 ``round([合格数] / [产量] * 100, 2)``）.
        rows: 行字典列表（键为字段显示名）.
        field_names: 该表的字段显示名集合，用于字段引用校验.
    """
    node = parse(expr)
    ctx = _Context(rows, set(field_names))
    out: list[float | None] = []
    for row in rows:
        ctx.row = row
        v = _eval(node, ctx)
        if v is None or isinstance(v, list) or not math.isfinite(v):
            out.append(None)
        else:
            out.append(float(v))
    return out


def evaluate_value(
    expr: str,
    rows: list[dict[str, Any]],
    field_names: list[str] | set[str],
) -> float | None:
    """求单一聚合值（供 KPI 场景）；取首行结果（常量表达式）或 None."""
    if not rows:
        return None
    return evaluate_column(expr, rows, field_names)[0]


__all__: list[str] = [
    "MAX_EXPR_LENGTH",
    "FormulaError",
    "evaluate_column",
    "evaluate_value",
    "parse",
    "referenced_fields",
    "validate_formula",
]
