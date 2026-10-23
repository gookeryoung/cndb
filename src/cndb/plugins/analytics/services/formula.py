"""受限公式表达式引擎 —— 自定义计算模板的核心.

安全约束（硬性）：
- **不使用 `eval` / `exec`**；全部走自实现的 tokenizer + 递归下降解析器，
  只生成白名单 AST 节点，再按白名单求值；
- 只允许：数字字面量、字段引用 `[字段名]`、`+ - * /`、一元 `+/-`、后缀 `%`（百分号）、
  括号与白名单函数；任何其它字符 / 标识符 / 函数名一律抛 `FormulaError`。

三类函数（白名单）：

1. **标量** `round / abs / sqrt / pow / ceil / floor`：逐行取值，作用在当前行；
2. **聚合** `sum / avg / count / min / max`：参数必须是字段引用，作用域是**整列**；
3. **窗口** `prev / lag / lead / diff / pct_change / cumsum / ma / rolling_sum / rolling_std / rank`：
   参数第一项必须是字段引用，作用域是「同一分区内按排序键排列的行序列」（ADR 0006 M4）。

窗口语义（与 evaluate_column 的 partition_by / order_by 配合）：

- 分区键 ``partition_by`` 为空 → 全表一个分区；排序键 ``order_by`` 为空 → 保持原始行序；
- ``lag([x], n)`` / ``prev([x])`` 取分区内前 n 行（n 缺省 1），越界为 ``None``；
  ``lead([x], n)`` 取后 n 行；``diff`` = 当前 − 前一行；``pct_change`` = （当前 − 前一行）/ |前一行|；
- ``ma / rolling_sum / rolling_std([x], n)`` 取含当前行的最近 n 行，**不满 n 行输出 None**
  （避免开头几行给出误导性的均值）；``rolling_std`` 为总体标准差；
- ``cumsum([x])`` 分区内累计和（跳过空值，全为空则 None）；
- ``rank([x])`` 分区内按值升序的名次（并列取最小名次，空值 None）。

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
# 窗口函数：第一参数必须是字段引用，第二参数（可选）为窗口长度 / 偏移量
_WINDOW_FUNCS: Final[dict[str, tuple[int, int]]] = {
    "prev": (1, 1),
    "lag": (1, 2),
    "lead": (1, 2),
    "diff": (1, 1),
    "pct_change": (1, 1),
    "cumsum": (1, 1),
    "ma": (1, 2),
    "rolling_sum": (1, 2),
    "rolling_std": (1, 2),
    "rank": (1, 1),
}
_ALL_FUNCS: Final[dict[str, tuple[int, int]]] = {**_SCALAR_FUNCS, **_AGG_FUNCS, **_WINDOW_FUNCS}

# 滚动类函数的缺省窗口长度
_DEFAULT_ROLLING = 3


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
            if func in _WINDOW_FUNCS and args[0][0] != "field":
                raise FormulaError(f"窗口函数 {func} 的第一个参数必须是字段引用，如 {func}([字段名])")
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
    try:
        return _Parser(_tokenize(expr)).parse()
    except RecursionError as exc:
        # 递归下降每层嵌套消耗多个栈帧；超长括号串会在长度上限内触发 RecursionError，
        # 必须转成 FormulaError（400），否则穿透成 500 且无法被路由层捕获。
        raise FormulaError("公式嵌套层级过深") from exc


def referenced_fields(node: Node) -> set[str]:
    """收集 AST 中引用的全部字段名（含聚合 / 窗口函数参数）."""
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


def uses_window(node: Node) -> bool:
    """AST 是否含窗口函数（决定是否需要分区 / 排序上下文）."""
    kind = node[0]
    if kind == "call":
        if node[1] in _WINDOW_FUNCS:
            return True
        return any(uses_window(arg) for arg in node[2])
    if kind in ("unary", "percent"):
        return uses_window(node[2] if kind == "unary" else node[1])
    if kind == "binary":
        return uses_window(node[2]) or uses_window(node[3])
    return False


def uses_window_expr(expr: str) -> bool:
    """公式串是否含窗口函数（前端 / 校验提示用）."""
    return uses_window(parse(expr))


def window_functions() -> dict[str, tuple[int, int]]:
    """窗口函数清单（供文档 / 前端快捷片段生成）."""
    return dict(_WINDOW_FUNCS)


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


def _is_blank_value(value: Any) -> bool:
    """空值判定：None 与纯空白字符串（与分组汇总口径一致）."""
    return value is None or (isinstance(value, str) and not value.strip())


def _rank_values(raw: list[Any]) -> list[int | None]:
    """分区内名次：升序、并列取最小名次、空值 None.

    全列可数值化时按**数值**排（``10`` 排在 ``2`` 之后）；否则按原始值字符串排 ——
    时间列的 ISO / 定宽格式字典序即时间序，文本列按其字面序。
    """
    usable = [i for i, value in enumerate(raw) if not _is_blank_value(value)]
    ranks: list[int | None] = [None] * len(raw)
    if not usable:
        return ranks

    numbers = [_to_number(raw[i]) for i in usable]
    pairs: list[tuple[Any, int]]
    if all(number is not None for number in numbers):
        pairs = [(number, index) for number, index in zip(numbers, usable, strict=True)]
    else:
        pairs = [(str(raw[i]).strip(), i) for i in usable]
    # 数值与字符串各自同质，key 取第 0 位即可（混合列已在上面的分支里统一成字符串）
    pairs.sort(key=lambda pair: pair[0])

    start = 0
    while start < len(pairs):
        end = start
        while end + 1 < len(pairs) and pairs[end + 1][0] == pairs[start][0]:
            end += 1
        for k in range(start, end + 1):
            ranks[pairs[k][1]] = start + 1
        start = end + 1
    return ranks


class _WindowCache:
    """单个分区 × 单个字段的窗口求值结构（前缀和 + 名次表，预处理一次 O(n)）.

    ``raw`` 是该分区的**原始值**（可能是时间 / 文本）：rank 需要按原始可比值排序，
    数值列则由 ``values`` 提供（两者等长、同序）。
    """

    __slots__ = ("_prefix_cnt", "_prefix_sq", "_prefix_sum", "_rank", "raw", "values")

    def __init__(self, values: list[float | None], raw: list[Any] | None = None) -> None:
        self.values = values
        self.raw = raw if raw is not None else list(values)
        size = len(values)
        self._prefix_sum = [0.0] * (size + 1)
        self._prefix_cnt = [0] * (size + 1)
        self._prefix_sq = [0.0] * (size + 1)
        for i, value in enumerate(values):
            if value is None:
                self._prefix_sum[i + 1] = self._prefix_sum[i]
                self._prefix_cnt[i + 1] = self._prefix_cnt[i]
                self._prefix_sq[i + 1] = self._prefix_sq[i]
            else:
                self._prefix_sum[i + 1] = self._prefix_sum[i] + value
                self._prefix_cnt[i + 1] = self._prefix_cnt[i] + 1
                self._prefix_sq[i + 1] = self._prefix_sq[i] + value * value
        self._rank: list[int | None] | None = None

    def at(self, pos: int) -> float | None:
        if 0 <= pos < len(self.values):
            return self.values[pos]
        return None

    def rolling(self, pos: int, size: int) -> tuple[float, float] | None:
        """含当前行的最近 ``size`` 行：返回 (sum, sumsq)；窗口内非空值不足 size → None."""
        if pos + 1 < size:
            return None
        start = pos + 1 - size
        count = self._prefix_cnt[pos + 1] - self._prefix_cnt[start]
        if count < size:
            return None
        total = self._prefix_sum[pos + 1] - self._prefix_sum[start]
        total_sq = self._prefix_sq[pos + 1] - self._prefix_sq[start]
        return total, total_sq

    def cumsum(self, pos: int) -> float | None:
        if self._prefix_cnt[pos + 1] == 0:
            return None
        return self._prefix_sum[pos + 1]

    def rank(self, pos: int) -> int | None:
        if self._rank is None:
            self._rank = _rank_values(self.raw)
        return self._rank[pos]


class _Context:
    """求值上下文：当前行 + 整列（惰性缓存）+ 窗口分区（惰性缓存）."""

    def __init__(self, rows: list[dict[str, Any]], field_names: set[str]) -> None:
        self._rows = rows
        self._field_names = field_names
        self._columns: dict[str, list[float]] = {}
        self._aligned: dict[str, list[float | None]] = {}
        self._raws: dict[str, list[Any]] = {}
        self._groups: list[list[int]] = [list(range(len(rows)))]
        self._window_cache: dict[tuple[int, str], _WindowCache] = {}
        self.row: dict[str, Any] = {}
        self.group_id = 0
        self.pos = 0

    def attach_groups(self, groups: list[list[int]]) -> None:
        self._groups = groups
        self._window_cache.clear()

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

    def aligned(self, name: str) -> list[float | None]:
        """与 ``rows`` 等长的行对齐数值列（窗口函数必须按位置对齐，不能丢空值）."""
        if name not in self._field_names:
            raise FormulaError(f"未知字段: {name}")
        cached = self._aligned.get(name)
        if cached is None:
            cached = [_to_number(r.get(name)) for r in self._rows]
            self._aligned[name] = cached
        return cached

    def raw_column(self, name: str) -> list[Any]:
        """行对齐的**原始值**列（不数值化；rank 等按原始可比值排序时用）."""
        if name not in self._field_names:
            raise FormulaError(f"未知字段: {name}")
        cached = self._raws.get(name)
        if cached is None:
            cached = [r.get(name) for r in self._rows]
            self._raws[name] = cached
        return cached

    def window_cache(self, name: str) -> _WindowCache:
        """当前分区的窗口结构（按 (分区, 字段) 惰性构建，多公式复用）."""
        key = (self.group_id, name)
        cached = self._window_cache.get(key)
        if cached is None:
            group = self._groups[self.group_id]
            values = self.aligned(name)
            raws = self.raw_column(name)
            cached = _WindowCache(
                [values[row_index] for row_index in group],
                [raws[row_index] for row_index in group],
            )
            self._window_cache[key] = cached
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
        if func in _WINDOW_FUNCS:
            return _apply_window(func, args, ctx)
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


def _apply_window(func: str, args: list[Node], ctx: _Context) -> float | None:
    """窗口函数求值（作用域 = 当前分区的有序行序列）."""
    name = str(args[0][1])
    cache = ctx.window_cache(name)
    pos = ctx.pos
    if func in ("prev", "lag", "lead"):
        offset = 1
        if len(args) > 1:
            raw = _eval(args[1], ctx)
            offset = int(raw) if isinstance(raw, float) and math.isfinite(raw) else 1
        offset = max(1, offset)
        current = cache.at(pos)
        if current is None:
            return None
        return cache.at(pos - offset) if func in ("prev", "lag") else cache.at(pos + offset)
    if func in ("diff", "pct_change"):
        current = cache.at(pos)
        previous = cache.at(pos - 1)
        if current is None or previous is None:
            return None
        delta = current - previous
        if func == "diff":
            return delta
        return None if previous == 0 else delta / abs(previous)
    if func == "cumsum":
        return cache.cumsum(pos)
    if func == "rank":
        value = cache.rank(pos)
        return float(value) if value is not None else None
    # 滚动窗口：ma / rolling_sum / rolling_std
    size = _DEFAULT_ROLLING
    if len(args) > 1:
        raw = _eval(args[1], ctx)
        size = int(raw) if isinstance(raw, float) and math.isfinite(raw) else _DEFAULT_ROLLING
    size = max(1, size)
    window = cache.rolling(pos, size)
    if window is None:
        return None
    total, total_sq = window
    if func == "rolling_sum":
        return total
    mean = total / size
    if func == "ma":
        return mean
    variance = max(0.0, total_sq / size - mean * mean)
    return math.sqrt(variance)


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
            result = argv[0] ** argv[1]
        except (OverflowError, ValueError, TypeError):
            return None
        # 负底数 + 非整数指数在 Python 返回 complex，float(complex) 会抛 TypeError；
        # 与 sqrt 的定义域口径一致，直接按「无有效数值」输出 None。
        if isinstance(result, complex):
            return None
        return float(result)
    if func == "ceil":
        return float(math.ceil(argv[0]))
    if func == "floor":
        return float(math.floor(argv[0]))
    return None  # pragma: no cover - parser 已限制函数白名单


def _sort_key(value: Any) -> tuple[int, Any]:
    """排序键：数值 < 文本 < 空值；空值恒排最后（与前端表格口径一致）."""
    number = _to_number(value)
    if number is not None:
        return (0, number)
    if isinstance(value, str) and value.strip():
        return (1, value.strip())
    return (2, "")


def partition_rows(
    rows: list[dict[str, Any]],
    *,
    partition_by: str | None = None,
    order_by: str | None = None,
    order_desc: bool = False,
    field_names: set[str] | None = None,
) -> list[list[int]]:
    """按分区键分组、按排序键排序，返回行索引序列（组内顺序即窗口顺序）.

    分区键为空 → 全表一个分区；排序键为空 → 保持原始行序；
    分组顺序 = 分区键首次出现顺序（与分组汇总桶序一致）。
    """
    names = field_names or set()
    if partition_by and names and partition_by not in names:
        raise FormulaError(f"未知分区字段: {partition_by}")
    if order_by and names and order_by not in names:
        raise FormulaError(f"未知排序字段: {order_by}")

    buckets: dict[Any, list[int]] = {}
    for index, row in enumerate(rows):
        key: Any = ("__all__",) if not partition_by else _bucket_key(row.get(partition_by))
        buckets.setdefault(key, []).append(index)

    groups: list[list[int]] = []
    for indexes in buckets.values():
        if order_by:
            indexes = sorted(
                indexes,
                key=lambda i, field=order_by: _sort_key(rows[i].get(field)),
                reverse=order_desc,
            )
        groups.append(indexes)
    return groups


def _bucket_key(value: Any) -> Any:
    """分组键：哈希不可用的值退回字符串表示，空值单独成组."""
    if value is None:
        return ("__none__",)
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def evaluate_column(
    expr: str,
    rows: list[dict[str, Any]],
    field_names: list[str] | set[str],
    *,
    partition_by: str | None = None,
    order_by: str | None = None,
    order_desc: bool = False,
) -> list[float | None]:
    """逐行求值，返回与 ``rows`` 等长的一列结果（非法 / 不可数值化 → None）.

    Args:
        expr: 公式串（如 ``round([合格数] / [产量] * 100, 2)``）.
        rows: 行字典列表（键为字段显示名）.
        field_names: 该表的字段显示名集合，用于字段引用校验.
        partition_by: 窗口函数的分区字段（空 = 全表一个分区）.
        order_by: 窗口函数的排序字段（空 = 原始行序）.
        order_desc: 排序方向（默认升序）.
    """
    node = parse(expr)
    names = set(field_names)
    ctx = _Context(rows, names)
    out: list[float | None] = [None] * len(rows)

    if not uses_window(node):
        # 无窗口函数：保持原始逐行路径（不做排序，零额外开销）
        for index, row in enumerate(rows):
            ctx.row = row
            v = _eval(node, ctx)
            if v is not None and not isinstance(v, list) and math.isfinite(v):
                out[index] = float(v)
        return out

    groups = partition_rows(
        rows,
        partition_by=partition_by,
        order_by=order_by,
        order_desc=order_desc,
        field_names=names,
    )
    ctx.attach_groups(groups)
    for group_id, group in enumerate(groups):
        ctx.group_id = group_id
        for pos, row_index in enumerate(group):
            ctx.pos = pos
            ctx.row = rows[row_index]
            v = _eval(node, ctx)
            if v is not None and not isinstance(v, list) and math.isfinite(v):
                out[row_index] = float(v)
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
    "partition_rows",
    "referenced_fields",
    "uses_window",
    "uses_window_expr",
    "validate_formula",
    "window_functions",
]
