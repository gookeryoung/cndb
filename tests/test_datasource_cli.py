"""datasource M2：cndb sync CLI 测试（list / run / tick / preview）.

策略与 test_cli_docs.py 一致：直接调用 cli.sync 的函数，临时 SQLite + monkeypatch
``runner.run_pipeline``（CLI 内部不注入 fetch，测试替换管线避免真实联网）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cndb.core.config import settings
from cndb.plugins.datasource.models import DatasourceSyncJob, DatasourceSyncRun
from cndb.plugins.datasource.services import runner
from cndb.plugins.datasource.services.normalize import NormalizeResult
from cndb.plugins.datasource.services.pipeline import FetchFailure, PipelineOutcome


@pytest.fixture
def cli_db(tmp_path: Path, monkeypatch) -> Session:
    """临时 SQLite（settings.DATABASE_URL）+ 已建表 session."""
    import cndb.plugins.accounts.models
    import cndb.plugins.datasource.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401
    from cndb.models.base import Base

    db_path = tmp_path / "cli_sync.db"
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


def _add_job(db: Session, **overrides: object) -> DatasourceSyncJob:
    payload: dict[str, object] = {
        "workspace_id": 1,
        "name": "天气同步",
        "provider": "http_json",
        "request_spec": {"url_template": "https://api.example.com/w", "paging": {"mode": "none"}},
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


@pytest.fixture
def fake_pipeline(monkeypatch):
    """把 runner.run_pipeline 换成固定行（避免 CLI 真实联网）."""
    rows = [{"city": "北京", "temp": 30.0}]

    def fake(job, *, provider=None, fetch=None, rate_limit_ms=0, sleep=None):
        normalize = NormalizeResult(rows=list(rows))
        return PipelineOutcome(rows=list(rows), plans=1, succeeded=1, failures=[], normalize=normalize)

    monkeypatch.setattr(runner, "run_pipeline", fake)
    return rows


@pytest.fixture
def failing_pipeline(monkeypatch):
    def fake(job, *, provider=None, fetch=None, rate_limit_ms=0, sleep=None):
        normalize = NormalizeResult(rows=[])
        outcome = PipelineOutcome(rows=[], plans=1, succeeded=0, failures=[], normalize=normalize)
        outcome.failures.append(FetchFailure(label="single", error="HTTP 500"))
        return outcome

    monkeypatch.setattr(runner, "run_pipeline", fake)


class TestCmdList:
    def test_lists_jobs(self, cli_db, capsys):
        from cndb.cli.sync import cmd_list, sync_command

        _add_job(cli_db, name="A")
        payload = cmd_list(_ns(workspace_id=None))
        assert payload["total"] == 1
        assert payload["jobs"][0]["name"] == "A"

        sync_command(_ns(sync_cmd="list", json=False))
        out = capsys.readouterr().out
        assert "共 1 个任务" in out
        assert "#1 A" in out

    def test_workspace_filter(self, cli_db):
        from cndb.cli.sync import cmd_list

        _add_job(cli_db, workspace_id=1)
        _add_job(cli_db, workspace_id=2)
        assert cmd_list(_ns(workspace_id=2))["total"] == 1


class TestCmdRun:
    def test_run_single_job(self, cli_db, fake_pipeline):
        from cndb.cli.sync import cmd_run

        job = _add_job(cli_db)
        payload = cmd_run(_ns(job_id=job.id, dry_run=False, limit=20))
        assert payload["total"] == 1
        assert payload["failed"] == 0
        assert payload["results"][0]["status"] == "success"
        assert cli_db.query(DatasourceSyncRun).count() == 1

    def test_run_all_enabled(self, cli_db, fake_pipeline):
        from cndb.cli.sync import cmd_run

        _add_job(cli_db)
        _add_job(cli_db, enabled=False)
        payload = cmd_run(_ns(job_id=None, dry_run=False, limit=20))
        assert payload["total"] == 1

    def test_run_dry_run_does_not_write(self, cli_db, fake_pipeline):
        from cndb.cli.sync import cmd_run

        job = _add_job(cli_db)
        payload = cmd_run(_ns(job_id=job.id, dry_run=True, limit=5))
        assert payload["results"][0]["dry_run"] is True
        assert payload["results"][0]["total"] == 1
        assert cli_db.query(DatasourceSyncRun).count() == 0

    def test_missing_job_exits(self, cli_db):
        from cndb.cli.sync import cmd_run

        with pytest.raises(SystemExit):
            cmd_run(_ns(job_id=999, dry_run=False, limit=20))

    def test_failed_run_sets_exit_code(self, cli_db, failing_pipeline):
        from cndb.cli.sync import sync_command

        _add_job(cli_db)
        with pytest.raises(SystemExit) as exc:
            sync_command(_ns(sync_cmd="run", job_id=None, dry_run=False, limit=20, json=False))
        assert exc.value.code == 1


class TestCmdTick:
    def test_tick_executes_due(self, cli_db, fake_pipeline):
        from cndb.cli.sync import cmd_tick

        _add_job(cli_db)
        payload = cmd_tick(_ns(limit=10, job_id=None, workspace_id=None))
        assert payload["executed"] == 1
        assert payload["succeeded"] == 1

    def test_tick_json_print(self, cli_db, fake_pipeline, capsys):
        from cndb.cli.sync import sync_command

        _add_job(cli_db)
        sync_command(_ns(sync_cmd="tick", limit=10, job_id=None, workspace_id=None, json=True))
        payload = json.loads(capsys.readouterr().out)
        assert payload["executed"] == 1


class TestCmdPreview:
    def test_preview(self, cli_db, fake_pipeline, capsys):
        from cndb.cli.sync import cmd_preview, sync_command

        job = _add_job(cli_db)
        payload = cmd_preview(_ns(job_id=job.id, limit=5))
        assert payload["total"] == 1
        assert payload["columns"] == ["city", "temp"]

        sync_command(_ns(sync_cmd="preview", job_id=job.id, limit=5, json=False))
        assert "sync preview" in capsys.readouterr().out

    def test_preview_missing_job(self, cli_db):
        from cndb.cli.sync import cmd_preview

        with pytest.raises(SystemExit):
            cmd_preview(_ns(job_id=999, limit=5))


class TestSubparser:
    def test_registered(self):
        import argparse

        from cndb.cli.sync import register_sync_subparser

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        register_sync_subparser(sub)
        args = parser.parse_args(["sync", "run", "--job-id", "3", "--dry-run"])
        assert (args.command, args.sync_cmd, args.job_id, args.dry_run) == ("sync", "run", 3, True)

    def test_batch_kline_registered(self):
        import argparse

        from cndb.cli.sync import MAX_BATCH_SIZE, register_sync_subparser

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        register_sync_subparser(sub)
        args = parser.parse_args(
            ["sync", "batch-kline", "--workspace", "数据源示例", "--market", "A", "--batch-size", "50", "--dry-run"]
        )
        assert args.sync_cmd == "batch-kline"
        assert args.workspace == "数据源示例"
        assert args.market == "A"
        assert args.batch_size == 50
        assert args.series == "day_qfq"
        assert args.dry_run is True
        # 默认值：只取自选、每日 17:30、每批不超过上限
        assert args.include_unselected is False
        assert args.schedule == "daily"
        assert parser.parse_args(["sync", "batch-kline", "--workspace", "1"]).batch_size == MAX_BATCH_SIZE

    def test_missing_subcommand_exits(self):
        from cndb.cli.sync import sync_command

        with pytest.raises(SystemExit):
            sync_command(_ns(sync_cmd=None))


class TestPrintBranches:
    """打印分支覆盖（运维实际看到的就是这些行）."""

    def test_list_shows_disabled_state(self, cli_db, capsys):
        from cndb.cli.sync import cmd_list, sync_command

        _add_job(cli_db, name="停用任务", enabled=False, schedule={"mode": "manual"})
        sync_command(_ns(sync_cmd="list", workspace_id=None, json=False))
        out = capsys.readouterr().out
        assert "停用" in out
        assert "schedule=manual" in out
        assert cmd_list(_ns(workspace_id=None))["jobs"][0]["enabled"] is False

    def test_run_printer_covers_skipped_dry_run_and_error(self, capsys):
        from cndb.cli.sync import _print_run

        _print_run(
            {
                "total": 3,
                "failed": 1,
                "results": [
                    {"job_id": 1, "name": "A", "skipped": "租约已被占用"},
                    {
                        "job_id": 2,
                        "name": "B",
                        "dry_run": True,
                        "status": "partial",
                        "total": 1,
                        "columns": ["city"],
                        "failures": [{"label": "city=上海", "error": "HTTP 500"}],
                    },
                    {
                        "job_id": 3,
                        "name": "C",
                        "run_id": 9,
                        "status": "failed",
                        "fetched": 0,
                        "inserted": 0,
                        "updated": 0,
                        "skipped_rows": 0,
                        "cursor_from": "",
                        "cursor_to": "",
                        "error": "源故障",
                    },
                ],
            }
        )
        out = capsys.readouterr().out
        assert "跳过：租约已被占用" in out
        assert "[dry-run]" in out
        assert "city=上海: HTTP 500" in out
        assert "源故障" in out
        assert "失败 1 条" in out

    def test_tick_and_preview_printers(self, capsys):
        from cndb.cli.sync import _print_preview, _print_tick

        _print_tick({"examined": 2, "executed": 1, "succeeded": 1, "failed": 0, "skipped_leased": 1, "job_ids": [7]})
        _print_preview(
            {
                "job_id": 7,
                "name": "天气同步",
                "status": "partial",
                "plans": 2,
                "total": 1,
                "columns": ["city"],
                "cursor_from": "2024-01-01",
                "cursor_to": "2024-06-30",
                "failures": [{"label": "city=上海", "error": "HTTP 500"}],
                "rows": [{"city": "北京"}],
            }
        )
        out = capsys.readouterr().out
        assert "租约占用跳过 1" in out
        assert "#7" in out
        assert "北京" in out

    def test_run_skips_when_leased(self, cli_db, db):
        from cndb.cli.sync import cmd_run
        from cndb.plugins.datasource.services.scheduler import acquire_lease

        job = _add_job(cli_db)
        assert acquire_lease(cli_db, job.id, "other", now=dt.datetime.now(dt.UTC))
        payload = cmd_run(_ns(job_id=job.id, dry_run=False, limit=20))
        assert payload["results"][0]["skipped"] == "租约已被占用"

    def test_session_creates_missing_tables(self, tmp_path, monkeypatch):
        """首跑场景：库里还没有同步表时，_get_session 自动建表."""
        from sqlalchemy import create_engine as _create_engine
        from sqlalchemy import inspect

        from cndb.cli.sync import _get_session

        db_path = tmp_path / "fresh.db"
        monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
        _get_session().close()
        engine = _create_engine(f"sqlite:///{db_path}")
        try:
            assert inspect(engine).has_table("datasource_sync_job")
        finally:
            engine.dispose()
