"""datasource ADR 0034：管线并发 / 全局限速 / 流式分批 / 行过滤与常量模板单测.

覆盖：

- ``workers > 1`` 组间真并发（barrier 验证）与组内串行语义不变（空页停）；
- ``rate_limit_ms`` 全局相邻请求最小出发间隔（并发下同样成立）；
- ``on_batch`` 流式分批（批大小、rows 恒空、filtered / flushed 计数）、回调异常终止整轮；
- ``row_filter`` 数值剔除、``row_defaults`` 模板渲染（{today} / {entrant}）；
- ``llm_prompt`` 声明并发时按 1 执行（告警）。
"""

from __future__ import annotations

import itertools
import threading
import time
from typing import Any

import pytest

from cndb.plugins.datasource.providers.base import PagingSpec, RequestSpec, SyncJobSpec
from cndb.plugins.datasource.services.pipeline import (
    apply_row_defaults,
    apply_row_filter,
    fill_entrant,
    run_pipeline,
)


def _job(*, entrants: tuple[str, ...] = (), workers: int = 1, **request_kwargs: Any) -> SyncJobSpec:
    """单请求无分页的 http_json 任务骨架（每个 entrant 恰好一个请求）."""
    return SyncJobSpec(
        request=RequestSpec(
            url_template="https://api.example.com/w?s={symbol}",
            workers=workers,
            **request_kwargs,
        ),
        entrant_param="symbol",
        entrant_values=entrants,
    )


class TestConcurrentWorkers:
    def test_groups_run_concurrently(self):
        """两个 entrant × workers=2：fetch 内 barrier 会合，串行则超时破裂成失败."""
        barrier = threading.Barrier(2, timeout=5)

        def fetch(_config: Any) -> list[dict[str, Any]]:
            barrier.wait()
            return [{"symbol": "x", "v": 1}]

        outcome = run_pipeline(_job(entrants=("a", "b"), workers=2), fetch=fetch)
        assert outcome.status == "success"
        assert outcome.plans == 2
        assert outcome.succeeded == 2
        assert len(outcome.rows) == 2

    def test_serial_workers_do_not_cross_groups(self):
        """workers=1：组间串行，barrier(2) 永远会不齐 → 两组都超时失败（而非死锁）."""
        barrier = threading.Barrier(2, timeout=0.2)

        def fetch(_config: Any) -> list[dict[str, Any]]:
            barrier.wait()
            return [{"v": 1}]

        outcome = run_pipeline(_job(entrants=("a", "b"), workers=1), fetch=fetch)
        assert outcome.status == "failed"
        assert outcome.failed == 2

    def test_single_group_with_workers_stays_serial(self):
        """同组（同 entrant 分页）不并发：页 2 仍等页 1 结束后出发."""
        order: list[int] = []

        def fetch(config: Any) -> list[dict[str, Any]]:
            # 页码渲染进 URL 查询串（p={page}），从 URL 解析
            page = int(config.url.rsplit("p=", 1)[1])
            order.append(page)
            return [{"v": 1}] if page == 1 else []

        job = SyncJobSpec(
            request=RequestSpec(
                url_template="https://api.example.com/w?s={symbol}&p={page}",
                workers=4,
                paging=PagingSpec(mode="page", max_pages=3),
            ),
            entrant_param="symbol",
            entrant_values=("a",),
        )
        outcome = run_pipeline(job, fetch=fetch)
        assert outcome.status == "success"
        assert order == [1, 2]  # 空页停：第 2 页空 → 第 3 页不发

    def test_llm_prompt_forces_single_worker(self, caplog):
        calls: list[str] = []
        lock = threading.Lock()

        def fetch(config: Any) -> list[dict[str, Any]]:
            with lock:
                calls.append(config.url)
            return [{"v": 1}]

        job = SyncJobSpec(
            provider="llm_prompt",
            request=RequestSpec(
                url_template="https://api.example.com/w?s={symbol}",
                workers=4,
                prompt={"user_template": "生成一行数据"},
            ),
            entrant_param="symbol",
            entrant_values=("a", "b", "c"),
            extra_variables={"api_key": "test-key"},
        )
        with caplog.at_level("WARNING"):
            outcome = run_pipeline(job, fetch=fetch)
        assert outcome.status == "success"
        assert len(calls) == 3
        assert any("llm_prompt 不支持并发" in message for message in caplog.messages)


class TestGlobalRateLimit:
    def test_departures_spaced_under_concurrency(self, monkeypatch):
        """workers=4 × 4 组：每个请求不早于自己的预约时刻（0/0.1/0.2/0.3s）.

        用假时钟（sleep 推进时钟）消除真实调度抖动：出发时刻即预约时刻，
        任意相邻出发间隔精确 ≥ rate_limit（ADR 0034 D5 全局间隔语义）。
        """
        clock = {"now": 0.0}
        guard = threading.Lock()
        departures: list[float] = []
        lock = threading.Lock()

        def fake_monotonic() -> float:
            return clock["now"]

        def fake_sleep(delay: float) -> None:
            with guard:
                clock["now"] += delay

        monkeypatch.setattr(time, "monotonic", fake_monotonic)

        def fetch(_config: Any) -> list[dict[str, Any]]:
            with lock:
                departures.append(time.monotonic())
            return [{"v": 1}]

        run_pipeline(
            _job(entrants=("a", "b", "c", "d"), workers=4),
            fetch=fetch,
            rate_limit_ms=100,
            sleep=fake_sleep,
        )
        ordered = sorted(departures)
        assert len(ordered) == 4
        gaps = [second - first for first, second in itertools.pairwise(ordered)]
        assert all(gap >= 0.0995 for gap in gaps), (ordered, gaps)


