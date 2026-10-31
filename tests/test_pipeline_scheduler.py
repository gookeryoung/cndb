"""流水线定时触发测试：cron 到期判定 / 单飞跳过 / 同步执行 / CLI（ADR 0076 P2）."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from cndb.core.config import settings
from cndb.plugins.pipeline.models import (
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULE,
    PipelineRun,
    PipelineWorkflow,
)
from cndb.plugins.pipeline.services import runner, scheduler
from cndb.plugins.pipeline.services.dsl.parse import compile_workflow
from tests.pipeline_helpers import make_table, make_user, make_workspace

NOW = dt.datetime(2024, 7, 1, 1, 30, tzinfo=dt.UTC)  # UTC+8 → 09:30


@pytest.fixture
def owner(db):
    return make_user(db, "pipeline_scheduler_owner")


@pytest.fixture
def ws(db, owner):
    return make_workspace(db, owner, "PipelineSchedulerWS")


@pytest.fixture
def people(db, ws):
    return make_table(db, ws, "人员", [("姓名", "text"), ("城市", "text")])


def _content(schedule: str, *, name: str = "定时巡检") -> str:
    return (
        f"name: {name}\n"
        "on:\n"
        "  manual: true\n"
        f'  schedule: "{schedule}"\n'
        "jobs:\n"
        "  表:\n"
        "    steps:\n"
        "      - uses: table/null-rate\n"
        "        with:\n"
        "          table: 人员\n"
        "          fields: [城市]\n"
    )


def _make_workflow(
    db,
    ws,
    schedule: str = "30 9 * * *",
    *,
    enabled: bool = True,
    name: str = "定时巡检",
) -> PipelineWorkflow:
    content = _content(schedule, name=name)
    ir = compile_workflow(content)
    workflow = PipelineWorkflow(
        workspace_id=ws.id,
        name=ir.name,
        content=content,
        compiled=ir.to_dict(),
        enabled=enabled,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def _runs(db, workflow: PipelineWorkflow) -> list[PipelineRun]:
    db.expire_all()
    return list(
        db.execute(select(PipelineRun).where(PipelineRun.workflow_id == workflow.id).order_by(PipelineRun.id)).scalars()
    )


class TestIsDue:
    def test_cron_hit_without_previous_run(self):
        assert scheduler.is_due("30 9 * * *", now=NOW, last_run_at=None) is True

    def test_cron_miss_returns_false(self):
        assert scheduler.is_due("0 9 * * *", now=NOW, last_run_at=None) is False

    def test_same_minute_already_ran(self):
        assert scheduler.is_due("30 9 * * *", now=NOW, last_run_at=NOW) is False

    def test_previous_minute_allows(self):
        before = NOW - dt.timedelta(minutes=1)
        assert scheduler.is_due("30 9 * * *", now=NOW, last_run_at=before) is True


class TestDueWorkflows:
    def test_only_enabled_with_schedule(self, db, ws):
        hit = _make_workflow(db, ws)
        _make_workflow(db, ws, enabled=False, name="停用巡检")
        no_schedule = compile_workflow(_content("30 9 * * *").replace('  schedule: "30 9 * * *"\n', ""))
        other = PipelineWorkflow(
            workspace_id=ws.id,
            name="手动巡检",
            content=no_schedule.name,
            compiled=no_schedule.to_dict(),
            enabled=True,
        )
        db.add(other)
        db.commit()

        due = scheduler.due_workflows(db, now=NOW)
        assert [workflow.id for workflow, _ in due] == [hit.id]
        assert due[0][1] == "30 9 * * *"

    def test_limit(self, db, ws):
        first = _make_workflow(db, ws, name="A")
        _make_workflow(db, ws, name="B")
        due = scheduler.due_workflows(db, now=NOW, limit=1)
        assert [workflow.id for workflow, _ in due] == [first.id]

    def test_workspace_and_workflow_filter(self, db, owner, ws):
        other_ws = make_workspace(db, owner, "OtherWS")
        target = _make_workflow(db, ws, name="目标")
        _make_workflow(db, other_ws, name="别的工作区")

        assert [w.id for w, _ in scheduler.due_workflows(db, now=NOW, workspace_id=ws.id)] == [target.id]
        assert [w.id for w, _ in scheduler.due_workflows(db, now=NOW, workflow_id=target.id)] == [target.id]

    def test_invalid_cron_is_skipped(self, db, ws, caplog):
        _make_workflow(db, ws, schedule="61 * * * *")
        assert scheduler.due_workflows(db, now=NOW) == []
        assert any("调度表达式非法" in record.message for record in caplog.records)

    def test_broken_compiled_is_skipped(self, db, ws, monkeypatch, caplog):
        _make_workflow(db, ws)

        def boom(_data):
            raise RuntimeError("编译快照损坏")

        monkeypatch.setattr(scheduler.WorkflowIR, "from_dict", boom)
        assert scheduler.due_workflows(db, now=NOW) == []
        assert any("编译快照损坏" in record.message for record in caplog.records)


class TestTick:
    def test_executes_due_workflow(self, db, ws, people):
        workflow = _make_workflow(db, ws)
        report = scheduler.tick(db, now=NOW)

        assert report.examined == 1
        assert report.executed == 1
        assert report.succeeded == 1
        assert report.workflow_ids == [workflow.id]
        run = _runs(db, workflow)[0]
        assert run.trigger == TRIGGER_SCHEDULE
        assert run.trigger_payload["event"] == "schedule"
        assert run.trigger_payload["cron"] == "30 9 * * *"
        assert run.status == "success"

    def test_same_minute_does_not_repeat(self, db, ws, people):
        workflow = _make_workflow(db, ws)
        scheduler.tick(db, now=NOW)
        report = scheduler.tick(db, now=NOW.replace(second=30))
        assert report.examined == 0
        assert len(_runs(db, workflow)) == 1

    def test_next_minute_slot_can_run_again(self, db, ws, people):
        workflow = _make_workflow(db, ws, schedule="* * * * *")
        scheduler.tick(db, now=NOW)
        # created_at 由数据库 server_default 填充，测试里对齐到 NOW 才能验证分钟槽水位
        run = _runs(db, workflow)[0]
        run.created_at = NOW
        db.commit()
        report = scheduler.tick(db, now=NOW + dt.timedelta(minutes=1))
        assert report.executed == 1
        assert len(_runs(db, workflow)) == 2

    def test_active_run_skips_conflict(self, db, ws):
        workflow = _make_workflow(db, ws)
        runner.create_run(db, workflow, trigger=TRIGGER_MANUAL)
        report = scheduler.tick(db, now=NOW)
        assert report.skipped_conflict == 1
        assert report.executed == 0

    def test_failed_run_counts(self, db, ws, monkeypatch):
        _make_workflow(db, ws)

        def fail(db_session: Session, run_id: int) -> None:
            run = db_session.get(PipelineRun, run_id)
            assert run is not None
            run.status = "failed"
            db_session.commit()

        monkeypatch.setattr(scheduler, "execute_pipeline_run", fail)
        report = scheduler.tick(db, now=NOW)
        assert report.failed == 1
        assert report.succeeded == 0

    def test_no_due_workflow(self, db, ws):
        _make_workflow(db, ws, schedule="0 9 * * *")
        report = scheduler.tick(db, now=NOW)
        assert report.examined == 0
        assert report.executed == 0

    def test_report_to_dict(self):
        report = scheduler.PipelineTickReport(examined=1, executed=1, succeeded=1, workflow_ids=[7])
        assert report.to_dict()["workflow_ids"] == [7]


@pytest.fixture
def cli_db(tmp_path: Path, monkeypatch) -> Session:
    """临时 SQLite（settings.DATABASE_URL）+ 已建表 session."""
    import cndb.plugins.accounts.models
    import cndb.plugins.documents.models
    import cndb.plugins.pipeline.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401
    from cndb.models.base import Base

    db_path = tmp_path / "cli_pipeline.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _ns(**kwargs: object) -> argparse.Namespace:
    ns = argparse.Namespace()
    for key, value in kwargs.items():
        setattr(ns, key, value)
    return ns


class TestCli:
    def test_cmd_tick_payload(self, cli_db, monkeypatch):
        from cndb.cli import pipeline as cli

        report = scheduler.PipelineTickReport(examined=1, executed=1, succeeded=1, workflow_ids=[3])
        monkeypatch.setattr(cli, "_get_session", lambda: cli_db)
        monkeypatch.setattr(scheduler, "tick", lambda _db, **_: report)

        payload = cli.cmd_tick(_ns(limit=10, workflow_id=3, workspace_id=1))
        assert payload["executed"] == 1
        assert payload["workflow_ids"] == [3]

    def test_pipeline_command_prints_json(self, cli_db, monkeypatch, capsys):
        from cndb.cli import pipeline as cli

        report = scheduler.PipelineTickReport(examined=1, executed=1, succeeded=1, workflow_ids=[3])
        monkeypatch.setattr(cli, "_get_session", lambda: cli_db)
        monkeypatch.setattr(scheduler, "tick", lambda _db, **_: report)

        cli.pipeline_command(_ns(pipeline_cmd="tick", json=True, limit=10, workflow_id=None, workspace_id=None))
        payload = json.loads(capsys.readouterr().out)
        assert payload["executed"] == 1

    def test_pipeline_command_prints_text(self, cli_db, monkeypatch, capsys):
        from cndb.cli import pipeline as cli

        report = scheduler.PipelineTickReport(examined=2, executed=2, succeeded=1, failed=1, workflow_ids=[3, 4])
        monkeypatch.setattr(cli, "_get_session", lambda: cli_db)
        monkeypatch.setattr(scheduler, "tick", lambda _db, **_: report)

        with pytest.raises(SystemExit) as exc:
            cli.pipeline_command(_ns(pipeline_cmd="tick", json=False, limit=10, workflow_id=None, workspace_id=None))
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "到期 2，执行 2" in out
        assert "执行流水线: #3, #4" in out

    def test_missing_subcommand_exits(self):
        from cndb.cli import pipeline as cli

        with pytest.raises(SystemExit):
            cli.pipeline_command(_ns(pipeline_cmd=None))

    def test_subparser_registered(self):
        from cndb.cli.pipeline import register_pipeline_subparser

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        register_pipeline_subparser(sub)
        args = parser.parse_args(["pipeline", "tick", "--workflow-id", "3", "--json"])
        assert (args.command, args.pipeline_cmd, args.workflow_id, args.json) == ("pipeline", "tick", 3, True)
