"""acquisition P0 编排单测（ADR 0085 §2/§3）：运行 / 落表 / 台账 / 预览 / 状态口径."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import MetaData, func, select
from sqlalchemy.orm import Session

from cndb.plugins.acquisition.models import (
    AcquisitionItem,
    AcquisitionRound,
    AcquisitionRun,
    AcquisitionStrategy,
)
from cndb.plugins.acquisition.services.rules.expr import RuleError
from cndb.plugins.acquisition.services.runner import (
    StrategyBusyError,
    execute_strategy,
    preview_strategy,
)
from cndb.plugins.acquisition.services.validation import validate_strategy_payload
from cndb.plugins.datasource.models import DatasourceSyncJob
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.importing.api_fetch import FetchConfig

UTC = dt.UTC
NOW = dt.datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def _make_table(session: Session, engine) -> DataTable:
    table = DataTable(workspace_id=1, name="政策台账")
    table.ensure_db_name()
    session.add(table)
    session.commit()
    session.refresh(table)
    for order, (name, field_type) in enumerate((("city", "text"), ("day", "date"), ("temp", "float"))):
        field = DataField(table_id=table.id, name=name, field_type=field_type, order=order)
        field.ensure_db_name()
        session.add(field)
    session.commit()
    session.refresh(table)
    ddl.create_table(engine, table)
    return table


def _make_job(db: Session, table: DataTable, *, name: str = "天气同步") -> DatasourceSyncJob:
    job = DatasourceSyncJob(
        workspace_id=1,
        name=name,
        provider="http_json",
        table_id=table.id,
        request_spec={"url_template": "https://api.example.com/w?city={city}&q={query}"},
        parser="json",
        entrant_param="city",
        entrant_keys=["北京"],
        match_keys=["city", "day"],
        field_mapping={"day": {"name": "day", "field_type": "date"}, "temp": {"name": "temp", "field_type": "float"}},
        cursor={"strategy": "none"},
        schedule={"mode": "manual"},
        enabled=True,
        last_status="",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _make_strategy(
    db: Session,
    table: DataTable,
    *,
    channels: list[object] | None = None,
    filter_rule: dict[str, object] | None = None,
    iteration: dict[str, object] | None = None,
    name: str = "政策日报",
) -> AcquisitionStrategy:
    strategy = AcquisitionStrategy(
        workspace_id=1,
        name=name,
        enabled=True,
        scope={"channels": channels or [], "query": "北京", "max_results_per_channel": 50},
        filter_rule=filter_rule or {},
        targets=[{"kind": "table", "table_id": table.id, "match_keys": ["city", "day"]}],
        iteration=iteration or {"max_rounds": 1, "budget": {"max_requests": 10}},
        llm={},
        schedule={"mode": "manual"},
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return strategy


def _fetch(rows: list[dict[str, object]]):
    def fetch(_config: FetchConfig) -> list[dict[str, object]]:
        return [dict(row) for row in rows]

    return fetch


def _row_count(engine, table: DataTable) -> int:
    sa_table = ddl.build_sa_table(MetaData(), table)
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(sa_table)).scalar_one())


def _ledger(db: Session, strategy: AcquisitionStrategy) -> list[AcquisitionItem]:
    return list(db.execute(select(AcquisitionItem).where(AcquisitionItem.strategy_id == strategy.id)).scalars())


ROWS = [{"city": "北京", "day": "2026-11-01", "temp": "12.5"}]


class TestExecuteStrategy:
    def test_success_writes_rows_ledger_and_run(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        strategy = _make_strategy(db, table, channels=[f"job:{job.id}"])

        execution = execute_strategy(db, strategy, fetch=_fetch(ROWS), now=NOW)

        assert execution.status == "success"
        assert execution.collected == 1
        assert execution.after_filter == 1
        assert execution.report.inserted == 1
        assert _row_count(db_engine, table) == 1

        db.refresh(strategy)
        assert strategy.last_status == "success"
        run = db.execute(select(AcquisitionRun)).scalar_one()
        assert run.status == "success" and run.fetched == 1 and run.round_count == 1
        assert run.rule_snapshot["rule_version"] == strategy.rule_version
        assert run.budget_used["requests"] == 1
        rounds = db.execute(select(AcquisitionRound)).scalars().all()
        assert len(rounds) == 1
        assert rounds[0].query == "北京"
        assert rounds[0].stop_reason == "max_rounds"
        assert rounds[0].review_state == "auto"
        items = _ledger(db, strategy)
        assert len(items) == 1
        assert items[0].target_kind == "table" and items[0].target_id == table.id

    def test_rerun_updates_without_duplicates(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        strategy = _make_strategy(db, table, channels=[f"job:{job.id}"])

        execute_strategy(db, strategy, fetch=_fetch(ROWS), now=NOW)
        second = execute_strategy(
            db, strategy, fetch=_fetch([{"city": "北京", "day": "2026-11-01", "temp": "13.0"}]), now=NOW
        )

        assert second.status == "success"
        assert second.report.inserted == 0
        assert second.report.updated == 1
        assert _row_count(db_engine, table) == 1
        assert len(_ledger(db, strategy)) == 1

    def test_filter_rejects_rows_but_run_still_success(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        strategy = _make_strategy(db, table, channels=[f"job:{job.id}"], filter_rule={"exclude_keywords": ["北京"]})

        execution = execute_strategy(db, strategy, fetch=_fetch(ROWS), now=NOW)

        assert execution.status == "success"
        assert execution.after_filter == 0
        assert _row_count(db_engine, table) == 0
        assert _ledger(db, strategy) == []

    def test_partial_when_one_channel_missing(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        strategy = _make_strategy(db, table, channels=[f"job:{job.id}", "job:999999"])

        execution = execute_strategy(db, strategy, fetch=_fetch(ROWS), now=NOW)

        assert execution.status == "partial"
        assert execution.report.inserted == 1
        assert any("999999" in error["error"] for error in execution.channel_errors)

    def test_failed_when_all_channels_unusable(self, db_engine, db):
        table = _make_table(db, db_engine)
        strategy = _make_strategy(db, table, channels=["job:999999"])

        execution = execute_strategy(db, strategy, fetch=_fetch(ROWS), now=NOW)

        assert execution.status == "failed"
        assert execution.report.inserted == 0

    def test_budget_exhausted_marks_partial(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        strategy = _make_strategy(
            db,
            table,
            channels=[f"job:{job.id}", f"job:{job.id}"],
            iteration={"max_rounds": 1, "budget": {"max_requests": 1}},
        )

        execution = execute_strategy(db, strategy, fetch=_fetch(ROWS), now=NOW)

        assert execution.status == "partial"
        run = db.execute(select(AcquisitionRun)).scalar_one()
        assert run.detail["budget_exhausted"] is True

    def test_busy_lease_blocks_second_run(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        strategy = _make_strategy(db, table, channels=[f"job:{job.id}"])
        strategy.lease_owner = "other-host"
        strategy.lease_until = NOW + dt.timedelta(minutes=5)
        db.add(strategy)
        db.commit()

        with pytest.raises(StrategyBusyError):
            execute_strategy(db, strategy, fetch=_fetch(ROWS), now=NOW)

    def test_preview_writes_nothing(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        strategy = _make_strategy(db, table, channels=[f"job:{job.id}"])

        execution = preview_strategy(db, strategy, fetch=_fetch(ROWS), now=NOW)

        assert execution.collected == 1 and execution.after_filter == 1
        assert execution.samples and execution.samples[0]["city"] == "北京"
        assert _row_count(db_engine, table) == 0
        assert _ledger(db, strategy) == []
        assert db.execute(select(AcquisitionRun)).scalars().all() == []
        db.refresh(strategy)
        assert strategy.lease_owner is None


class TestValidation:
    def _valid(self, table_id: int = 1) -> dict[str, object]:
        return {
            "scope": {"channels": ["job:1"], "query": "{today} 北京"},
            "filter_rule": {"must_have_keywords": ["北京"]},
            "targets": [{"kind": "table", "table_id": table_id, "match_keys": ["city"]}],
            "iteration": {"max_rounds": 1, "expand": {"review": "llm"}},
        }

    def test_valid_payload_passes(self) -> None:
        validate_strategy_payload(**self._valid())  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("patch", "message"),
        [
            ({"scope": {"channels": [], "query": "x"}}, "channels 不能为空"),
            ({"scope": {"channels": ["bad:1"], "query": "x"}}, "渠道引用非法"),
            ({"scope": {"channels": ["job:1"], "query": "{missing}"}}, "未知占位符"),
            ({"targets": [{"kind": "document", "parent_id": -1}]}, "parent_id"),
            ({"iteration": {"max_rounds": 9}}, "上限"),
            ({"iteration": {"expand": {"review": "maybe"}}}, "review 非法"),
        ],
    )
    def test_invalid_payloads_raise(self, patch: dict[str, object], message: str) -> None:
        payload = {**self._valid(), **patch}
        with pytest.raises(RuleError) as excinfo:
            validate_strategy_payload(**payload)  # type: ignore[arg-type]
        assert message in str(excinfo.value)
