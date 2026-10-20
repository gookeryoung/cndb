"""datasource M2：调度器（到期扫描 / DB 租约 / tick）单测."""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from cndb.plugins.datasource.models import DatasourceSyncJob, DatasourceSyncRun
from cndb.plugins.datasource.services import scheduler
from cndb.plugins.datasource.services.runner import execute_job
from cndb.plugins.tables.services.importing.api_fetch import FetchConfig

UTC = dt.UTC
NOW = dt.datetime(2024, 7, 1, 9, 0, tzinfo=UTC)

BASE_SPEC: dict[str, object] = {
    "url_template": "https://api.example.com/w",
    "paging": {"mode": "none"},
    "time_window": {"mode": "none"},
}


def _make_job(db: Session, **overrides: object) -> DatasourceSyncJob:
    payload: dict[str, object] = {
        "workspace_id": 1,
        "name": "天气同步",
        "provider": "http_json",
        "request_spec": dict(BASE_SPEC),
        "parser": "json",
        "entrant_keys": [],
        "match_keys": [],
        "field_mapping": {},
        "cursor": {"strategy": "none"},
        "schedule": {"mode": "interval", "seconds": 60},
        "enabled": True,
        "last_status": "",
    }
    payload.update(overrides)
    job = DatasourceSyncJob(**payload)  # type: ignore[arg-type]
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _ok_fetch(rows: list[dict[str, object]]):
    def fetch(_config: FetchConfig) -> list[dict[str, object]]:
        return rows

    return fetch


def _boom_fetch(_config: FetchConfig) -> list[dict[str, object]]:
    raise ValueError("HTTP 500: 模拟源故障")


class TestLease:
    def test_second_holder_blocked(self, db):
        job = _make_job(db)
        assert scheduler.acquire_lease(db, job.id, "owner-a", now=NOW) is True
        assert scheduler.acquire_lease(db, job.id, "owner-b", now=NOW) is False

    def test_release_allows_other_holder(self, db):
        job = _make_job(db)
        assert scheduler.acquire_lease(db, job.id, "owner-a", now=NOW) is True
        scheduler.release_lease(db, job.id, "owner-a")
        assert scheduler.acquire_lease(db, job.id, "owner-b", now=NOW) is True

    def test_expired_lease_can_be_taken(self, db):
        job = _make_job(db)
        assert scheduler.acquire_lease(db, job.id, "owner-a", now=NOW, ttl_seconds=60) is True
        later = NOW + dt.timedelta(seconds=61)
        assert scheduler.acquire_lease(db, job.id, "owner-b", now=later) is True

    def test_release_only_by_owner(self, db):
        job = _make_job(db)
        assert scheduler.acquire_lease(db, job.id, "owner-a", now=NOW) is True
        scheduler.release_lease(db, job.id, "owner-b")
        db.refresh(job)
        assert job.lease_owner == "owner-a"


class TestDueJobs:
    def test_interval_due(self, db):
        job = _make_job(db)
        assert [item.id for item in scheduler.due_jobs(db, now=NOW)] == [job.id]

    def test_interval_not_due(self, db):
        _make_job(db, last_run_at=NOW - dt.timedelta(seconds=10))
        assert scheduler.due_jobs(db, now=NOW) == []

    def test_disabled_skipped(self, db):
        _make_job(db, enabled=False)
        assert scheduler.due_jobs(db, now=NOW) == []

    def test_manual_never_due(self, db):
        _make_job(db, schedule={"mode": "manual"})
        assert scheduler.due_jobs(db, now=NOW) == []

    def test_broken_schedule_skipped(self, db):
        _make_job(db, schedule={"mode": "weekly"})
        assert scheduler.due_jobs(db, now=NOW) == []

    def test_filters(self, db):
        first = _make_job(db, name="A")
        _make_job(db, name="B")
        assert [item.id for item in scheduler.due_jobs(db, now=NOW, job_id=first.id)] == [first.id]
        assert scheduler.due_jobs(db, now=NOW, workspace_id=99) == []


class TestTick:
    def test_executes_due_job(self, db):
        job = _make_job(db)
        report = scheduler.tick(db, now=NOW, owner="tester", fetch=_ok_fetch([{"a": 1}]))
        assert (report.examined, report.executed, report.succeeded, report.failed) == (1, 1, 1, 0)
        assert report.job_ids == [job.id]
        db.refresh(job)
        assert job.last_status == "success"
        assert job.lease_owner is None  # 执行完释放
        runs = db.query(DatasourceSyncRun).filter(DatasourceSyncRun.job_id == job.id).all()
        assert len(runs) == 1

    def test_skips_leased_job(self, db):
        job = _make_job(db)
        assert scheduler.acquire_lease(db, job.id, "other", now=NOW) is True
        report = scheduler.tick(db, now=NOW, owner="tester", fetch=_ok_fetch([]))
        assert (report.examined, report.executed, report.skipped_leased) == (1, 0, 1)

    def test_failed_run_counted(self, db):
        job = _make_job(db)
        report = scheduler.tick(db, now=NOW, owner="tester", fetch=_boom_fetch)
        assert (report.executed, report.failed) == (1, 1)
        db.refresh(job)
        assert job.last_status == "failed"

    def test_nothing_due(self, db):
        report = scheduler.tick(db, now=NOW, owner="tester", fetch=_ok_fetch([]))
        assert (report.examined, report.executed) == (0, 0)
        assert report.to_dict()["job_ids"] == []


class TestExecuteTrigger:
    def test_manual_execution_keeps_trigger(self, db):
        job = _make_job(db)
        execution = execute_job(db, job, fetch=_ok_fetch([]), now=NOW)
        assert execution.run.trigger == "manual"
        assert execution.run.status == "success"
