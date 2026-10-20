"""datasource M2：调度声明解析与到期判定单测."""

from __future__ import annotations

import datetime as dt

import pytest

from cndb.plugins.datasource.models import ScheduleMode
from cndb.plugins.datasource.providers.base import ProviderError
from cndb.plugins.datasource.services.schedule import (
    ScheduleConfig,
    cron_matches,
    is_due,
    parse_cron,
)

UTC = dt.UTC


def _utc(*args: int) -> dt.datetime:
    return dt.datetime(*args, tzinfo=UTC)


class TestScheduleConfig:
    def test_defaults_to_manual(self):
        config = ScheduleConfig.from_dict(None)
        assert config.mode is ScheduleMode.MANUAL
        assert config.tz_offset_minutes == 480

    def test_daily_requires_valid_hhmm(self):
        with pytest.raises(ProviderError, match="HH:MM"):
            ScheduleConfig(mode=ScheduleMode.DAILY, at="17点")
        with pytest.raises(ProviderError, match="超出范围"):
            ScheduleConfig(mode=ScheduleMode.DAILY, at="24:00")

    def test_interval_requires_positive_seconds(self):
        with pytest.raises(ProviderError, match="seconds"):
            ScheduleConfig(mode=ScheduleMode.INTERVAL, seconds=0)

    def test_cron_validated_eagerly(self):
        with pytest.raises(ProviderError, match="5 段"):
            ScheduleConfig(mode=ScheduleMode.CRON, expr="* * *")

    def test_negative_backoff_rejected(self):
        with pytest.raises(ProviderError, match="不能为负"):
            ScheduleConfig(mode=ScheduleMode.DAILY, at="08:00", retry_backoff_seconds=-1)

    def test_unknown_mode_rejected(self):
        with pytest.raises(ProviderError, match="未知调度模式"):
            ScheduleConfig.from_dict({"mode": "hourly"})

    def test_roundtrip(self):
        config = ScheduleConfig.from_dict({"mode": "daily", "at": "17:10", "tz_offset_minutes": 0})
        assert config.to_dict()["mode"] == "daily"
        assert config.at == "17:10"
        assert config.tz_offset_minutes == 0


class TestIsDue:
    def test_manual_never_due(self):
        assert is_due(ScheduleConfig(), now=_utc(2024, 7, 1, 9, 0), last_run_at=None) is False

    def test_interval_first_run(self):
        config = ScheduleConfig(mode=ScheduleMode.INTERVAL, seconds=60)
        assert is_due(config, now=_utc(2024, 7, 1, 9, 0), last_run_at=None) is True

    def test_interval_not_yet(self):
        config = ScheduleConfig(mode=ScheduleMode.INTERVAL, seconds=60)
        now = _utc(2024, 7, 1, 9, 0)
        assert is_due(config, now=now, last_run_at=now - dt.timedelta(seconds=30)) is False
        assert is_due(config, now=now, last_run_at=now - dt.timedelta(seconds=61)) is True

    def test_daily_before_time(self):
        config = ScheduleConfig(mode=ScheduleMode.DAILY, at="17:10", tz_offset_minutes=480)
        # UTC 09:00 = 本地 17:00，未到 17:10
        assert is_due(config, now=_utc(2024, 7, 1, 9, 0), last_run_at=None) is False

    def test_daily_after_time(self):
        config = ScheduleConfig(mode=ScheduleMode.DAILY, at="17:10", tz_offset_minutes=480)
        # UTC 09:10 = 本地 17:10
        assert is_due(config, now=_utc(2024, 7, 1, 9, 10), last_run_at=None) is True

    def test_daily_already_ran_today(self):
        config = ScheduleConfig(mode=ScheduleMode.DAILY, at="17:10", tz_offset_minutes=480)
        # 本地今天 18:00 跑过（UTC 10:00），UTC 11:00 再判 → 不重复
        assert is_due(config, now=_utc(2024, 7, 1, 11, 0), last_run_at=_utc(2024, 7, 1, 10, 0)) is False

    def test_daily_ran_yesterday(self):
        config = ScheduleConfig(mode=ScheduleMode.DAILY, at="17:10", tz_offset_minutes=480)
        assert is_due(config, now=_utc(2024, 7, 2, 9, 30), last_run_at=_utc(2024, 7, 1, 10, 0)) is True

    def test_naive_last_run_treated_as_utc(self):
        config = ScheduleConfig(mode=ScheduleMode.INTERVAL, seconds=60)
        now = _utc(2024, 7, 1, 9, 0)
        assert is_due(config, now=now, last_run_at=dt.datetime(2024, 7, 1, 8, 59)) is True

    def test_cron_matches_minute(self):
        config = ScheduleConfig(mode=ScheduleMode.CRON, expr="0 6 * * *", tz_offset_minutes=0)
        assert is_due(config, now=_utc(2024, 7, 1, 6, 0), last_run_at=None) is True

    def test_cron_same_minute_not_repeated(self):
        config = ScheduleConfig(mode=ScheduleMode.CRON, expr="0 6 * * *", tz_offset_minutes=0)
        slot = _utc(2024, 7, 1, 6, 0)
        assert is_due(config, now=slot, last_run_at=slot) is False

    def test_retry_backoff_after_failure(self):
        config = ScheduleConfig(mode=ScheduleMode.INTERVAL, seconds=1, retry_backoff_seconds=300)
        now = _utc(2024, 7, 1, 9, 0)
        assert is_due(config, now=now, last_run_at=now - dt.timedelta(seconds=60), last_status="failed") is False
        assert is_due(config, now=now, last_run_at=now - dt.timedelta(seconds=400), last_status="failed") is True

    def test_backoff_ignored_on_success(self):
        config = ScheduleConfig(mode=ScheduleMode.INTERVAL, seconds=1, retry_backoff_seconds=300)
        now = _utc(2024, 7, 1, 9, 0)
        assert is_due(config, now=now, last_run_at=now - dt.timedelta(seconds=60), last_status="success") is True


class TestCron:
    def test_parse_ok(self):
        assert parse_cron("*/5 0-6 1,15 * 1-5") == ("*/5", "0-6", "1,15", "*", "1-5")

    @pytest.mark.parametrize(
        "expr",
        ["60 * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *", "* * * * 7", "x * * * *", "5-1 * * * *", "*/0 * * * *"],
    )
    def test_invalid_expressions(self, expr: str):
        with pytest.raises(ProviderError):
            parse_cron(expr)

    def test_step_matching(self):
        assert cron_matches("*/15 * * * *", _utc(2024, 7, 1, 0, 30)) is True
        assert cron_matches("*/15 * * * *", _utc(2024, 7, 1, 0, 31)) is False

    def test_list_and_range(self):
        assert cron_matches("0 9,18 * * *", _utc(2024, 7, 1, 18, 0)) is True
        assert cron_matches("0 9-17 * * *", _utc(2024, 7, 1, 12, 0)) is True
        assert cron_matches("0 9-17 * * *", _utc(2024, 7, 1, 18, 0)) is False

    def test_dow_sunday_zero(self):
        # 2024-07-07 是周日 → 等价 dow=0
        assert cron_matches("0 0 * * 0", _utc(2024, 7, 7, 0, 0)) is True
