"""结构 DSL（.cnmd）编译：词法 / 语法 / 求值 → IR 快照（ADR 0079 D2/D3）.

唯一编译入口：``compile.py::compile_design``；调用方（保存端点 / 预览端点）
不得绕过该入口自行解析或求值（I1）。
"""

from __future__ import annotations

from cndb.plugins.design.services.dsl.compile import CompileResult, Diagnostic, compile_design
from cndb.plugins.design.services.dsl.nodes import (
    Program,
)

__all__ = [
    "CompileResult",
    "Diagnostic",
    "Program",
    "compile_design",
]
