"""core/task_runner.py：统一后台线程登记 / 超时 / 回收."""

from __future__ import annotations

import logging
import threading

import pytest

from cndb.core import task_runner


@pytest.fixture(autouse=True)
def _clean_registry():
    task_runner.reset()
    yield
    task_runner.reset()


def test_spawn_runs_and_registers_live_thread() -> None:
    done = threading.Event()
    task_runner.spawn("demo-job", done.set)
    assert done.wait(5)
    # 线程结束后 join_all 会清掉登记
    task_runner.join_all(timeout=1)
    assert task_runner.live_threads() == []


def test_run_with_timeout_returns_value() -> None:
    assert task_runner.run_with_timeout(lambda: 42, name="ok-job", timeout=5, timeout_message="boom") == 42


def test_run_with_timeout_reraises_job_error() -> None:
    def _fail() -> None:
        raise ValueError("内部错误")

    with pytest.raises(ValueError, match="内部错误"):
        task_runner.run_with_timeout(_fail, name="fail-job", timeout=5, timeout_message="boom")


def test_run_with_timeout_keeps_orphan_registered(caplog) -> None:
    """超时只代表调用方不再等待：线程仍留在登记表，join_all 能观测到并给出警告."""
    release = threading.Event()
    started = threading.Event()

    def _slow() -> None:
        started.set()
        release.wait(5)

    with caplog.at_level(logging.WARNING), pytest.raises(TimeoutError, match="超时了"):
        task_runner.run_with_timeout(_slow, name="slow-job", timeout=0.01, timeout_message="超时了")
    assert started.wait(5)
    assert task_runner.live_threads() == ["slow-job"]

    task_runner.join_all(timeout=0.01)
    assert "slow-job" in caplog.text
    assert task_runner.live_threads() == ["slow-job"]

    release.set()
    task_runner.join_all(timeout=5)
    assert task_runner.live_threads() == []


def test_join_all_joins_finished_threads() -> None:
    finished = threading.Event()
    finished.set()
    thread = task_runner.spawn("done-job", finished.wait)
    task_runner.join_all(timeout=1)
    assert not thread.is_alive()
    assert task_runner.live_threads() == []


def test_reset_clears_registry() -> None:
    release = threading.Event()
    try:
        _ = task_runner.spawn("blocked-job", lambda: release.wait(5))
        assert task_runner.live_threads() == ["blocked-job"]
        task_runner.reset()
        assert task_runner.live_threads() == []
    finally:
        release.set()
