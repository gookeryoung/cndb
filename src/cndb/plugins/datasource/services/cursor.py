"""增量游标 —— 四种策略统一在这里推进（ADR 0006 D4）.

| 策略 | 语义 | 游标推进 |
|---|---|---|
| ``date`` | 按日期字段增量，首跑回填 ``backfill_start`` | 取本轮最大日期 |
| ``datetime`` | 按时间戳增量 | 取本轮最大时刻 |
| ``key_set`` | 无稳定时序（榜单 / RSS），靠幂等键去重 | 不推进 |
| ``none`` | 每次全量覆盖（快照类） | 不推进 |

两条边界（I3）：
- **无新数据不推进**：本轮没有可比字段值时保留原游标，与「同步失败」区分开；
- **只前进不后退**：源侧乱序返回旧数据时，游标取 ``max(原值, 本轮最大值)``。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from cndb.plugins.datasource.providers.base import CursorStrategy, ProviderError
from cndb.plugins.datasource.services.normalize import coerce_value

_WINDOWED: frozenset[CursorStrategy] = frozenset({"date", "datetime"})


@dataclass(frozen=True, slots=True)
class CursorConfig:
    """游标配置（持久化为 ``datasource_sync_job.cursor``）."""

    strategy: CursorStrategy = "date"
    field: str = ""
    backfill_start: str = ""
    value: str | None = None

    def __post_init__(self) -> None:
        if self.strategy in _WINDOWED and not self.field:
            raise ProviderError(f"游标策略 {self.strategy} 必须指定增量字段 field")
        if self.strategy not in ("date", "datetime", "key_set", "none"):
            raise ProviderError(f"未知游标策略: {self.strategy}")

    @property
    def is_windowed(self) -> bool:
        """是否需要按时间区间请求（date / datetime）."""
        return self.strategy in _WINDOWED

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "field": self.field,
            "backfill_start": self.backfill_start,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> CursorConfig:
        """从 job 的 JSON 列还原；缺省按 ``none``（不猜增量语义）."""
        if not data:
            return cls(strategy="none")
        strategy = str(data.get("strategy") or "none")
        if strategy not in ("date", "datetime", "key_set", "none"):
            raise ProviderError(f"未知游标策略: {strategy}")
        raw_value = data.get("value")
        return cls(
            strategy=cast("CursorStrategy", strategy),
            field=str(data.get("field") or ""),
            backfill_start=str(data.get("backfill_start") or ""),
            value=str(raw_value) if raw_value else None,
        )


def window_start(config: CursorConfig, *, today: str) -> str | None:
    """本轮抓取区间的起点：``value`` → ``backfill_start`` → ``today``.

    非窗口策略返回 ``None``（不注入时间参数）。
    """
    if not config.is_windowed:
        return None
    return config.value or config.backfill_start or today


def advance(config: CursorConfig, rows: Sequence[Mapping[str, Any]]) -> str | None:
    """根据本轮数据推进游标；无新数据或非窗口策略时原样返回."""
    if not config.is_windowed:
        return config.value
    candidate = max_field_value(rows, config.field, config.strategy)
    if candidate is None:
        return config.value
    if config.value is None or candidate > config.value:
        return candidate
    return config.value


def max_field_value(
    rows: Sequence[Mapping[str, Any]],
    field: str,
    strategy: CursorStrategy,
) -> str | None:
    """取 ``field`` 的归一最大值（date → ``YYYY-MM-DD``，datetime → ``YYYY-MM-DD HH:MM:SS``）."""
    kind = "date" if strategy == "date" else "datetime"
    best: str | None = None
    for row in rows:
        value, reason = coerce_value(row.get(field), kind)
        if reason is not None or value is None:
            continue
        text = str(value)
        if best is None or text > best:
            best = text
    return best


__all__ = ["CursorConfig", "advance", "max_field_value", "window_start"]
