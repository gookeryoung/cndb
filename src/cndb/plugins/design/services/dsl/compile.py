"""结构 DSL 编译唯一入口（ADR 0079 D3）：原文 → IR / 诊断.

流程：长度限制 → 词法 / 语法（``parse.py``）→ 语义（param / module / 图元
校验与展开）→ IR。保存端点与预览端点都只调 ``compile_design``，前端零解析
（I1）；同原文 + 同参数覆盖 → 同 IR，全程无 IO / 随机（I3）。

变换下推：变换是仿射映射，与布尔集合运算可交换，因此 IR 不保留变换包裹节点，
而是把变换栈「先外后内」下推到每个图元的 ``transform.ops``（ADR 0079 §2）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from cndb.plugins.design.services.dsl.expressions import DslEvalError, base_env, eval_expr, eval_vector
from cndb.plugins.design.services.dsl.lexer import DslSyntaxError
from cndb.plugins.design.services.dsl.limits import (
    DEFAULT_FN,
    MAX_CONTENT_BYTES,
    MAX_FN,
    MAX_MODULE_RECURSION,
    MAX_MODULES,
    MAX_PARAMS,
    MAX_PRIMITIVES,
    MIN_FN,
)
from cndb.plugins.design.services.dsl.nodes import (
    CompileResult,
    Diagnostic,
    Expr,
    Instance,
    ModuleCall,
    ModuleDecl,
    PrimitiveCall,
    Program,
    TransformCall,
)
from cndb.plugins.design.services.dsl.parse import parse_program

#: IR 协议版本（前后端契约，随语法演进递增）
IR_VERSION = 1


def compile_design(content: str, overrides: Mapping[str, float] | None = None) -> CompileResult:
    """编译结构 DSL：成功返回 IR，失败返回结构化诊断（不产出半截 IR，I6）.

    ``overrides`` 为参数面板的实时覆盖（param 名 → 数值）；编译不通过时
    ``ir`` 为 ``None``，调用方不得落库（I2）。
    """
    try:
        ir = _compile(content, dict(overrides or {}))
    except (DslSyntaxError, DslEvalError) as exc:
        return CompileResult(
            ok=False,
            ir=None,
            diagnostics=(Diagnostic(severity="error", line=exc.line, col=exc.col, message=exc.message),),
        )
    return CompileResult(ok=True, ir=ir, diagnostics=())


# ── 语义编译 ─────────────────────────────────────────────


def _compile(content: str, overrides: dict[str, float]) -> dict[str, Any]:
    """词法 / 语法 / 语义三段编译；任何失败抛带位置的 DSL 异常."""
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise DslEvalError(f"DSL 原文超过 {MAX_CONTENT_BYTES // 1024}KB 上限", 1, 1)

    program = parse_program(content)

    if len(program.params) > MAX_PARAMS:
        bad = program.params[MAX_PARAMS]
        raise DslEvalError(f"param 数量超过上限 {MAX_PARAMS}", bad.line, bad.col)
    if len(program.modules) > MAX_MODULES:
        bad = program.modules[MAX_MODULES]
        raise DslEvalError(f"module 数量超过上限 {MAX_MODULES}", bad.line, bad.col)

    env, params_out = _eval_params(program, overrides)
    modules = _collect_modules(program)
    nodes = _Emitter(modules=modules, global_env=env).emit_top(program.instances)

    return {
        "version": IR_VERSION,
        "units": {"length": "mm", "angle": "deg"},
        "params": params_out,
        "nodes": nodes,
    }


def _eval_params(program: Program, overrides: dict[str, float]) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """按声明顺序求值顶层 param，合并覆盖值；返回求值环境与 IR params 列表."""
    env = base_env()
    params_out: list[dict[str, Any]] = []
    for decl in program.params:
        if decl.name == "PI":
            raise DslEvalError("PI 为内置常量，不能声明为 param", decl.line, decl.col)
        if decl.name in env:
            raise DslEvalError(f"重复的 param 声明 '{decl.name}'", decl.line, decl.col)
        if decl.name in overrides:
            value = _override_number(decl.name, overrides[decl.name], decl.line, decl.col)
        else:
            value = eval_expr(decl.value, env)
        if not math.isfinite(value):
            raise DslEvalError(f"参数 '{decl.name}' 的值必须为有限数值", decl.line, decl.col)
        env[decl.name] = value
        params_out.append({"name": decl.name, "value": value})

    unknown = sorted(set(overrides) - set(env))
    if unknown:
        raise DslEvalError(f"未知参数覆盖 '{unknown[0]}'", 1, 1)
    return env, params_out


def _override_number(name: str, value: object, line: int, col: int) -> float:
    """参数覆盖值必须是有限数值（布尔拒绝）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DslEvalError(f"参数 '{name}' 的覆盖值必须为数值", line, col)
    if not math.isfinite(float(value)):
        raise DslEvalError(f"参数 '{name}' 的覆盖值必须为有限数值", line, col)
    return float(value)


