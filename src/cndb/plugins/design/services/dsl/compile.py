"""结构 DSL 编译唯一入口（ADR 0079 D3）：原文 → IR / 诊断.

流程：长度限制 → 词法 / 语法（``parse.py``）→ 语义（param / module / 图元
校验与展开）→ IR。保存端点与预览端点都只调 ``compile_design``，前端零解析
（I1）；同原文 + 同参数覆盖 → 同 IR，全程无 IO / 随机（I3）。

变换下推：变换是仿射映射，与布尔集合运算可交换，因此 IR 不保留变换包裹节点，
而是把变换栈「先外后内」下推到每个图元的 ``transform.ops``（ADR 0079 §2）。

装配大纲（ADR 0083 D2 / ADR 0084 D2）：与 ``nodes`` 同一次编译产出顶层 ``outline`` ——
``system`` 声明 = ``system``（复杂系统级，ADR 0084）、``module`` 实例 = ``assembly``
（组件级，可嵌套）、布尔块 = ``group``、图元 = ``part``（零件级）；每个节点带语句
起始的 1 基行 / 列。变换不建大纲节点（透明穿透），大纲节点数沿用既有编译期限制，
不新增限制项（ADR 0083 I3 / ADR 0084 I3）。``system`` 是纯组织层：把系统体平铺到
顶层后 ``nodes`` / ``params`` 完全一致（ADR 0084 I2）。

分文件与装配约束（ADR 0086）：``use "file_key"(参数…) as 标签`` 经 ``resolver``
回调拉取被引用 ``part`` 文件并递归编译（按 file_id + 版本 + 参数缓存，深拷贝注入）；
依赖闭包按 I4 预算累计（文件数 / 原文字节 / 引用深度 / module 数），循环引用与
缺失引用报带位置的诊断。``constraint`` 声明在同一作用域内经 ``constraints.py``
做确定性位姿传播（fixed / 首件接地 → BFS），结果下推到组件图元节点并写入 IR
``constraints``；欠约束为 warning 诊断，冲突抛错不产出 IR（I6）。
"""

from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from cndb.plugins.design.services.dsl.constraints import ConstraintError, Pose, authored_pose, solve_constraints
from cndb.plugins.design.services.dsl.expressions import DslEvalError, base_env, eval_expr, eval_vector
from cndb.plugins.design.services.dsl.lexer import DslSyntaxError
from cndb.plugins.design.services.dsl.limits import (
    DEFAULT_FN,
    MAX_CLOSURE_BYTES,
    MAX_CLOSURE_FILES,
    MAX_CLOSURE_MODULES,
    MAX_CONTENT_BYTES,
    MAX_FN,
    MAX_MODULE_RECURSION,
    MAX_MODULES,
    MAX_PARAMS,
    MAX_PRIMITIVES,
    MAX_REF_DEPTH,
    MIN_FN,
)
from cndb.plugins.design.services.dsl.nodes import (
    CompileResult,
    ConstraintDecl,
    DependencySnapshot,
    Diagnostic,
    Expr,
    FileSource,
    Instance,
    ModuleCall,
    ModuleDecl,
    PrimitiveCall,
    Program,
    SystemDecl,
    TransformCall,
    UseCall,
)
from cndb.plugins.design.services.dsl.parse import parse_program

#: IR 协议版本（前后端契约，随语法演进递增；v3 = v2 + 大纲 system 节点，ADR 0084 D2；
#: v4 = v3 + constraints[] + 大纲节点 file_id / use ref，ADR 0086 D2；
#: v5 = v4 + 大纲节点 node_index（首个所属顶层 nodes 下标，ADR 0103 D7））
IR_VERSION = 5

#: 伪 file_id：独立编译（无文件身份）时的根文件占位
_ROOT_FILE_ID = 0


