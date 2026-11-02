"""旧设计重构服务：提取顶层 ``module`` 为 ``part`` 文件（ADR 0086 D8 / §6）.

规则（逐条对应 ADR §6 重构服务）：

1. 仅处理 ``refactored_from_version IS NULL`` 且有顶层 ``module`` 的 assembly；
2. 按模块依赖拓扑序提取每个顶层 ``module`` 为 ``part`` 文件
   （``file_key = "<assembly_key>__<module>"``，冲突自动加后缀；
   ``folder = "parts/<assembly_folder>/<assembly_title>"``），
   模块形参 → 顶层 ``param``，模块体 → 顶层实例；
3. 模块内引用的全局 ``param`` 复制为 part 顶层参数默认值（含传递引用），
   并在所有调用点显式传参，保持装配参数联动；
4. 重写装配 ``content``：删除被提取的 ``module`` 声明，调用点替换为
   ``use "<key>"(…)`；保留 ``system`` 与顶层孤儿实例；
5. 编译前后 ``nodes`` 规范化（浮点 1e-6）逐节点比较；等价才落库，
   不等价整设计回滚并报告；
6. 成功写新版本（原版本保留），``refactored_from_version = 旧最新版本号``；
   批量模式逐设计事务，失败不阻断其它设计。

重构是文本层 → AST → 文本层的无损往返（表达式加括号保优先级），旧原文
永远留在 ``refactored_from_version`` 指向的版本行里（downgrade 可还原）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.design.models import DesignDesign
from cndb.plugins.design.services.dsl.compile import compile_design
from cndb.plugins.design.services.dsl.nodes import (
    BinOp,
    BooleanCall,
    ConstraintDecl,
    Expr,
    FuncCall,
    Instance,
    ModuleCall,
    ModuleDecl,
    Name,
    Num,
    ParamDecl,
    PrimitiveCall,
    Program,
    SystemDecl,
    TransformCall,
    UnaryOp,
    UseCall,
    Vector,
)
from cndb.plugins.design.services.dsl.parse import parse_program
from cndb.plugins.design.services.files import build_resolver, latest_version_number, sync_refs
from cndb.plugins.design.services.keys import generate_file_key

_TOLERANCE = 1e-6


def _hash_text(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ── 重构报告 ──────────────────────────────────────────────


@dataclass
class RefactorEntry:
    """单设计重构结果."""

    design_id: int
    title: str
    parts: list[str] = field(default_factory=list)
    version_number: int | None = None
    reason: str = ""
    error: str = ""


@dataclass
class RefactorReport:
    """批量重构汇总（refactored / skipped / failed，ADR §6 CLI 输出口径）."""

    refactored: list[RefactorEntry] = field(default_factory=list)
    skipped: list[RefactorEntry] = field(default_factory=list)
    failed: list[RefactorEntry] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "refactored": [vars(entry) for entry in self.refactored],
            "skipped": [vars(entry) for entry in self.skipped],
            "failed": [vars(entry) for entry in self.failed],
        }


# ── 表达式 / 实例渲染（AST → 文本） ───────────────────────


def _fmt(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def _render_expr(expr: Expr) -> str:
    if isinstance(expr, Num):
        return _fmt(expr.value)
    if isinstance(expr, Name):
        return expr.name
    if isinstance(expr, BinOp):
        return f"({_render_expr(expr.left)} {expr.op} {_render_expr(expr.right)})"
    if isinstance(expr, UnaryOp):
        operand = _render_expr(expr.operand)
        return f"-({operand})" if isinstance(expr.operand, BinOp) else f"-{operand}"
    if isinstance(expr, FuncCall):
        return f"{expr.name}({', '.join(_render_expr(arg) for arg in expr.args)})"
    if isinstance(expr, Vector):
        return f"[{', '.join(_render_expr(item) for item in expr.items)}]"
    raise ValueError(f"未知表达式节点: {type(expr).__name__}")  # pragma: no cover - AST 全覆盖


def _render_args(positional: tuple[Expr, ...], named: dict[str, Expr]) -> str:
    parts = [_render_expr(item) for item in positional]
    parts.extend(f"{name} = {_render_expr(value)}" for name, value in named.items())
    return ", ".join(parts)


def _render_instance(inst: Instance, indent: str = "") -> str:
    """渲染实例为多行文本（每行以 indent 缩进，无尾换行）."""
    pad = indent
    if isinstance(inst, PrimitiveCall):
        args = ", ".join(f"{name} = {_render_expr(value)}" for name, value in inst.args.items())
        return f"{pad}{inst.name}({args})"
    if isinstance(inst, TransformCall):
        vector = _render_expr(Vector(items=inst.vector, line=0, col=0))
        head = f"{pad}{inst.kind}({vector}) {{"
        body = "\n".join(_render_instance(child, indent + "  ") for child in inst.children)
        return f"{head}\n{body}\n{pad}}}"
    if isinstance(inst, BooleanCall):
        head = f"{pad}{inst.kind} {{"
        body = "\n".join(_render_instance(child, indent + "  ") for child in inst.children)
        return f"{head}\n{body}\n{pad}}}"
    if isinstance(inst, ModuleCall):
        label = f" as {inst.label}" if inst.label else ""
        return f"{pad}{inst.name}({_render_args(inst.positional, inst.named)}){label}"
    if isinstance(inst, UseCall):
        label = f" as {inst.label}" if inst.label else ""
        return f'{pad}use "{inst.file_key}"({_render_args(inst.positional, inst.named)}){label}'
    raise ValueError(f"未知实例节点: {type(inst).__name__}")  # pragma: no cover


def _render_constraint(decl: ConstraintDecl, indent: str = "") -> str:
    parts = [f"{name} = {ref.label}.{ref.anchor}" for name, ref in decl.refs.items()]
    parts.extend(f"{name} = {_render_expr(value)}" for name, value in decl.values.items())
    return f"{indent}constraint {decl.id} {decl.kind}({', '.join(parts)})"


# ── 模块分析 ──────────────────────────────────────────────


def _iter_exprs(inst: Instance) -> list[Expr]:
    """收集实例树里的全部表达式（参数引用分析用）."""
    exprs: list[Expr] = []

    def walk(node: Any) -> None:
        if isinstance(node, Expr):
            exprs.append(node)
            for field_name in ("left", "right", "operand", "args", "items"):
                value = getattr(node, field_name, None)
                if isinstance(value, Expr):
                    walk(value)
                elif isinstance(value, (tuple, list)):
                    for item in value:
                        walk(item)
            return
        if isinstance(node, Instance):
            if isinstance(node, PrimitiveCall):
                for value in node.args.values():
                    walk(value)
            elif isinstance(node, TransformCall):
                for item in node.vector:
                    walk(item)
                for child in node.children:
                    walk(child)
            elif isinstance(node, BooleanCall):
                for child in node.children:
                    walk(child)
            elif isinstance(node, (ModuleCall, UseCall)):
                for item in node.positional:
                    walk(item)
                for value in node.named.values():
                    walk(value)

    walk(inst)
    return exprs


def _module_global_params(module: ModuleDecl, param_names: set[str]) -> list[str]:
    """模块体引用的全局 param 名（按出现顺序去重）."""
    seen: list[str] = []
    for expr in _iter_exprs_list(module.body):
        if isinstance(expr, Name) and expr.name in param_names and expr.name not in seen:
            seen.append(expr.name)
    return seen


def _iter_exprs_list(instances: tuple[Instance, ...]) -> list[Expr]:
    result: list[Expr] = []
    for inst in instances:
        result.extend(_iter_exprs(inst))
    return result


def _param_dep_closure(param_map: dict[str, ParamDecl], seeds: list[str]) -> list[str]:
    """全局 param 默认值的传递引用闭包（part 顶层需一并复制）."""
    ordered: list[str] = []
    seen: set[str] = set()

    def visit(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        decl = param_map.get(name)
        if decl is not None:
            for expr in _collect_names(decl.value):
                if expr in param_map:
                    visit(expr)
        ordered.append(name)

    for seed in seeds:
        visit(seed)
    return ordered


def _collect_names(expr: Expr) -> list[str]:
    if isinstance(expr, Name):
        return [expr.name]
    if isinstance(expr, BinOp):
        return _collect_names(expr.left) + _collect_names(expr.right)
    if isinstance(expr, UnaryOp):
        return _collect_names(expr.operand)
    if isinstance(expr, FuncCall):
        return [name for arg in expr.args for name in _collect_names(arg)]
    if isinstance(expr, Vector):
        return [name for item in expr.items for name in _collect_names(item)]
    return []


def _module_dep_order(modules: dict[str, ModuleDecl]) -> list[str]:
    """模块按内部调用依赖拓扑排序（被依赖者先提取，键 = 模块名）."""
    order: list[str] = []
    state: dict[str, int] = {}

    def visit(name: str) -> None:
        status = state.get(name, 0)
        if status == 1:  # pragma: no cover - 编译期已拒绝递归
            raise ValueError(f"模块循环调用: {name}")
        if status == 2:
            return
        state[name] = 1
        for call in _module_calls(list(modules[name].body)):
            if call.name in modules:
                visit(call.name)
        state[name] = 2
        order.append(name)

    for name in modules:
        visit(name)
    return order


def _module_calls(instances: list[Instance]) -> list[ModuleCall]:
    calls: list[ModuleCall] = []
    for inst in instances:
        if isinstance(inst, ModuleCall):
            calls.append(inst)
        elif isinstance(inst, TransformCall | BooleanCall):
            calls.extend(_module_calls(list(inst.children)))
    return calls


# ── part 文件生成 ─────────────────────────────────────────


def _render_part(
    module: ModuleDecl,
    globals_needed: list[str],
    param_map: dict[str, ParamDecl],
    replaced_keys: dict[str, str],
    call_globals: dict[str, list[str]] | None = None,
    decl_params: dict[str, list[str]] | None = None,
) -> str:
    """渲染 part 文件文本：顶层 param + 模块体实例（内部模块调用 → use）."""
    lines: list[str] = []
    for name in _param_dep_closure(param_map, globals_needed):
        decl = param_map.get(name)
        default = _render_expr(decl.value) if decl is not None and decl.value is not None else "0"
        lines.append(f"param {name} = {default}")
    for param in module.params:
        default = _render_expr(param.default) if param.default is not None else "1"
        lines.append(f"param {param.name} = {default}")
    body = [_rewrite_instance(inst, replaced_keys, call_globals, decl_params) for inst in module.body]
    return "\n".join(lines + body) + "\n"


def _rewrite_instance(
    inst: Instance,
    replaced_keys: dict[str, str],
    call_globals: dict[str, list[str]] | None = None,
    decl_params: dict[str, list[str]] | None = None,
) -> str:
    """实例渲染：被提取模块的调用点替换为 ``use "<key>"`` 并显式传全局参（规则 3）."""
    if isinstance(inst, TransformCall):
        vector = _render_expr(Vector(items=inst.vector, line=0, col=0))
        body = "\n".join(_rewrite_instance(child, replaced_keys, call_globals) for child in inst.children)
        return f"{inst.kind}({vector}) {{\n{body}\n}}"
    if isinstance(inst, BooleanCall):
        body = "\n".join(_rewrite_instance(child, replaced_keys, call_globals) for child in inst.children)
        return f"{inst.kind} {{\n{body}\n}}"
    if isinstance(inst, ModuleCall) and inst.name in replaced_keys:
        key = replaced_keys[inst.name]
        globals_needed = (call_globals or {}).get(inst.name, [])
        named = dict(inst.named)
        if globals_needed:
            # part 文件参数序 = 闭包全局参 + 模块形参，位置实参会错位 →
            # 全部改写为命名实参（需拿到模块形参名，经 decl_params 传入）
            for i, expr in enumerate(inst.positional):
                name = (decl_params or {}).get(inst.name, [None] * (i + 1))[i]
                if name is None:
                    break
                named.setdefault(name, expr)
            for name in globals_needed:
                named.setdefault(name, Name(name=name, line=inst.line, col=inst.col))
            label = f" as {inst.label}" if inst.label else ""
            return f'use "{key}"({_render_args((), named)}){label}'
        label = f" as {inst.label}" if inst.label else ""
        return f'use "{key}"({_render_args(inst.positional, named)}){label}'
    return _render_instance(inst)


def _render_assembly(
    program: Program,
    extracted: set[str],
    replaced_keys: dict[str, str],
    call_globals: dict[str, list[str]] | None = None,
    decl_params: dict[str, list[str]] | None = None,
) -> str:
    """渲染重写后的装配：删除被提取 module，调用点替换为 use（含全局参显式传递）."""
    lines: list[str] = []
    for item in program.items:
        if isinstance(item, ParamDecl):
            lines.append(f"param {item.name} = {_render_expr(item.value)}")
        elif isinstance(item, ModuleDecl):
            if item.name not in extracted:
                lines.append(_render_module(item))
        elif isinstance(item, SystemDecl):
            body = [
                _rewrite_instance(node, replaced_keys, call_globals, decl_params)
                if not isinstance(node, ConstraintDecl)
                else _render_constraint(node, "")
                for node in item.body
            ]
            lines.append(f"system {item.name} {{\n" + "\n".join(body) + "\n}")
        elif isinstance(item, ConstraintDecl):
            lines.append(_render_constraint(item))
        else:
            lines.append(_rewrite_instance(item, replaced_keys, call_globals, decl_params))
    return "\n".join(lines) + "\n"


def _render_module(module: ModuleDecl) -> str:
    params = ", ".join(param.name for param in module.params)
    body = "\n".join(_rewrite_instance(inst, {}) for inst in module.body)
    return f"module {module.name}({params}) {{\n{body}\n}}"


# ── 等价校验 ──────────────────────────────────────────────


def _normalize(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def nodes_equal(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """编译前后 ``nodes`` 规范化（浮点 1e-6）逐节点比较（ADR §6 规则 5）."""
    return _normalize(before) == _normalize(after)


# ── 单设计重构 ────────────────────────────────────────────


def _unique_title(db: Session, workspace_id: int, folder: str, title: str) -> str:
    base = title
    n = 2
    while (
        db.query(DesignDesign)
        .filter(
            DesignDesign.workspace_id == workspace_id,
            DesignDesign.folder == folder,
            DesignDesign.title == title,
        )
        .first()
        is not None
    ):
        title = f"{base}-{n}"
        n += 1
    return title


def refactor_design(db: Session, design: DesignDesign, *, dry_run: bool = False) -> RefactorEntry:
    """重构单个设计：提取顶层 module 为 part 文件，等价校验通过才落库."""
    entry = RefactorEntry(design_id=design.id, title=design.title)
    if design.kind != "assembly" or design.refactored_from_version is not None:
        entry.reason = "非 assembly 或已重构过"
        return entry
    try:
        program = parse_program(design.content)
    except Exception as exc:  # DslSyntaxError / 词法错误：保留原文报 failed
        entry.error = f"原文解析失败: {exc}"
        return entry
    if not program.modules:
        entry.reason = "无顶层 module"
        return entry

    modules = {module.name: module for module in program.modules}
    param_map = {param.name: param for param in program.params}
    param_names = set(param_map)
    try:
        order = _module_dep_order(modules)
    except ValueError as exc:
        entry.error = str(exc)
        return entry

    replaced_keys: dict[str, str] = {}
    part_specs: list[tuple[str, str, str]] = []  # (title, folder, content)
    call_globals = {name: _module_global_params(modules[name], param_names) for name in modules}
    decl_params = {name: [param.name for param in modules[name].params] for name in modules}
    for name in order:
        module = modules[name]
        folder = "/".join(part for part in ("parts", design.folder, design.title) if part)
        key = generate_file_key(db, design.workspace_id, name, preferred=f"{design.file_key}__{name}")
        replaced_keys[name] = key
        content = _render_part(module, call_globals[name], param_map, replaced_keys, call_globals, decl_params)
        part_specs.append((_unique_title(db, design.workspace_id, folder, name), folder, content))

    new_content = _render_assembly(program, set(modules), replaced_keys, call_globals, decl_params)

    # 等价校验：编译前后 nodes 逐节点比较（原设计独立编译；新装配用内存
    # resolver 解析尚未落库的 part 规格文本，file_id 用稳定伪 id 占位）
    before = compile_design(design.content)

    part_index = {
        key: content for key, (_title, _folder, content) in zip(replaced_keys.values(), part_specs, strict=True)
    }

    def _memory_resolver(key: str) -> Any:
        from cndb.plugins.design.services.dsl.nodes import FileSource

        content = part_index.get(key)
        if content is None:
            return None
        return FileSource(
            file_id=10_000 + sorted(part_index).index(key),
            file_key=key,
            kind="part",
            content=content,
            version_number=1,
            content_hash=_hash_text(content),
        )

    after = compile_design(new_content, file_kind="assembly", file_id=design.id, resolver=_memory_resolver)
    if not before.ok or not after.ok:
        entry.error = "编译失败: " + "；".join(
            d.message for d in (after.diagnostics if not after.ok else before.diagnostics)
        )
        return entry
    assert before.ir is not None and after.ir is not None
    if not nodes_equal(before.ir.get("nodes", []), after.ir.get("nodes", [])):
        entry.error = "重构前后几何不等价，已保留原文"
        return entry

    entry.parts = list(replaced_keys.values())
    if dry_run:
        entry.reason = "dry-run（未写库）"
        return entry

    # ── 落库（调用方事务）：part 文件 + 装配新版本 ──
    for key, (title, folder, content) in zip(replaced_keys.values(), part_specs, strict=True):
        part_result = compile_design(content, file_kind="part", resolver=_memory_resolver)
        assert part_result.ok and part_result.ir is not None, "part 文件必须可独立编译"
        part = DesignDesign(
            workspace_id=design.workspace_id,
            title=title,
            kind="part",
            folder=folder,
            file_key=key,
            content=content,
            compiled=part_result.ir,
            description=f"自 {design.title} 重构拆分",
            created_by_id=design.updated_by_id,
            updated_by_id=design.updated_by_id,
        )
        db.add(part)
        db.flush()
        db.add(_version_row(design, part, content, part_result.ir))
    # 以真实 file_id 重新编译装配（part 行已落库，走工作区 resolver）
    final = compile_design(
        new_content,
        file_kind="assembly",
        file_id=design.id,
        resolver=build_resolver(db, design.workspace_id),
    )
    assert final.ok and final.ir is not None, "等价校验已通过，最终编译不应失败"
    design.content = new_content
    design.compiled = final.ir
    design.dependencies = [
        {
            "file_id": d.file_id,
            "file_key": d.file_key,
            "version_number": d.version_number,
            "content_hash": d.content_hash,
        }
        for d in final.dependencies
    ]
    design.refactored_from_version = latest_version_number(db, design.id)
    sync_refs(db, design, list(replaced_keys.values()))
    # 规则 6：成功写新版本（原版本保留）
    from cndb.plugins.design.models import DesignDesignVersion

    number = (design.refactored_from_version or 0) + 1
    db.add(
        DesignDesignVersion(
            design_id=design.id,
            workspace_id=design.workspace_id,
            version_number=number,
            content=new_content,
            compiled=final.ir,
            dependencies=list(design.dependencies),
            comment="重构：拆分零件文件",
            created_by_id=design.updated_by_id,
        )
    )
    entry.version_number = number
    return entry


def _version_row(design: DesignDesign, part: DesignDesign, content: str, ir: dict[str, Any]) -> Any:
    from cndb.plugins.design.models import DesignDesignVersion

    return DesignDesignVersion(
        design_id=part.id,
        workspace_id=design.workspace_id,
        version_number=1,
        content=content,
        compiled=ir,
        comment=f"自 {design.title} 重构拆分",
        created_by_id=design.updated_by_id,
    )


def run_refactor(
    db: Session,
    *,
    workspace_id: int | None = None,
    dry_run: bool = False,
) -> RefactorReport:
    """批量重构（逐设计事务，失败不阻断其它设计，ADR §6 规则 6）."""

    report = RefactorReport(dry_run=dry_run)
    query = db.query(DesignDesign).filter(
        DesignDesign.is_deleted.is_(False),
        DesignDesign.kind == "assembly",
    )
    if workspace_id is not None:
        query = query.filter(DesignDesign.workspace_id == workspace_id)
    for design in query.order_by(DesignDesign.id).all():
        entry = refactor_design(db, design, dry_run=dry_run)
        if entry.error:
            db.rollback()
            report.failed.append(entry)
        elif entry.reason and not entry.parts:
            report.skipped.append(entry)
        else:
            if not dry_run:
                db.commit()
            report.refactored.append(entry)
    return report


__all__ = [
    "RefactorEntry",
    "RefactorReport",
    "nodes_equal",
    "refactor_design",
    "run_refactor",
]