def _collect_modules(program: Program) -> dict[str, ModuleDecl]:
    """建模块注册表；重名报错（param 名与模块名空间独立）."""
    modules: dict[str, ModuleDecl] = {}
    for decl in program.modules:
        if decl.name in modules:
            raise DslEvalError(f"重复的 module 声明 '{decl.name}'", decl.line, decl.col)
        modules[decl.name] = decl
    return modules


# ── 图元校验（IR 节点构造） ────────────────────────────────


def _require_positive(name: str, value: float, primitive: str, line: int, col: int) -> None:
    if value <= 0:
        raise DslEvalError(f"{primitive} 的参数 {name} 必须为正数（实为 {value}）", line, col)


def _eval_fn(args: dict[str, Expr], env: dict[str, float], primitive: str, line: int, col: int) -> int:
    """fn（圆周分段数）：缺省 64，须为 [3, 256] 的整数."""
    if "fn" not in args:
        return DEFAULT_FN
    value = eval_expr(args["fn"], env)
    if int(value) != value:
        raise DslEvalError(f"{primitive} 的参数 fn 必须为整数（实为 {value}）", line, col)
    if not MIN_FN <= value <= MAX_FN:
        raise DslEvalError(f"{primitive} 的参数 fn 取值须在 {MIN_FN}~{MAX_FN} 之间（实为 {value}）", line, col)
    return int(value)


def _reject_unknown(args: dict[str, Expr], allowed: set[str], primitive: str, line: int, col: int) -> None:
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise DslEvalError(f"{primitive} 不支持参数 '{unknown[0]}'（可用：{'/'.join(sorted(allowed))}）", line, col)


def _eval_box(call: PrimitiveCall, env: dict[str, float]) -> dict[str, Any]:
    """box：size=[x,y,z] 或 w/h/d，全部为正."""
    _reject_unknown(call.args, {"size", "w", "h", "d"}, "box", call.line, call.col)
    if "size" in call.args:
        if any(k in call.args for k in ("w", "h", "d")):
            raise DslEvalError("box 的 size 与 w/h/d 不可同时使用", call.line, call.col)
        size = eval_vector(call.args["size"], env)
    else:
        missing = [k for k in ("w", "h", "d") if k not in call.args]
        if missing:
            raise DslEvalError(f"box 缺少必需参数 {missing[0]}（或整组 size）", call.line, call.col)
        size = (
            eval_expr(call.args["w"], env),
            eval_expr(call.args["h"], env),
            eval_expr(call.args["d"], env),
        )
    for k, v in zip(("x", "y", "z"), size, strict=True):
        _require_positive(k, v, "box", call.line, call.col)
    return {"op": "box", "size": [size[0], size[1], size[2]]}


def _eval_cyl(call: PrimitiveCall, env: dict[str, float]) -> dict[str, Any]:
    """cyl：沿 Z 轴圆柱，d / h 为正."""
    _reject_unknown(call.args, {"d", "h", "fn"}, "cyl", call.line, call.col)
    missing = [k for k in ("d", "h") if k not in call.args]
    if missing:
        raise DslEvalError(f"cyl 缺少必需参数 {missing[0]}", call.line, call.col)
    d = eval_expr(call.args["d"], env)
    h = eval_expr(call.args["h"], env)
    _require_positive("d", d, "cyl", call.line, call.col)
    _require_positive("h", h, "cyl", call.line, call.col)
    fn = _eval_fn(call.args, env, "cyl", call.line, call.col)
    return {"op": "cyl", "d": d, "h": h, "fn": fn}


def _eval_sphere(call: PrimitiveCall, env: dict[str, float]) -> dict[str, Any]:
    """sphere：r 为正."""
    _reject_unknown(call.args, {"r", "fn"}, "sphere", call.line, call.col)
    if "r" not in call.args:
        raise DslEvalError("sphere 缺少必需参数 r", call.line, call.col)
    r = eval_expr(call.args["r"], env)
    _require_positive("r", r, "sphere", call.line, call.col)
    fn = _eval_fn(call.args, env, "sphere", call.line, call.col)
    return {"op": "sphere", "r": r, "fn": fn}


