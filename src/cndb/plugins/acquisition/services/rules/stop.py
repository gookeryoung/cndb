"""轮次停止判定（ADR 0085 §2 / D6）.

四重条件取**最先触发**者（优先级即判定顺序）：

1. ``budget``       预算触顶（请求 / 行数 / 模型调用任一）—— 先停，避免跑飞；
2. ``max_rounds``   达到用户声明轮数上限；
3. ``empty_round``  连续 ``stop.empty_rounds`` 轮无新增（默认 1 轮，对齐 endo 的提前终止）；
4. ``min_new``      本轮新增低于 ``stop.min_new_items``（默认 1）。

零新增属正常收敛，不是失败（ADR §8）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["decide_stop"]

STOP_BUDGET = "budget"
STOP_MAX_ROUNDS = "max_rounds"
STOP_EMPTY_ROUND = "empty_round"
STOP_MIN_NEW = "min_new"


def _as_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def decide_stop(
    *,
    round_no: int,
    max_rounds: int,
    new_items: int,
    stop_config: Mapping[str, Any] | None = None,
    consecutive_empty: int = 0,
    budget_exhausted: bool = False,
) -> str | None:
    """返回停止原因；``None`` 表示可以继续下一轮."""
    config = dict(stop_config or {})
    if budget_exhausted:
        return STOP_BUDGET
    if round_no >= max(1, max_rounds):
        return STOP_MAX_ROUNDS
    empty_rounds = _as_int(config.get("empty_rounds"), 1)
    if new_items == 0 and consecutive_empty >= max(1, empty_rounds):
        return STOP_EMPTY_ROUND
    if new_items < _as_int(config.get("min_new_items"), 1):
        return STOP_MIN_NEW
    return None