class TestStreamingBatches:
    def test_batches_flushed_at_batch_size(self):
        batches: list[int] = []
        rows = [{"v": i} for i in range(5)]

        outcome = run_pipeline(
            _job(),
            fetch=lambda _config: rows,
            on_batch=lambda batch: batches.append(len(batch)),
            batch_size=2,
        )
        assert batches == [2, 2, 1]
        assert outcome.rows == []  # 流式下行不进 outcome.rows
        assert outcome.flushed == 5
        assert outcome.filtered == 0

    def test_batch_callback_error_aborts_run(self):
        """回调异常向外抛且未开始的组不再请求（断点续跑语义）."""
        calls: list[str] = []

        def fetch(config: Any) -> list[dict[str, Any]]:
            calls.append(config.url)
            return [{"v": 1}]

        def on_batch(_rows: Any) -> None:
            raise RuntimeError("落库失败")

        with pytest.raises(RuntimeError, match="落库失败"):
            run_pipeline(
                _job(entrants=("a", "b")),
                fetch=fetch,
                on_batch=on_batch,
                batch_size=1,
            )
        # 第一组 1 个请求已发；第二组被取消（cancel 标记）零请求
        assert len(calls) == 1

    def test_row_filter_applies_before_callback(self):
        batches: list[list[dict[str, Any]]] = []
        rows = [{"v": 3}, {"v": 0}, {"v": 5}]

        outcome = run_pipeline(
            SyncJobSpec(
                request=RequestSpec(
                    url_template="https://api.example.com/w",
                    row_filter={"field": "v", "op": ">", "value": 0},
                )
            ),
            fetch=lambda _config: rows,
            on_batch=lambda batch: batches.append([dict(row) for row in batch]),
            batch_size=10,
        )
        assert batches == [[{"v": 3}, {"v": 5}]]
        assert outcome.filtered == 1
        assert outcome.flushed == 2

    def test_row_defaults_template_rendered(self):
        batches: list[list[dict[str, Any]]] = []
        job = SyncJobSpec(
            request=RequestSpec(
                url_template="https://api.example.com/w?s={symbol}",
                row_defaults={"日期": "{today}", "来源": "新浪", "份数": 100},
            ),
            entrant_param="symbol",
            entrant_values=("sh600519",),
            extra_variables={"today": "2026-10-25"},
        )
        run_pipeline(
            job,
            fetch=lambda _config: [{"close": 1500.0}],
            on_batch=lambda batch: batches.append([dict(row) for row in batch]),
            batch_size=10,
        )
        # {today} 渲染、非字符串原样、setdefault 不覆盖已有列；symbol 由请求维度补齐
        assert batches == [[{"close": 1500.0, "symbol": "sh600519", "日期": "2026-10-25", "来源": "新浪", "份数": 100}]]


class TestRowHelpers:
    def test_apply_row_filter_keeps_and_removes(self):
        rows = [{"v": 1}, {"v": 0}, {"v": "bad"}, {"other": 1}]
        kept, removed = apply_row_filter(rows, {"field": "v", "op": ">=", "value": 1})
        assert kept == [{"v": 1}]
        assert removed == 3

    def test_apply_row_filter_none_passthrough(self):
        rows = [{"v": 0}]
        kept, removed = apply_row_filter(rows, None)
        assert kept == rows and removed == 0

    def test_apply_row_filter_incomplete_config_passthrough(self):
        """缺 field / op / value 的声明视为未配置（历史配置不炸）."""
        rows = [{"v": 0}]
        kept, removed = apply_row_filter(rows, {"field": "v"})
        assert kept == rows and removed == 0

    def test_apply_row_defaults_setdefault_semantics(self):
        rows = [{"来源": "腾讯", "v": 1}]
        filled = apply_row_defaults(rows, {"来源": "新浪", "日期": "2026-10-25"})
        # 响应自带的「来源」优先，缺的「日期」补上
        assert filled == [{"来源": "腾讯", "v": 1, "日期": "2026-10-25"}]

    def test_fill_entrant_setdefault_semantics(self):
        rows = [{"symbol": "sh600519", "v": 1}, {"v": 2}]
        filled = fill_entrant(rows, "symbol", "sz000001")
        assert filled[0]["symbol"] == "sh600519"  # 自带值不被覆盖
        assert filled[1]["symbol"] == "sz000001"


class TestRowFilterValidation:
    def test_rejects_bad_op(self):
        with pytest.raises(Exception, match="op 非法"):
            RequestSpec(
                url_template="https://api.example.com/w",
                row_filter={"field": "v", "op": "~", "value": 1},
            )

    def test_rejects_non_numeric_value(self):
        with pytest.raises(Exception, match="必须是数值"):
            RequestSpec(
                url_template="https://api.example.com/w",
                row_filter={"field": "v", "op": ">", "value": "1"},
            )

    def test_rejects_missing_field(self):
        with pytest.raises(Exception, match="field 不能为空"):
            RequestSpec(
                url_template="https://api.example.com/w",
                row_filter={"op": ">", "value": 1},
            )

    def test_rejects_zero_workers(self):
        with pytest.raises(Exception, match="workers"):
            RequestSpec(url_template="https://api.example.com/w", workers=0)
