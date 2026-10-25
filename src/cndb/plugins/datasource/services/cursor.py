"""增量游标 —— 五种策略统一在这里推进（ADR 0006 D4；backfill_date 见 ADR 0034 D2）.

| 策略 | 语义 | 游标推进 |
|---|---|---|
| ``date`` | 按日期字段增量，首跑回填 ``backfill_start`` | 取本轮最大日期 |
| ``datetime`` | 按时间戳增量 | 取本轮最大时刻 |
| ``key_set`` | 无稳定时序（榜单 / RSS），靠幂等键去重 | 不推进 |
| ``none`` | 每次全量覆盖（快照类） | 不推进 |
| ``backfill_date`` | 按标的回补水位（历史回补，end 锚点逐轮前推） | 每标的取本轮**最早**日期，存 ``datasource_entrant_cursor`` |

两条边界（I3）：
- **无新数据不推进**：本轮没有可比字段值时保留原游标，与「同步失败」区分开；
- **只前进不后退**：源侧乱序返回旧数据时，游标取 ``max(原值, 本轮最大值)``；
  ``backfill_date`` 对称地**只向更早前移**（``min(原值, 本轮最早值)``）。

``backfill_date`` 的水位读写（DB）在 ``services/entrant_state.py``，本模块只做纯函数判定。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from cndb.plugins.datasource.providers.base import CursorStrategy, ProviderError
from cndb.plugins.datasource.services.normalize import coerce_value

_WINDOWED: frozenset[CursorStrategy] = frozenset({"date", "datetime"})
_STRATEGIES: frozenset[str] = frozenset({"date", "datetime", "key_set", "none", "backfill_date"})


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
        if self.strategy == "backfill_date" and not self.field:
            raise ProviderError("游标策略 backfill_date 必须指定日期字段 field")
        if self.strategy == "backfill_date" and not self.backfill_start:
            raise ProviderError("游标策略 backfill_date 必须指定回补起点 backfill_start")
        if self.strategy not in _STRATEGIES:
            raise ProviderError(f"未知游标策略: {self.strategy}")

    @property
    def is_windowed(self) -> bool:
        """是否需要按时间区间请求（date / datetime）."""
        return self.strategy in _WINDOWED

    @property
    def is_backfill(self) -> bool:
        """是否为按标的回补水位（backfill_date）."""
        return self.strategy == "backfill_date"

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
        if strategy not in _STRATEGIES:
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

    非窗口策略返回 ``None``（不注入时间参数）；``backfill_date`` 的请求锚点
    由 :func:`backfill_anchor` 按标的给出，不走本函数。
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
    kind = "date" if strategy in ("date", "backfill_date") else "datetime"
    best: str | None = None
    for row in rows:
        value, reason = coerce_value(row.get(field), kind)
        if reason is not None or value is None:
            continue
        text = str(value)
        if best is None or text > best:
            best = text
    return best


def min_field_value(rows: Sequence[Mapping[str, Any]], field: str) -> str | None:
    """取 ``field`` 的归一最早日期（``YYYY-MM-DD``；backfill_date 水位推进用）."""
    best: str | None = None
    for row in rows:
        value, reason = coerce_value(row.get(field), "date")
        if reason is not None or value is None:
            continue
        text = str(value)
        if best is None or text < best:
            best = text
    return best


def backfill_anchor(
    watermark: str | None,
    *,
    backfill_start: str,
    today: str,
) -> str | None:
    """按标的回补的请求 end 锚点：``watermark − 1 天``；已达回补起点返回 ``None``（跳过）.

    无水位（首轮）锚点为 ``today``（拉最近一段，含当日）；水位只表达「已补到的
    最早日期」，下一批的终点是它前一天。
    """
    anchor = _previous_day(watermark) if watermark else today
    if anchor < backfill_start:
        return None
    return anchor


def backfill_advance(
    watermark: str | None,
    rows: Sequence[Mapping[str, Any]],
    *,
    field: str,
    backfill_start: str,
) -> str | None:
    """按标的推进回补水位：本轮最早日期向 ``backfill_start`` 截断，只前移不后退.

    空响应 / 无可比日期 → 原样返回（不推进）；已到 ``backfill_start`` 的标的
    由 :func:`backfill_anchor` 判跳过，本函数返回值不会晚于 ``backfill_start``。
    """
    candidate = min_field_value(rows, field)
    if candidate is None:
        return watermark
    floor = max(candidate, backfill_start) if candidate < backfill_start else candidate
    if watermark is not None and floor >= watermark:
        # 只向更早前移：本轮最早日期不比现水位早就保留原值
        return watermark
    return floor


def _previous_day(value: str) -> str:
    """ISO 日期串减一天；非法日期抛 ProviderError（水位由本模块写入，格式理应可控）."""
    try:
        day = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ProviderError(f"回补水位必须是 ISO 日期（YYYY-MM-DD）: {value!r}") from exc
    return (day - dt.timedelta(days=1)).isoformat()


__all__ = [
    "CursorConfig",
    "advance",
    "backfill_advance",
    "backfill_anchor",
    "max_field_value",
    "min_field_value",
    "window_start",
]
