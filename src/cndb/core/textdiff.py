"""纯文本 diff 工具：unified diff 唯一入口（ADR 0057 I1 / ADR 0113 D6）.

documents 与 design 插件共用，避免插件间反向依赖，前端统一解析 ``difflib`` 输出。
"""

from __future__ import annotations

import difflib

__all__ = ["unified_diff"]


def unified_diff(base: str, head: str, context_lines: int = 3) -> tuple[str, int, int]:
    """计算两版本 unified diff.

    Returns:
        (diff 文本, 新增行数, 删除行数)
    """
    base_lines = base.splitlines(keepends=True)
    head_lines = head.splitlines(keepends=True)
    diff_gen = difflib.unified_diff(base_lines, head_lines, fromfile="base", tofile="head", n=context_lines)
    diff_text = "".join(diff_gen)
    added = sum(1 for ln in diff_text.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff_text.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    return diff_text, added, removed