def compile_design(
    content: str,
    overrides: Mapping[str, float] | None = None,
    *,
    file_kind: str = "assembly",
    file_id: int | None = None,
    resolver: Callable[[str], FileSource | None] | None = None,
) -> CompileResult:
    """编译结构 DSL：成功返回 IR，失败返回结构化诊断（不产出半截 IR，I6）.

    ``overrides`` 为参数面板的实时覆盖（param 名 → 数值）；``file_kind`` 为
    根文件类型（part / assembly，part 禁止 system）；``resolver`` 按
    ``file_key`` 返回被引用文件快照（ADR 0086 §2）。编译不通过时 ``ir`` 为
    ``None``，调用方不得落库（I2）。
    """
    closure = _Closure(resolver=resolver, root_id=file_id if file_id is not None else _ROOT_FILE_ID)
    closure.files_seen.add(closure.root_id)
    closure.stack.append(closure.root_id)
    closure.total_bytes = len(content.encode("utf-8"))
    if closure.total_bytes > MAX_CLOSURE_BYTES:
        return _error_result(f"依赖闭包原文累计超过 {MAX_CLOSURE_BYTES // 1024}KB 上限", 1, 1)
    try:
        ir = _compile(content, dict(overrides or {}), file_kind=file_kind, closure=closure)
    except (DslSyntaxError, DslEvalError, ConstraintError) as exc:
        line = getattr(exc, "line", 1)
        col = getattr(exc, "col", 1)
        message = getattr(exc, "message", str(exc))
        return _error_result(message, line, col)
    warnings = ir.pop("_warnings", [])
    diagnostics = tuple(Diagnostic(severity="warning", line=w[1], col=w[2], message=w[3]) for w in warnings)
    dependencies = tuple(closure.deps[k] for k in sorted(closure.deps, key=lambda fid: closure.deps[fid].file_key))
    return CompileResult(ok=True, ir=ir, diagnostics=diagnostics, dependencies=dependencies)


def _error_result(message: str, line: int, col: int) -> CompileResult:
    return CompileResult(
        ok=False,
        ir=None,
        diagnostics=(Diagnostic(severity="error", line=line, col=col, message=message),),
    )


@dataclass
class _Closure:
    """依赖闭包的编译期共享状态：预算累计、依赖快照与跨文件编译缓存（I4）."""

    resolver: Callable[[str], FileSource | None] | None
    root_id: int
    #: 已计入预算的文件（含根文件）
    files_seen: set[int] = field(default_factory=set)
    total_bytes: int = 0
    module_count: int = 0
    #: file_id → 依赖快照（不含根文件）
    deps: dict[int, DependencySnapshot] = field(default_factory=dict)
    #: (file_id, version, 参数覆盖) → (nodes, outline children) 模板（注入前深拷贝）
    cache: dict[tuple[Any, ...], tuple[list[dict[str, Any]], list[dict[str, Any]]]] = field(default_factory=dict)
    #: 当前正在编译的文件链（循环引用检测；元素为 file_id）
    stack: list[int] = field(default_factory=list)


