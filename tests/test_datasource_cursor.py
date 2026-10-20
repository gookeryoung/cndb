"""datasource M2：增量游标四策略单测."""

from __future__ import annotations

import pytest

from cndb.plugins.datasource.providers.base import ProviderError
from cndb.plugins.datasource.services.cursor import CursorConfig, advance, max_field_value, window_start


class TestCursorConfig:
    def test_defaults_to_none_without_payload(self):
        config = CursorConfig.from_dict(None)
        assert config.strategy == "none"
        assert config.is_windowed is False

    def test_windowed_requires_field(self):
        with pytest.raises(ProviderError, match="增量字段"):
            CursorConfig(strategy="date")

    def test_unknown_strategy_rejected(self):
        with pytest.raises(ProviderError, match="未知游标策略"):
            CursorConfig(strategy="weekly")  # type: ignore[arg-type]
        with pytest.raises(ProviderError, match="未知游标策略"):
            CursorConfig.from_dict({"strategy": "weekly"})

    def test_roundtrip(self):
        config = CursorConfig.from_dict(
            {
                "strategy": "datetime",
                "field": "published_at",
                "backfill_start": "2024-01-01",
                "value": "2024-06-01 08:00:00",
            }
        )
        assert config.to_dict() == {
            "strategy": "datetime",
            "field": "published_at",
            "backfill_start": "2024-01-01",
            "value": "2024-06-01 08:00:00",
        }

    def test_empty_value_becomes_none(self):
        assert CursorConfig.from_dict({"strategy": "date", "field": "d", "value": ""}).value is None


class TestWindowStart:
    def test_value_wins(self):
        config = CursorConfig(strategy="date", field="d", backfill_start="2024-01-01", value="2024-06-30")
        assert window_start(config, today="2024-07-01") == "2024-06-30"

    def test_backfill_when_no_value(self):
        config = CursorConfig(strategy="date", field="d", backfill_start="2024-01-01")
        assert window_start(config, today="2024-07-01") == "2024-01-01"

    def test_today_when_nothing_configured(self):
        config = CursorConfig(strategy="datetime", field="ts")
        assert window_start(config, today="2024-07-01") == "2024-07-01"

    def test_non_windowed_returns_none(self):
        assert window_start(CursorConfig(strategy="key_set"), today="2024-07-01") is None
        assert window_start(CursorConfig(strategy="none"), today="2024-07-01") is None


class TestAdvance:
    def test_date_takes_max(self):
        config = CursorConfig(strategy="date", field="trade_date")
        rows = [{"trade_date": "2024-01-03"}, {"trade_date": "2024-01-05"}, {"trade_date": "2024-01-04"}]
        assert advance(config, rows) == "2024-01-05"

    def test_datetime_normalizes_formats(self):
        config = CursorConfig(strategy="datetime", field="published_at")
        rows = [{"published_at": "2024/01/03 08:00:00"}, {"published_at": "2024-01-03T09:30:00"}]
        assert advance(config, rows) == "2024-01-03 09:30:00"

    def test_no_new_data_keeps_previous(self):
        config = CursorConfig(strategy="date", field="d", value="2024-06-30")
        assert advance(config, []) == "2024-06-30"
        assert advance(config, [{"d": None}, {"d": "不是日期"}]) == "2024-06-30"

    def test_never_goes_backwards(self):
        config = CursorConfig(strategy="date", field="d", value="2024-06-30")
        assert advance(config, [{"d": "2024-01-01"}]) == "2024-06-30"

    def test_key_set_and_none_do_not_move(self):
        for strategy in ("key_set", "none"):
            config = CursorConfig(strategy=strategy)  # type: ignore[arg-type]
            assert advance(config, [{"d": "2024-01-01"}]) is None

    def test_max_field_value_ignores_bad_rows(self):
        assert max_field_value([{"d": "x"}, {"d": "2024-02-02"}], "d", "date") == "2024-02-02"
        assert max_field_value([], "d", "date") is None
