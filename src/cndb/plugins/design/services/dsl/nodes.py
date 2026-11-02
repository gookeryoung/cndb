"""结构 DSL 的 AST 节点、诊断与编译结果（ADR 0079 D2）.

节点只承载语法结构与出错位置（1 基行 / 列），语义求值与 IR 构造在
``compile.py``；表达式在解析期不求值（参数覆盖需在编译期重算，I3）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ── 表达式 ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Num:
    """数值字面量."""

    value: float
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class Name:
    """标识符引用（param 名或常量 PI）."""

    name: str
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class BinOp:
    """二元运算：+ - * / %."""

    op: str
    left: Expr
    right: Expr
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class UnaryOp:
    """一元负号."""

    op: str
    operand: Expr
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class FuncCall:
    """白名单函数调用（sin / sqrt / min ...）."""

    name: str
    args: tuple[Expr, ...]
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class Vector:
    """三维向量字面量 ``[x, y, z]``：仅图元 ``size`` 参数可求值为向量."""

    items: tuple[Expr, Expr, Expr]
    line: int
    col: int


Expr = Num | Name | BinOp | UnaryOp | FuncCall | Vector


# ── 实例（产出几何的语句） ────────────────────────────────


@dataclass(frozen=True, slots=True)
class PrimitiveCall:
    """图元调用：六种之一，仅命名参数."""

    name: str
    args: dict[str, Expr]
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class TransformCall:
    """变换包裹：translate / rotate / scale / mirror，作用于块或单实例."""

    kind: str
    vector: tuple[Expr, Expr, Expr]
    children: tuple[Instance, ...]
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class BooleanCall:
    """布尔块：union / difference / intersection."""

    kind: str
    children: tuple[Instance, ...]
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class ModuleCall:
    """模块实例化：位置参数 + 命名参数（可混用，命名须在位置之后）."""

    name: str
    positional: tuple[Expr, ...]
    named: dict[str, Expr]
    line: int
    col: int
    #: ``as`` 实例标签（ADR 0086 D4：约束引用端；同作用域唯一）
    label: str | None = None


@dataclass(frozen=True, slots=True)
class UseCall:
    """分文件零件引用：``use "file_key"(参数...) as 标签``（ADR 0086 D2）."""

    file_key: str
    positional: tuple[Expr, ...]
    named: dict[str, Expr]
    line: int
    col: int
    label: str | None = None


Instance = PrimitiveCall | TransformCall | BooleanCall | ModuleCall | UseCall


# ── 顶层声明 ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ModuleParam:
    """模块形参：可带默认值表达式."""

    name: str
    default: Expr | None


@dataclass(frozen=True, slots=True)
class ModuleDecl:
    """模块声明：名 + 形参表 + 实例体."""

    name: str
    params: tuple[ModuleParam, ...]
    body: tuple[Instance, ...]
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class ParamDecl:
    """顶层参数声明：param name = expr."""

    name: str
    value: Expr
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class ConstraintRef:
    """约束引用端：``实例标签.基准``（ADR 0086 D4；基准 origin / x / y / z）."""

    label: str
    anchor: str
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class ConstraintDecl:
    """装配约束声明：``constraint <id> <type>(a = …, b = …)``（ADR 0086 D4/D5）.

    ``refs`` 承载实例引用（a / b），``values`` 承载数值参数（offset / value）；
    MVP 类型 fixed / coincident / concentric / distance / angle。
    """

    id: str
    kind: str
    refs: dict[str, ConstraintRef]
    values: dict[str, Expr]
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class SystemDecl:
    """系统装配声明（ADR 0084 D1/D3）：顶层根、无参数表、不可实例化.

    系统是纯组织层——把 ``body`` 平铺到顶层后几何与参数完全一致（I2）；
    ADR 0086 起体内可声明装配约束（作用域 = 该系统）。
    """

    name: str
    body: tuple[Instance | ConstraintDecl, ...]
    line: int
    col: int


#: 顶层语句（保持原文出现顺序：几何按此顺序展开，ADR 0084 §2）
ProgramItem = ParamDecl | ModuleDecl | SystemDecl | ConstraintDecl | Instance


@dataclass(frozen=True, slots=True)
class Program:
    """编译单元：顶层 param / module / system 声明与顶层实例."""

    params: tuple[ParamDecl, ...]
    modules: tuple[ModuleDecl, ...]
    instances: tuple[Instance, ...]
    systems: tuple[SystemDecl, ...] = ()
    #: 顶层约束声明（ADR 0086 D4，作用于顶层实例标签作用域）
    constraints: tuple[ConstraintDecl, ...] = ()
    #: 顶层语句的原文顺序（编译按此交错展开，I2）；为空表示仅按分类元组展开
    items: tuple[ProgramItem, ...] = ()


# ── 诊断与编译结果 ────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """结构化诊断：行 / 列定位 + 中文消息."""

    severity: str
    line: int
    col: int
    message: str


@dataclass(frozen=True, slots=True)
class FileSource:
    """跨文件编译的输入快照（ADR 0086 §2）：一个设计文件的内容 + 身份."""

    file_id: int
    file_key: str
    kind: str  # part / assembly
    content: str
    version_number: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class DependencySnapshot:
    """依赖闭包项：装配版本保存时用于可复现编译（ADR 0086 D6）."""

    file_id: int
    file_key: str
    version_number: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class CompileResult:
    """编译结果：ok 时 ir 非空，失败时只有诊断（不产出半截 IR，I6）.

    ``diagnostics`` 既含 error 也含 warning（欠约束等）；只有 error 时 ``ok``
    为 False。``dependencies`` 为本次编译实际用到的引用闭包（不含根文件）。
    """

    ok: bool
    ir: dict[str, Any] | None
    diagnostics: tuple[Diagnostic, ...] = ()
    dependencies: tuple[DependencySnapshot, ...] = ()


__all__ = [
    "BinOp",
    "BooleanCall",
    "CompileResult",
    "ConstraintDecl",
    "ConstraintRef",
    "DependencySnapshot",
    "Diagnostic",
    "Expr",
    "FileSource",
    "FuncCall",
    "Instance",
    "ModuleCall",
    "ModuleDecl",
    "ModuleParam",
    "Name",
    "Num",
    "ParamDecl",
    "PrimitiveCall",
    "Program",
    "ProgramItem",
    "SystemDecl",
    "TransformCall",
    "UnaryOp",
    "UseCall",
    "Vector",
]
