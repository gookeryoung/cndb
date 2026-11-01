"""结构 DSL 编译期限制（ADR 0079 D10 / I6）.

所有上限在编译期（保存 / 预览）判定，超限报诊断、不产出半截 IR。
"""

from __future__ import annotations

#: DSL 原文上限（字节）
MAX_CONTENT_BYTES: int = 256 * 1024
#: 实例嵌套深度上限（布尔 / 变换 / 模块体块级，含变换包裹）
MAX_NESTING_DEPTH: int = 32
#: 单份设计图元实例总数上限（模块展开后累计）
MAX_PRIMITIVES: int = 2000
#: 顶层 param 数量上限
MAX_PARAMS: int = 64
#: 顶层 module 数量上限
MAX_MODULES: int = 128
#: 模块实例化递归深度上限
MAX_MODULE_RECURSION: int = 16
#: 图元 fn（圆周分段数）缺省值与取值范围
DEFAULT_FN: int = 64
MIN_FN: int = 3
MAX_FN: int = 256

__all__ = [
    "DEFAULT_FN",
    "MAX_CONTENT_BYTES",
    "MAX_FN",
    "MAX_MODULES",
    "MAX_MODULE_RECURSION",
    "MAX_NESTING_DEPTH",
    "MAX_PARAMS",
    "MAX_PRIMITIVES",
    "MIN_FN",
]