def _eval_cone(call: PrimitiveCall, env: dict[str, float]) -> dict[str, Any]:
    """cone：d1 / d2 可一端为 0（尖锥），不可同时为 0；h 为正."""
    _reject_unknown(call.args, {"d1", "d2", "h", "fn"}, "cone", call.line, call.col)
    missing = [k for k in ("d1", "d2", "h") if k not in call.args]
    if missing:
        raise DslEvalError(f"cone 缺少必需参数 {missing[0]}", call.line, call.col)
    d1 = eval_expr(call.args["d1"], env)
    d2 = eval_expr(call.args["d2"], env)
    h = eval_expr(call.args["h"], env)
    for k, v in (("d1", d1), ("d2", d2)):
        if v < 0:
            raise DslEvalError(f"cone 的参数 {k} 不能为负（实为 {v}）", call.line, call.col)
    if d1 + d2 <= 0:
        raise DslEvalError("cone 的 d1 与 d2 不能同时为 0", call.line, call.col)
    _require_positive("h", h, "cone", call.line, call.col)
    fn = _eval_fn(call.args, env, "cone", call.line, call.col)
    return {"op": "cone", "d1": d1, "d2": d2, "h": h, "fn": fn}


def _eval_torus(call: PrimitiveCall, env: dict[str, float]) -> dict[str, Any]:
    """torus：圆环面，中心半径 r 与管径 tube 均为正."""
    _reject_unknown(call.args, {"r", "tube", "fn"}, "torus", call.line, call.col)
    missing = [k for k in ("r", "tube") if k not in call.args]
    if missing:
        raise DslEvalError(f"torus 缺少必需参数 {missing[0]}", call.line, call.col)
    r = eval_expr(call.args["r"], env)
    tube = eval_expr(call.args["tube"], env)
    _require_positive("r", r, "torus", call.line, call.col)
    _require_positive("tube", tube, "torus", call.line, call.col)
    fn = _eval_fn(call.args, env, "torus", call.line, call.col)
    return {"op": "torus", "r": r, "tube": tube, "fn": fn}


def _eval_tube(call: PrimitiveCall, env: dict[str, float]) -> dict[str, Any]:
    """tube：空心圆管，外径 > 内径 > 0，h 为正."""
    _reject_unknown(call.args, {"od", "id", "h", "fn"}, "tube", call.line, call.col)
    missing = [k for k in ("od", "id", "h") if k not in call.args]
    if missing:
        raise DslEvalError(f"tube 缺少必需参数 {missing[0]}", call.line, call.col)
    od = eval_expr(call.args["od"], env)
    inner = eval_expr(call.args["id"], env)
    h = eval_expr(call.args["h"], env)
    _require_positive("od", od, "tube", call.line, call.col)
    _require_positive("id", inner, "tube", call.line, call.col)
    if inner >= od:
        raise DslEvalError(f"tube 的 id 必须小于 od（实为 {inner} >= {od}）", call.line, call.col)
    _require_positive("h", h, "tube", call.line, call.col)
    fn = _eval_fn(call.args, env, "tube", call.line, call.col)
    return {"op": "tube", "od": od, "id": inner, "h": h, "fn": fn}


_PRIMITIVE_EVALUATORS = {
    "box": _eval_box,
    "cyl": _eval_cyl,
    "sphere": _eval_sphere,
    "cone": _eval_cone,
    "torus": _eval_torus,
    "tube": _eval_tube,
}


# ── 实例展开 ─────────────────────────────────────────────

#: 变换栈元素：(kind, [x, y, z])；列表按「先外后内」排列
_XfStack = tuple[tuple[str, list[float]], ...]


