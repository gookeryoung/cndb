"""调度声明与到期判定（纯函数，便于单测与 CLI 复用）.

支持的调度形态（``datasource_sync_job.schedule`` JSON）：

- ``manual``   只由手动接口 / CLI 触发
- ``daily``    ``{"mode":"daily","at":"17:10"}`` 每天该时刻之后触发一次
- ``interval`` ``{"mode":"interval","seconds":3600}`` 距上次运行满 N 秒触发
- ``cron``     ``{"mode":"cron","expr":"0 6 * * *"}`` 标准 5 段表达式，分钟级匹配

时区：``tz_offset_minutes`` 默认 480（UTC+8），避免依赖服务器本地时区；
落库时间一律 aware UTC，比较前统一换算到该偏移。

退避：``last_status == "failed"`` 时，距上次运行不足 ``retry_backoff_seconds``
不再重试，避免故障源被每分钟打一次（ADR 0006 D3）。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from cndb.plugins.datasource.models import ScheduleMode
from cndb.plugins.datasource.providers.base import ProviderError

DEFAULT_RETRY_BACKOFF_SECONDS = 300
DEFAULT_TZ_OFFSET_MINUTES = 480


@dataclass(frozen=True, slots=True)
class ScheduleConfig:
    """调度配置（持久化为 ``datasource_sync_job.schedule``）."""

    mode: ScheduleMode = ScheduleMode.MANUAL
    at: str = ""
    seconds: int = 0
    expr: str = ""
    tz_offset_minutes: int = DEFAULT_TZ_OFFSET_MINUTES
    retry_backoff_seconds: int = DEFAULT_RETRY_BACKOFF_SECONDS

    def __post_init__(self) -> None:
        if self.mode is ScheduleMode.DAILY:
            _parse_hhmm(self.at)
        if self.mode is ScheduleMode.INTERVAL and self.seconds < 1:
            raise ProviderError("interval 调度的 seconds 必须 >= 1")
        if self.mode is ScheduleMode.CRON:
            parse_cron(self.expr)
        if self.retry_backoff_seconds < 0:
            raise ProviderError("retry_backoff_seconds 不能为负")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": str(self.mode),
            "at": self.at,
            "seconds": self.seconds,
            "expr": self.expr,
            "tz_offset_minutes": self.tz_offset_minutes,
            "retry_backoff_seconds": self.retry_backoff_seconds,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> ScheduleConfig:
        if not data:
            return cls()
        raw_mode = str(data.get("mode") or "manual")
        try:
            mode = ScheduleMode(raw_mode)
        except ValueError as exc:
            raise ProviderError(f"未知调度模式: {raw_mode}") from exc
        tz_raw = data.get("tz_offset_minutes")
        backoff_raw = data.get("retry_backoff_seconds")
        return cls(
            mode=mode,
            at=str(data.get("at") or ""),
            seconds=int(data.get("seconds") or 0),
            expr=str(data.get("expr") or ""),
            tz_offset_minutes=DEFAULT_TZ_OFFSET_MINUTES if tz_raw is None else int(tz_raw),
            retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS if backoff_raw is None else int(backoff_raw),
        )


def is_due(
    config: ScheduleConfig,
    *,
    now: dt.datetime,
    last_run_at: dt.datetime | None,
    last_status: str = "",
) -> bool:
    """判定该 job 当前是否到期（不含租约判定，租约在 scheduler 里做）."""
    current = _as_utc(now)
    previous = _as_utc(last_run_at) if last_run_at is not None else None

    if (
        previous is not None
        and last_status == "failed"
        and (current - previous).total_seconds() < config.retry_backoff_seconds
    ):
        return False

    match config.mode:
        case ScheduleMode.MANUAL:
            return False
        case ScheduleMode.INTERVAL:
            return previous is None or (current - previous).total_seconds() >= config.seconds
        case ScheduleMode.DAILY:
            hour, minute = _parse_hhmm(config.at)
            local_now = _to_offset(current, config.tz_offset_minutes)
            today_at = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if local_now < today_at:
                return False
            if previous is None:
                return True
            return _to_offset(previous, config.tz_offset_minutes) < today_at
        case ScheduleMode.CRON:
            slot = current.replace(second=0, microsecond=0)
            if not cron_matches(config.expr, _to_offset(slot, config.tz_offset_minutes)):
                return False
            return previous is None or _as_utc(previous) < slot
    return False  # pragma: no cover - 枚举已穷举


def cron_matches(expr: str, moment: dt.datetime) -> bool:
    """判断 ``moment`` 是否命中 5 段 cron 表达式（分钟级）."""
    minute, hour, dom, month, dow = parse_cron(expr)
    return (
        _match_field(minute, moment.minute)
        and _match_field(hour, moment.hour)
        and _match_field(dom, moment.day)
        and _match_field(month, moment.month)
        and _match_field(dow, moment.isoweekday() % 7)
    )


def parse_cron(expr: str) -> tuple[str, str, str, str, str]:
    """校验并拆分 cron 表达式为 ``(minute, hour, dom, month, dow)``."""
    parts = expr.split()
    if len(parts) != 5:
        raise ProviderError(f"cron 表达式必须是 5 段（分 时 日 月 周）: {expr!r}")
    ranges = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
    for part, (low, high) in zip(parts, ranges, strict=True):
        _validate_field(part, low, high, expr)
    return cast("tuple[str, str, str, str, str]", tuple(parts))


def _validate_field(part: str, low: int, high: int, expr: str) -> None:
    for item in part.split(","):
        if item == "*":
            continue
        if item.startswith("*/"):
            _check_int(item[2:], 1, high, expr)
            continue
        if "-" in item:
            start, _, end = item.partition("-")
            begin = _check_int(start, low, high, expr)
            finish = _check_int(end, low, high, expr)
            if begin > finish:
                raise ProviderError(f"cron 区间反向: {item!r}（{expr!r}）")
            continue
        _check_int(item, low, high, expr)


def _check_int(text: str, low: int, high: int, expr: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise ProviderError(f"cron 字段无法解析: {text!r}（{expr!r}）") from exc
    if not low <= value <= high:
        raise ProviderError(f"cron 字段超出范围 {low}-{high}: {text!r}（{expr!r}）")
    return value


def _match_field(part: str, value: int) -> bool:
    for item in part.split(","):
        if item == "*":
            return True
        if item.startswith("*/"):
            step = int(item[2:])
            if step > 0 and value % step == 0:
                return True
            continue
        if "-" in item:
            start, _, end = item.partition("-")
            if int(start) <= value <= int(end):
                return True
            continue
        if int(item) == value:
            return True
    return False


def _parse_hhmm(text: str) -> tuple[int, int]:
    hour_text, _, minute_text = text.partition(":")
    try:
        hour, minute = int(hour_text), int(minute_text)
    except ValueError as exc:
        raise ProviderError(f"时刻必须是 HH:MM: {text!r}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ProviderError(f"时刻超出范围: {text!r}")
    return hour, minute


def _as_utc(value: dt.datetime) -> dt.datetime:
    """naive 视为 UTC（SQLite 读回可能丢失 tzinfo）."""
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def _to_offset(value: dt.datetime, offset_minutes: int) -> dt.datetime:
    return _as_utc(value).astimezone(dt.timezone(dt.timedelta(minutes=offset_minutes)))


__all__ = [
    "DEFAULT_RETRY_BACKOFF_SECONDS",
    "DEFAULT_TZ_OFFSET_MINUTES",
    "ScheduleConfig",
    "cron_matches",
    "is_due",
    "parse_cron",
]
