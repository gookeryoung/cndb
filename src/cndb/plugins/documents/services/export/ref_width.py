"""文档引用显示宽度（ADR 0051）.

图表 / 数据表引用可带 ``width=<百分比>``：25–100 整数，缺省 / 非法 / 越界回退 75。
本模块是后端宽度常量与解析的唯一入口，与前端 ``refWidth.ts`` 保持同口径。
"""

from __future__ import annotations

DEFAULT_REF_WIDTH = 75
MIN_REF_WIDTH = 25
MAX_REF_WIDTH = 100


def parse_ref_width(value: str | None) -> int:
    """解析宽度参数：缺省 / 非整数 / 越界 → 75."""
    if value is None or value == "":
        return DEFAULT_REF_WIDTH
    try:
        width = int(value)
    except (TypeError, ValueError):
        return DEFAULT_REF_WIDTH
    if width < MIN_REF_WIDTH or width > MAX_REF_WIDTH:
        return DEFAULT_REF_WIDTH
    return width


__all__ = ["DEFAULT_REF_WIDTH", "MAX_REF_WIDTH", "MIN_REF_WIDTH", "parse_ref_width"]