class _Emitter:
    """把 AST 实例展开为 IR 节点：模块递归、变换下推、图元上限计数."""

    def __init__(self, modules: dict[str, ModuleDecl], global_env: dict[str, float]) -> None:
        self._modules = modules
        self._global_env = global_env
        self._primitive_count = 0

    def emit_top(self, instances: tuple[Instance, ...]) -> list[dict[str, Any]]:
        """展开顶层实例；无实例时返回空列表（合法，预览显示空画布）."""
        return self._emit_instances(instances, env=self._global_env, xf=(), depth=0)

    def _emit_instances(
        self, instances: tuple[Instance, ...], env: dict[str, float], xf: _XfStack, depth: int
    ) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for inst in instances:
            nodes.extend(self._emit_instance(inst, env, xf, depth))
        return nodes

    def _emit_instance(self, inst: Instance, env: dict[str, float], xf: _XfStack, depth: int) -> list[dict[str, Any]]:
        if isinstance(inst, PrimitiveCall):
            return [self._emit_primitive(inst, env, xf)]
        if isinstance(inst, ModuleCall):
            return self._emit_module_call(inst, env, xf, depth)
        if isinstance(inst, TransformCall):
            vector = [eval_expr(item, env) for item in inst.vector]
            return self._emit_instances(inst.children, env, (*xf, (inst.kind, vector)), depth)
        # BooleanCall：children 一定非空（语法层已保证）
        children = self._emit_instances(inst.children, env, xf, depth)
        return [{"op": inst.kind, "children": children}]

    def _emit_primitive(self, call: PrimitiveCall, env: dict[str, float], xf: _XfStack) -> dict[str, Any]:
        """校验图元参数并构造 IR 节点（带变换栈下推）."""
        evaluator = _PRIMITIVE_EVALUATORS.get(call.name)
        if evaluator is None:  # pragma: no cover - 语法层已按白名单放行
            raise DslEvalError(f"未知图元 '{call.name}'", call.line, call.col)
        node = evaluator(call, env)
        self._primitive_count += 1
        if self._primitive_count > MAX_PRIMITIVES:
            raise DslEvalError(f"图元实例总数超过上限 {MAX_PRIMITIVES}", call.line, call.col)
        if xf:
            node["transform"] = {"ops": [[kind, list(vector)] for kind, vector in xf]}
        return node

    def _emit_module_call(
        self, call: ModuleCall, env: dict[str, float], xf: _XfStack, depth: int
    ) -> list[dict[str, Any]]:
        """展开模块实例化：绑参（位置 + 命名 + 默认值）后以模块作用域求值体."""
        if depth + 1 > MAX_MODULE_RECURSION:
            raise DslEvalError(f"模块实例化递归深度超过上限 {MAX_MODULE_RECURSION}", call.line, call.col)
        decl = self._modules.get(call.name)
        if decl is None:
            raise DslEvalError(f"未知模块 '{call.name}'", call.line, call.col)
        bindings = self._bind_module_args(decl, call, env)
        module_env = dict(self._global_env)
        module_env.update(bindings)
        return self._emit_instances(decl.body, module_env, xf, depth + 1)

    def _bind_module_args(self, decl: ModuleDecl, call: ModuleCall, env: dict[str, float]) -> dict[str, float]:
        """绑模块实参：位置按序、命名对名、缺省取默认值（重复绑定报错）.

        实参表达式在**调用方环境**下求值；默认值在「全局环境 + 已绑定参数」下
        求值（可引用全局 param 与先绑定的形参）。
        """
        if len(call.positional) > len(decl.params):
            raise DslEvalError(
                f"模块 '{decl.name}' 最多接收 {len(decl.params)} 个参数，实为 {len(call.positional)}",
                call.line,
                call.col,
            )
        bindings: dict[str, float] = {}
        param_names = {p.name for p in decl.params}
        for i, expr in enumerate(call.positional):
            name = decl.params[i].name
            bindings[name] = eval_expr(expr, env)
        for name, expr in call.named.items():
            if name not in param_names:
                raise DslEvalError(f"模块 '{decl.name}' 没有参数 '{name}'", call.line, call.col)
            if name in bindings:
                raise DslEvalError(f"模块 '{decl.name}' 的参数 '{name}' 重复绑定", call.line, call.col)
            bindings[name] = eval_expr(expr, env)
        default_env = dict(self._global_env)
        default_env.update(bindings)
        for param in decl.params:
            if param.name in bindings:
                continue
            if param.default is None:
                raise DslEvalError(f"模块 '{decl.name}' 缺少参数 '{param.name}'", call.line, call.col)
            value = eval_expr(param.default, default_env)
            if not math.isfinite(value):
                raise DslEvalError(f"模块 '{decl.name}' 的参数 '{param.name}' 必须为有限数值", call.line, call.col)
            bindings[param.name] = value
            default_env[param.name] = value
        return bindings


__all__ = [
    "IR_VERSION",
    "compile_design",
]
