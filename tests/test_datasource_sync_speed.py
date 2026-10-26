"""SyncRunOut 速度字段判定单测（ADR 0040 D1）."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from cndb.plugins.datasource.schemas import SyncRunOut


def _run(**overrides: object) -> SimpleNamespace:
    base = {
        "id": 1,
        "job_id": 2,
        "status": "success",
        "trigger": "manual",
        "started_at": dt.datetime(2026, 10, 26, 2, 0, tzinfo=dt.UTC),
        "finished_at": dt.datetime(2026, 10, 26, 2, 0, 10, tzinfo=dt.UTC),
        "duration_ms": 10_000,
        "cursor_from": "",
        "cursor_to": "",
        "fetched": 1000,
        "inserted": 1000,
        "updated": 0,
        "skipped": 0,
        "progress_total": 2,
        "progress_done": 2,
        "progress_entrant": "sh600519",
        "error_message": "",
        "detail": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_finished_run_uses_duration_and_steady_rate() -> None:
    out = SyncRunOut.from_model(_run())
    assert out.elapsed_ms == 10_000
    assert out.rows_per_second == pytest.approx(100.0)
    assert out.detail == {}


def test_running_run_uses_injected_now() -> None:
    started = dt.datetime(2026, 10, 26, 2, 0, tzinfo=dt.UTC)
    run = _run(status="running", started_at=started, duration_ms=0, fetched=500)
    out = SyncRunOut.from_model(run, now=started + dt.timedelta(seconds=5))
    assert out.elapsed_ms == 5000
    assert out.rows_per_second == pytest.approx(100.0)


def test_running_run_treats_naive_started_at_as_utc() -> None:
    started = dt.datetime(2026, 10, 26, 2, 0)
    run = _run(status="running", started_at=started, duration_ms=0, fetched=100)
    out = SyncRunOut.from_model(run, now=dt.datetime(2026, 10, 26, 2, 0, 2, tzinfo=dt.UTC))
    assert out.elapsed_ms == 2000
    assert out.rows_per_second == pytest.approx(50.0)


def test_running_run_never_negative_elapsed() -> None:
    started = dt.datetime(2026, 10, 26, 2, 0, tzinfo=dt.UTC)
    run = _run(status="running", started_at=started, duration_ms=0, fetched=10)
    out = SyncRunOut.from_model(run, now=started - dt.timedelta(seconds=3))
    assert out.elapsed_ms == 0
    assert out.rows_per_second == 0.0


def test_sub_second_run_reports_zero_rate() -> None:
    run = _run(duration_ms=800, fetched=900)
    out = SyncRunOut.from_model(run)
    assert out.elapsed_ms == 800
    assert out.rows_per_second == 0.0


def test_empty_run_does_not_divide_by_zero() -> None:
    run = _run(duration_ms=5000, fetched=0)
    out = SyncRunOut.from_model(run)
    assert out.rows_per_second == 0.0


def test_tiny_rate_keeps_visible_floor() -> None:
    """有写入但速度取整为 0 时保底 0.1，避免界面显示 0 行/秒."""
    run = _run(duration_ms=3_600_000, fetched=1)
    out = SyncRunOut.from_model(run)
    assert out.rows_per_second == 0.1


def test_failed_run_keeps_terminal_elapsed() -> None:
    run = _run(status="failed", duration_ms=2000, fetched=40, finished_at=dt.datetime.now(dt.UTC))
    out = SyncRunOut.from_model(run)
    assert out.elapsed_ms == 2000
    assert out.rows_per_second == pytest.approx(20.0)
