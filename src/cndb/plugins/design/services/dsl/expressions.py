"""结构 DSL 表达式求值（ADR 0079 D2/D3）：白名单函数、无 eval、除零报错.

求值环境只有 ``float``（param 值与常量 PI）；编译确定性要求全程无 IO、
无随机（I3）。
"""

from __future__ import annotations

import math

from cndb.plugins.design.services.dsl.nodes import BinOp, Expr, FuncCall, Name, Num, UnaryOp, Vector

#: 圆周率常量：预置进求值环境，DSL 内直接写 ``PI``
PI = math.pi


class DslEvalError(Exception):
    """求值 / 语义错误（未知标识符、除零、非法图元参数等），携带 1 基行 / 列."""

    def __init__(self, message: str, line: int, col: int) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col


#: 白名单函数：名 → (最小参数个数, 最大参数个数, 实现)
_FUNCTIONS: dict[str, tuple[int, int, object]] = {
    "sin": (1, 1, math.sin),
    "cos": (1, 1, math.cos),
    "tan": (1, 1, math.tan),
    "asin": (1, 1, math.asin),
    "acos": (1, 1, math.acos),
    "atan2": (2, 2, math.atan2),
    "sqrt": (1, 1, math.sqrt),
    "abs": (1, 1, abs),
    "min": (1, 8, min),
    "max": (1, 8, max),
    "pow": (2, 2, math.pow),
    "floor": (1, 1, math.floor),
    "ceil": (1, 1, math.ceil),
    "round": (1, 1, round),
}

_FUNCTION_NAMES = "/".join(sorted(_FUNCTIONS))


def base_env() -> dict[str, float]:
    """求值环境的固定底座：只含常量 PI."""
    return {"PI": PI}


def eval_expr(expr: Expr, env: dict[str, float]) -> float:
    """在给定环境下求值表达式（数值域，布尔值拒绝）."""
    if isinstance(expr, Num):
        return expr.value
    if isinstance(expr, Name):
        if expr.name not in env:
            raise DslEvalError(f"未知标识符 '{expr.name}'", expr.line, expr.col)
        return env[expr.name]
    if isinstance(expr, UnaryOp):
        v = eval_expr(expr.operand, env)
        if expr.op == "-":
            return -v
        raise DslEvalError(f"不支持的一元运算符 '{expr.op}'", expr.line, expr.col)  # pragma: no cover - 语法层已拦截
    if isinstance(expr, BinOp):
        left = eval_expr(expr.left, env)
        right = eval_expr(expr.right, env)
        if expr.op == "+":
            return left + right
        if expr.op == "-":
            return left - right
        if expr.op == "*":
            return left * right
        if expr.op == "/":
            if right == 0:
                raise DslEvalError("除数为零", expr.line, expr.col)
            return left / right
        if expr.op == "%":
            if right == 0:
                raise DslEvalError("取模的右操作数为零", expr.line, expr.col)
            return math.fmod(left, right)
        raise DslEvalError(f"不支持的运算符 '{expr.op}'", expr.line, expr.col)  # pragma: no cover - 语法层已拦截
    if isinstance(expr, FuncCall):
        spec = _FUNCTIONS.get(expr.name)
        if spec is None:
            raise DslEvalError(f"未知函数 '{expr.name}'（可用：{_FUNCTION_NAMES}）", expr.line, expr.col)
        lo, hi, func = spec
        if not lo <= len(expr.args) <= hi:
            raise DslEvalError(
                f"函数 '{expr.name}' 参数个数应为 {lo}~{hi}，实为 {len(expr.args)}",
                expr.line,
                expr.col,
            )
        try:
            return float(func(*(eval_expr(a, env) for a in expr.args)))  # type: ignore[operator]
        except (ValueError, OverflowError):
            # 数值域错误（sqrt 负数、asin 越界、pow 溢出）
            raise DslEvalError(f"函数 '{expr.name}' 数值越界", expr.line, expr.col) from None
    if isinstance(expr, Vector):
        raise DslEvalError("向量只能用于图元的 size 参数，不能出现在数值表达式中", expr.line, expr.col)
    raise DslEvalError(f"不支持的表达式节点 {type(expr).__name__}", 0, 0)  # pragma: no cover - 类型收口


def eval_vector(expr: Expr, env: dict[str, float]) -> tuple[float, float, float]:
    """把 ``size`` 参数求值为三维向量（仅接受向量字面量）."""
    if isinstance(expr, Vector):
        return (  # pragma: no branch - 三元组由解析层保证
            eval_expr(expr.items[0], env),
            eval_expr(expr.items[1], env),
            eval_expr(expr.items[2], env),
        )
    raise DslEvalError("应为向量 [x, y, z]", expr.line, expr.col)


__all__ = [
    "PI",
    "DslEvalError",
    "base_env",
    "eval_expr",
    "eval_vector",
]