def _compile(content: str, overrides: dict[str, float], *, file_kind: str, closure: _Closure) -> dict[str, Any]:
    """词法 / 语法 / 语义三段编译；任何失败抛带位置的 DSL 异常."""
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise DslEvalError(f"DSL 原文超过 {MAX_CONTENT_BYTES // 1024}KB 上限", 1, 1)

    program = parse_program(content)

    if file_kind == "part" and program.systems:
        bad = program.systems[0]
        raise DslEvalError("part 文件不允许声明 system（系统请放装配文件）", bad.line, bad.col)

    if len(program.params) > MAX_PARAMS:
        bad = program.params[MAX_PARAMS]
        raise DslEvalError(f"param 数量超过上限 {MAX_PARAMS}", bad.line, bad.col)
    decls = [item for item in program.items if isinstance(item, (ModuleDecl, SystemDecl))]
    if len(decls) > MAX_MODULES:
        bad = decls[MAX_MODULES]
        raise DslEvalError(f"module / system 声明数量超过上限 {MAX_MODULES}", bad.line, bad.col)

    env, params_out = _eval_params(program, overrides)
    modules, systems = _collect_decls(program)
    emitter = _Emitter(
        modules=modules,
        systems=systems,
        global_env=env,
        closure=closure,
    )
    nodes, outline, constraint_entries, warnings = emitter.emit_program(program, env)

    return {
        "version": IR_VERSION,
        "units": {"length": "mm", "angle": "deg"},
        "params": params_out,
        "nodes": nodes,
        "outline": {"children": outline},
        "constraints": constraint_entries,
        "_warnings": warnings,
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


def _collect_decls(program: Program) -> tuple[dict[str, ModuleDecl], dict[str, SystemDecl]]:
    """建 module / system 注册表；两名空间共享，重名报错（ADR 0084 D3）."""
    modules: dict[str, ModuleDecl] = {}
    systems: dict[str, SystemDecl] = {}
    for decl in (*program.modules, *program.systems):
        if isinstance(decl, ModuleDecl):
            if decl.name in modules or decl.name in systems:
                raise DslEvalError(f"重复的 module 声明 '{decl.name}'", decl.line, decl.col)
            modules[decl.name] = decl
            continue
        if decl.name in systems or decl.name in modules:
            raise DslEvalError(f"重复的 system 声明 '{decl.name}'", decl.line, decl.col)
        systems[decl.name] = decl
    return modules, systems


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


# ── 装配大纲节点（ADR 0083 D3） ──────────────────────────


def _part_outline(call: PrimitiveCall, node_index: int) -> dict[str, Any]:
    """图元 → 零件大纲节点（叶）；行 / 列为调用语句起点（1 基，I4）."""
    return {
        "kind": "part",
        "primitive": call.name,
        "line": call.line,
        "col": call.col,
        "node_index": node_index,
    }


# ── 实例展开 ─────────────────────────────────────────────

#: 变换栈元素：(kind, [x, y, z])；列表按「先外后内」排列
_XfStack = tuple[tuple[str, list[float]], ...]


class _Emitter:
    """把 AST 实例展开为 IR 节点：模块递归、变换下推、use 跨文件展开、图元上限计数."""

    def __init__(
        self,
        modules: dict[str, ModuleDecl],
        systems: dict[str, SystemDecl],
        global_env: dict[str, float],
        closure: _Closure,
    ) -> None:
        self._modules = modules
        self._systems = systems
        self._global_env = global_env
        self._closure = closure
        self._primitive_count = 0

    def emit_program(
        self, program: Program, env: dict[str, float]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[tuple[str, int, int, str]]]:
        """按顶层语句顺序展开：实例进入顶层作用域，``system`` 体各自成约束作用域.

        返回 ``(nodes, outline, IR 约束记录, 警告)``；``system`` 是纯组织层——
        几何平铺到顶层（ADR 0084 I2），大纲侧包一层 ``system`` 节点。
        """
        nodes: list[dict[str, Any]] = []
        outline: list[dict[str, Any]] = []
        entries: list[dict[str, Any]] = []
        warnings: list[tuple[str, int, int, str]] = []
        labels: dict[str, list[dict[str, Any]]] = {}
        ordered: list[str] = []
        poses: dict[str, Pose] = {}
        for item in program.items:
            if isinstance(item, SystemDecl):
                insts = tuple(i for i in item.body if isinstance(i, Instance))
                cons = tuple(c for c in item.body if isinstance(c, ConstraintDecl))
                sys_base = len(nodes)
                sys_nodes, sys_children, sys_entries, sys_warnings = self.emit_scope(
                    insts, cons, env, (), {}, [], {}, base=sys_base
                )
                nodes.extend(sys_nodes)
                outline.append(
                    {
                        "kind": "system",
                        "name": item.name,
                        "line": item.line,
                        "col": item.col,
                        "node_index": sys_base if sys_nodes else None,
                        "children": sys_children,
                    }
                )
                entries.extend(sys_entries)
                warnings.extend(sys_warnings)
                continue
            if isinstance(item, Instance):
                inst_nodes, inst_outline = self._emit_instance(item, env, (), 0, labels, ordered, poses, len(nodes))
                nodes.extend(inst_nodes)
                outline.extend(inst_outline)
        if program.constraints:
            top_entries, top_warnings = solve_constraints(program.constraints, labels, ordered, poses, env)
            entries.extend(top_entries)
            warnings.extend(top_warnings)
        return nodes, outline, entries, warnings

    def emit_scope(
        self,
        instances: tuple[Instance, ...],
        constraints: tuple[ConstraintDecl, ...],
        env: dict[str, float],
        xf: _XfStack,
        labels: dict[str, list[dict[str, Any]]],
        ordered: list[str],
        poses: dict[str, Pose],
        base: int = 0,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[tuple[str, int, int, str]]]:
        """展开一个约束作用域（文件顶层或 system 体）并求解装配约束（ADR 0086 §3）.

        返回 ``(nodes, outline 子节点, IR 约束记录, 警告)``；位姿下推在
        ``solve_constraints`` 内原地完成。``labels`` / ``ordered`` / ``poses``
        由调用方持有（顶层作用域跨语句累计）。``base`` 是本作用域 ``nodes``
        在**顶层 nodes 数组**中的起始下标（大纲 ``node_index`` 回填用，ADR 0103 §2）；
        独立编译（被引用文件模板）从 0 起算，由引用方整体平移。
        """
        nodes: list[dict[str, Any]] = []
        outline: list[dict[str, Any]] = []
        for inst in instances:
            inst_nodes, inst_outline = self._emit_instance(inst, env, xf, 0, labels, ordered, poses, base + len(nodes))
            nodes.extend(inst_nodes)
            outline.extend(inst_outline)
        if not constraints:
            return nodes, outline, [], []
        entries, warnings = solve_constraints(constraints, labels, ordered, poses, env)
        return nodes, outline, entries, warnings

    def _emit_instances(
        self,
        instances: tuple[Instance, ...],
        env: dict[str, float],
        xf: _XfStack,
        depth: int,
        labels: dict[str, list[dict[str, Any]]],
        ordered: list[str],
        poses: dict[str, Pose],
        base: int = 0,
        fixed_base: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        nodes: list[dict[str, Any]] = []
        outline: list[dict[str, Any]] = []
        for inst in instances:
            # fixed_base：布尔块内的子实例共享块的单个顶层下标（ADR 0103 §4#1）
            start = base if fixed_base else base + len(nodes)
            inst_nodes, inst_outline = self._emit_instance(inst, env, xf, depth, labels, ordered, poses, start)
            nodes.extend(inst_nodes)
            outline.extend(inst_outline)
        return nodes, outline

    def _emit_instance(
        self,
        inst: Instance,
        env: dict[str, float],
        xf: _XfStack,
        depth: int,
        labels: dict[str, list[dict[str, Any]]],
        ordered: list[str],
        poses: dict[str, Pose],
        base: int = 0,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """展开单个实例：同时产出几何节点与大纲节点（ADR 0083 D3）.

        ``base`` 为本实例产出的首个顶层节点下标；零产出（空模块 / 空装配）时
        大纲节点的 ``node_index`` 为 ``None``（ADR 0103 D7）。
        """
        if isinstance(inst, PrimitiveCall):
            return [self._emit_primitive(inst, env, xf)], [_part_outline(inst, base)]
        if isinstance(inst, ModuleCall):
            nodes, children = self._emit_module_call(inst, env, xf, depth, base)
            assembly = {
                "kind": "assembly",
                "name": inst.name,
                "line": inst.line,
                "col": inst.col,
                "node_index": base if nodes else None,
                "children": children,
            }
            self._register_label(inst.label, nodes, xf, labels, ordered, poses, inst.line, inst.col)
            if inst.label:
                assembly["label"] = inst.label
            return nodes, [assembly]
        if isinstance(inst, UseCall):
            return self._emit_use_call(inst, env, xf, labels, ordered, poses, base)
        if isinstance(inst, TransformCall):
            # 变换透明穿透：不建大纲节点，其子实例保持在当前父节点层级（下标照常累加）
            vector = [eval_expr(item, env) for item in inst.vector]
            return self._emit_instances(
                inst.children, env, (*xf, (inst.kind, vector)), depth, labels, ordered, poses, base
            )
        # BooleanCall：children 一定非空（语法层已保证）；整块是单个顶层 CSG 节点，
        # 故其下所有子节点共享块下标（ADR 0103 §4#1）
        nodes, children = self._emit_instances(
            inst.children, env, xf, depth, labels, ordered, poses, base, fixed_base=True
        )
        group = {
            "kind": "group",
            "op": inst.kind,
            "line": inst.line,
            "col": inst.col,
            "node_index": base if nodes else None,
            "children": children,
        }
        return [{"op": inst.kind, "children": nodes}], [group]

    def _register_label(
        self,
        label: str | None,
        nodes: list[dict[str, Any]],
        xf: _XfStack,
        labels: dict[str, list[dict[str, Any]]],
        ordered: list[str],
        poses: dict[str, Pose],
        line: int,
        col: int,
    ) -> None:
        """登记带标签组件：约束作用域内标签唯一（ADR 0086 D4）."""
        if label is None:
            return
        if label in labels:
            raise DslEvalError(f"重复的实例标签 '{label}'（同作用域内须唯一）", line, col)
        labels[label] = nodes
        ordered.append(label)
        poses[label] = authored_pose(xf)

    def _emit_use_call(
        self,
        call: UseCall,
        env: dict[str, float],
        xf: _XfStack,
        labels: dict[str, list[dict[str, Any]]],
        ordered: list[str],
        poses: dict[str, Pose],
        base: int = 0,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """分文件零件引用：解析 → 预算 → 递归编译 → 深拷贝注入并标注来源（ADR 0086 §2）."""
        source = self._resolve_source(call)
        bindings = self._bind_use_args(source, call, env)
        key = (source.file_id, source.version_number, tuple(sorted(bindings.items())))
        cached = self._closure.cache.get(key)
        if cached is None:
            nodes, children = _compile_file_source(source, bindings, self._closure, call)
            # 模板存深拷贝：原节点随后会被引用方变换 / 约束位姿原地修改
            self._closure.cache[key] = (copy.deepcopy(nodes), copy.deepcopy(children))
        else:
            nodes, children = copy.deepcopy(cached[0]), copy.deepcopy(cached[1])
        if xf:
            _prepend_xf(nodes, xf)
        name = call.label or source.file_key
        # 被引用文件模板的下标是文件内相对值，注入到引用方需整体平移到顶层基址
        assembly = {
            "kind": "assembly",
            "name": name,
            "line": call.line,
            "col": call.col,
            "file_id": source.file_id,
            "ref": {"file_id": source.file_id, "file_key": source.file_key, "kind": source.kind},
            "node_index": base if nodes else None,
            "children": _shift_node_index(_stamp_file_id(children, source.file_id), base),
        }
        self._register_label(call.label, nodes, xf, labels, ordered, poses, call.line, call.col)
        if call.label:
            assembly["label"] = call.label
        return nodes, [assembly]

    def _resolve_source(self, call: UseCall) -> FileSource:
        """按 file_key 解析被引用文件：缺失 / 非 part / 循环 / 预算超限均报错（I2/I4）."""
        if self._closure.resolver is None:
            raise DslEvalError("当前编译未提供文件解析器，无法使用 use 引用", call.line, call.col)
        if len(self._closure.stack) > MAX_REF_DEPTH:
            raise DslEvalError(f"跨文件引用深度超过上限 {MAX_REF_DEPTH}", call.line, call.col)
        source = self._closure.resolver(call.file_key)
        if source is None:
            raise DslEvalError(f"未找到引用的文件 '{call.file_key}'", call.line, call.col)
        if source.kind != "part":
            raise DslEvalError(f"use 目标必须是 part 文件（'{call.file_key}' 是 {source.kind}）", call.line, call.col)
        if source.file_id in self._closure.stack:
            chain = " → ".join([*map(str, self._closure.stack), str(source.file_id)])
            raise DslEvalError(f"循环引用：{chain}", call.line, call.col)
        if source.file_id not in self._closure.files_seen:
            self._closure.files_seen.add(source.file_id)
            if len(self._closure.files_seen) > MAX_CLOSURE_FILES:
                raise DslEvalError(f"依赖闭包文件数超过上限 {MAX_CLOSURE_FILES}", call.line, call.col)
            self._closure.total_bytes += len(source.content.encode("utf-8"))
            if self._closure.total_bytes > MAX_CLOSURE_BYTES:
                raise DslEvalError(f"依赖闭包原文累计超过 {MAX_CLOSURE_BYTES // 1024}KB 上限", call.line, call.col)
            self._closure.deps[source.file_id] = DependencySnapshot(
                file_id=source.file_id,
                file_key=source.file_key,
                version_number=source.version_number,
                content_hash=hashlib.sha256(source.content.encode("utf-8")).hexdigest(),
            )
        return source

    def _bind_use_args(self, source: FileSource, call: UseCall, env: dict[str, float]) -> dict[str, float]:
        """把 use 实参绑定为被引用文件的 param 覆盖（位置按序 + 命名对名）."""
        program = parse_program(source.content)
        param_names = [p.name for p in program.params]
        if len(call.positional) > len(param_names):
            raise DslEvalError(
                f"文件 '{source.file_key}' 最多接收 {len(param_names)} 个参数，实为 {len(call.positional)}",
                call.line,
                call.col,
            )
        bindings: dict[str, float] = {}
        for i, expr in enumerate(call.positional):
            bindings[param_names[i]] = eval_expr(expr, env)
        declared = set(param_names)
        for name, expr in call.named.items():
            if name not in declared:
                raise DslEvalError(f"文件 '{source.file_key}' 没有参数 '{name}'", call.line, call.col)
            if name in bindings:
                raise DslEvalError(f"文件 '{source.file_key}' 的参数 '{name}' 重复绑定", call.line, call.col)
            bindings[name] = eval_expr(expr, env)
        return bindings

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
        self, call: ModuleCall, env: dict[str, float], xf: _XfStack, depth: int, base: int = 0
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """展开模块实例化：绑参（位置 + 命名 + 默认值）后以模块作用域求值体."""
        if depth + 1 > MAX_MODULE_RECURSION:
            raise DslEvalError(f"模块实例化递归深度超过上限 {MAX_MODULE_RECURSION}", call.line, call.col)
        decl = self._modules.get(call.name)
        if decl is None:
            if call.name in self._systems:
                raise DslEvalError(f"'{call.name}' 是 system 声明，不可实例化（请改用 module）", call.line, call.col)
            raise DslEvalError(f"未知模块 '{call.name}'", call.line, call.col)
        bindings = self._bind_module_args(decl, call, env)
        module_env = dict(self._global_env)
        module_env.update(bindings)
        return self._emit_instances(decl.body, module_env, xf, depth + 1, {}, [], {}, base)

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


def _compile_file_source(
    source: FileSource,
    bindings: dict[str, float],
    closure: _Closure,
    call: UseCall,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """递归编译被引用 part 文件，返回 (nodes, outline 子节点) 模板（ADR 0086 §2）."""
    closure.stack.append(source.file_id)
    try:
        if len(source.content.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise DslEvalError(f"DSL 原文超过 {MAX_CONTENT_BYTES // 1024}KB 上限", call.line, call.col)
        program = parse_program(source.content)
        if program.systems:
            bad = program.systems[0]
            raise DslEvalError(f"part 文件 '{source.file_key}' 不允许声明 system", bad.line, bad.col)
        closure.module_count += len(program.modules) + len(program.systems)
        if closure.module_count > MAX_CLOSURE_MODULES:
            raise DslEvalError(f"依赖闭包 module / system 声明数超过上限 {MAX_CLOSURE_MODULES}", call.line, call.col)
        if len(program.params) > MAX_PARAMS:
            bad = program.params[MAX_PARAMS]
            raise DslEvalError(f"param 数量超过上限 {MAX_PARAMS}", bad.line, bad.col)
        decls = [item for item in program.items if isinstance(item, (ModuleDecl, SystemDecl))]
        if len(decls) > MAX_MODULES:
            bad = decls[MAX_MODULES]
            raise DslEvalError(f"module / system 声明数量超过上限 {MAX_MODULES}", bad.line, bad.col)

        env, _params_out = _eval_params(program, bindings)
        modules, _systems = _collect_decls(program)
        emitter = _Emitter(
            modules=modules,
            systems=_systems,
            global_env=env,
            closure=closure,
        )
        top_instances = [item for item in program.items if isinstance(item, Instance)]
        nodes, outline, _entries, _warnings = emitter.emit_scope(
            tuple(top_instances), program.constraints, env, (), {}, [], {}
        )
        return nodes, outline
    finally:
        closure.stack.pop()


def _prepend_xf(nodes: list[dict[str, Any]], xf: _XfStack) -> None:
    """把引用方的变换栈前插到被引用文件全部图元叶子（先外后内序保持）."""
    ops = [[kind, list(vector)] for kind, vector in xf]
    for node in nodes:
        _prepend_xf_node(node, ops)


def _prepend_xf_node(node: dict[str, Any], ops: list[list[Any]]) -> None:
    if "children" in node:
        for child in node["children"]:
            _prepend_xf_node(child, ops)
        return
    existing = (node.get("transform") or {}).get("ops", [])
    node["transform"] = {"ops": [*ops, *existing]}


def _shift_node_index(outline: list[dict[str, Any]], delta: int) -> list[dict[str, Any]]:
    """把大纲子树的 ``node_index`` 整体平移 ``delta``（被引用文件模板注入引用方时用）."""
    for node in outline:
        index = node.get("node_index")
        if index is not None:
            node["node_index"] = index + delta
        if node.get("children"):
            _shift_node_index(node["children"], delta)
    return outline


def _stamp_file_id(outline: list[dict[str, Any]], file_id: int) -> list[dict[str, Any]]:
    """递归给大纲子树标注源文件 id（前端按 file_id 打开源文件，ADR 0086 C7）.

    已带 ``file_id`` 的节点（嵌套 use 的更深层文件）保持原值不覆盖。
    """
    for node in outline:
        node.setdefault("file_id", file_id)
        if node.get("children"):
            _stamp_file_id(node["children"], file_id)
    return outline


__all__ = [
    "IR_VERSION",
    "compile_design",
]
