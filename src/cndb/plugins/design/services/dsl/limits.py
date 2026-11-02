"""结构 DSL 编译期限制（ADR 0079 D10 / ADR 0086 D9）.

所有上限在编译期（保存 / 预览）判定，超限报诊断、不产出半截 IR；
ADR 0086 起按依赖闭包累计（拆文件不得放大总预算）。
"""

from __future__ import annotations

#: 单文件原文上限（字节）
MAX_CONTENT_BYTES: int = 256 * 1024
#: 实例嵌套深度上限（单个文件；布尔 / 变换 / 模块体块级，含变换包裹）
MAX_NESTING_DEPTH: int = 32

#: 顶层 param 数量上限（单文件）
MAX_PARAMS: int = 64
#: 顶层 module 数量上限（单个文件）
MAX_MODULES: int = 128
#: 模块实例化递归深度上限（单文件；跨文件递归另见 MAX_REF_DEPTH）
MAX_MODULE_RECURSION: int = 16
#: 依赖闭包：引用文件总数上限（含根文件，ADR 0086 D9）
MAX_CLOSURE_FILES: int = 64
#: 依赖闭包：累计原文上限（字节，含根文件，ADR 0086 D9）
MAX_CLOSURE_BYTES: int = 1024 * 1024
#: 依赖闭包：跨文件引用深度上限（根文件为 0，ADR 0086 D9）
MAX_REF_DEPTH: int = 8
#: 单文件 module / system 声明累计上限与闭包上限（ADR 0086 D9）
MAX_CLOSURE_MODULES: int = 256
#: 单文件图元（叶子节点）数量上限（按依赖闭包累计，ADR 0086 D9）
MAX_PRIMITIVES: int = 2000
#: 图元 fn（圆周分段数）缺省值与取值范围（固定，不随闭包放宽）
DEFAULT_FN: int = 64
MIN_FN: int = 3
MAX_FN: int = 256

__all__ = [
    "DEFAULT_FN",
    "MAX_CLOSURE_BYTES",
    "MAX_CLOSURE_FILES",
    "MAX_CLOSURE_MODULES",
    "MAX_CONTENT_BYTES",
    "MAX_FN",
    "MAX_MODULES",
    "MAX_MODULE_RECURSION",
    "MAX_NESTING_DEPTH",
    "MAX_PARAMS",
    "MAX_PRIMITIVES",
    "MAX_REF_DEPTH",
    "MIN_FN",
]
