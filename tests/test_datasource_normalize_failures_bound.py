"""归一失败明细有界单测（ADR 0043 D5）.

覆盖：

- ``_NormalizeAggregate.add_failures`` 明细封顶 100、``failed_total`` 全量；
- ``run_pipeline`` 大规模失败下内存明细有界；
- ``_finalize`` 的 ``detail["normalize_failures"]`` 键集合与条数口径不变，总量只进日志。
"""

from __future__ import annotations

import datetime as dt
import logging

from cndb.plugins.datasource.models import DatasourceSyncRun
from cndb.plugins.datasource.providers.base import RequestSpec, SyncJobSpec
from cndb.plugins.datasource.services import runner
from cndb.plugins.datasource.services.normalize import NormalizeFailure
from cndb.plugins.datasource.services.pipeline import (
    PipelineOutcome,
    _NormalizeAggregate,
    run_pipeline,
)
from cndb.plugins.datasource.services.write import WriteOutcome

UTC = dt.UTC
NOW = dt.datetime(2024, 7, 1, 9, 0, tzinfo=UTC)


def _failure(index: int) -> NormalizeFailure:
    return NormalizeFailure(row_index=index, field="temp", raw="bad", reason="无法转为数值")


class TestAggregateBound:
    def test_details_capped_total_kept(self):
        aggregate = _NormalizeAggregate()
        for round_ in range(3):
            aggregate.add_failures([_failure(round_ * 60 + i) for i in range(60)])
        assert len(aggregate.failures) == 100
        assert aggregate.failed_total == 180

    def test_empty_batch_is_noop(self):
        aggregate = _NormalizeAggregate()
        aggregate.add_failures([])
        assert aggregate.failures == [] and aggregate.failed_total == 0

    def test_partial_room_fills_exactly(self):
        aggregate = _NormalizeAggregate()
        aggregate.add_failures([_failure(i) for i in range(98)])
        aggregate.add_failures([_failure(i) for i in range(5)])
        assert len(aggregate.failures) == 100
        assert aggregate.failed_total == 103


class TestPipelineBound:
    def test_run_pipeline_bounds_failures(self):
        job = SyncJobSpec(
            request=RequestSpec(url_template="https://api.example.com/w"),
            field_mapping={"temp": {"name": "temp", "field_type": "float"}},
        )
        outcome = run_pipeline(
            job,
            fetch=lambda _config: [{"temp": "bad"} for _ in range(150)],
        )
        assert outcome.normalize is not None
        assert outcome.normalize.failed_total == 150
        assert len(outcome.normalize.failures) == 100


class TestFinalizeDetailUnchanged:
    def test_detail_keeps_first_100_and_logs_total(self, caplog):
        normalized = _NormalizeAggregate()
        normalized.add_failures([_failure(i) for i in range(150)])
        run = DatasourceSyncRun(job_id=1, status="success", trigger="manual", started_at=NOW)
        with caplog.at_level(logging.INFO, logger=runner.logger.name):
            runner._finalize(
                run,
                outcome=PipelineOutcome(plans=1, succeeded=1, normalize=normalized),
                write=WriteOutcome(fetched=150),
                cursor_from="",
                cursor_to="",
                started_clock=0.0,
                now=NOW,
            )
        assert set(run.detail) == {
            "plans",
            "succeeded",
            "failures",
            "normalize_failures",
            "dropped_fields",
            "filtered",
            "response_metadata",
            "auto_fields",
            "auto_match_keys",
        }
        assert len(run.detail["normalize_failures"]) == 100
        assert "归一失败 150 条" in caplog.text

    def test_detail_silent_when_all_kept(self, caplog):
        normalized = _NormalizeAggregate()
        normalized.add_failures([_failure(i) for i in range(3)])
        run = DatasourceSyncRun(job_id=1, status="success", trigger="manual", started_at=NOW)
        with caplog.at_level(logging.INFO, logger=runner.logger.name):
            runner._finalize(
                run,
                outcome=PipelineOutcome(plans=1, succeeded=1, normalize=normalized),
                write=WriteOutcome(fetched=3),
                cursor_from="",
                cursor_to="",
                started_clock=0.0,
                now=NOW,
            )
        assert len(run.detail["normalize_failures"]) == 3
        assert "归一失败" not in caplog.text
