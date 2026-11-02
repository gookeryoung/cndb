"""cndb acquisition 子命令：分发 / 输出格式 / 退出码（ADR 0085）.

CLI 只做「取 session → 调服务层 → 打印」，因此这里用 stub 替换服务层，
锁住四件事：子命令分发正确、``--json`` 与人类可读输出都有内容、失败退出码
（run failed / tick 有 failed）为 1、缺子命令为 2；另一条用例单独覆盖
``_get_session`` 建表兜底分支。
"""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace
from typing import Any

import pytest

from cndb.cli import acquisition as cli
from tests.test_acquisition_iteration import _make_job, _make_table, _make_workspace, _table_strategy


class _SessionProxy:
    """包一层 session：CLI 会 ``close()``，测试 fixture 的 session 需要活到断言之后."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def close(self) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._db, name)


@pytest.fixture()
def cli_session(monkeypatch, db):
    """把 CLI 的 session 工厂指向测试 session（不真正关闭）."""
    monkeypatch.setattr(cli, "_get_session", lambda: _SessionProxy(db))
    return db


def _args(**kwargs: Any) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def _execution(**overrides: Any) -> SimpleNamespace:
    payload: dict[str, Any] = {
        "run": SimpleNamespace(id=7, error_message=""),
        "status": "success",
        "collected": 5,
        "after_dedup": 4,
        "after_filter": 3,
        "report": SimpleNamespace(
            inserted=2,
            updated=1,
            skipped=0,
            docs_created=1,
            docs_updated=0,
            errors=[],
        ),
        "channel_errors": [],
        "by_channel": {"rss": 5},
        "samples": [{"title": "样例"}],
        "rounds": 2,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


class TestGetSession:
    def test_creates_missing_tables_and_reuses_existing(self, tmp_path, monkeypatch) -> None:
        from cndb.core.config import settings

        db_path = tmp_path / "cli.sqlite3"
        monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}", raising=False)

        first = cli._get_session()
        try:
            assert db_path.exists()
        finally:
            first.close()

        # 第二次：表已存在，不再 create_all（走 has_table 提前返回分支）
        second = cli._get_session()
        try:
            from sqlalchemy import text

            assert second.execute(text("select count(*) from acquisition_strategy")).scalar() == 0
        finally:
            second.close()


class TestCmdList:
    def test_empty_and_workspace_filter(self, cli_session, db_engine, db) -> None:
        assert cli.cmd_list(_args())["total"] == 0

        ws, _user = _make_workspace(db, "CLI 列表")
        other, _user2 = _make_workspace(db, "CLI 其他")
        table = _make_table(db, db_engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = _table_strategy(db, workspace_id=ws.id, table_id=table.id, job_id=job.id)

        payload = cli.cmd_list(_args())
        assert payload["total"] == 1
        item = payload["strategies"][0]
        assert item["id"] == strategy.id
        assert item["workspace_id"] == ws.id
        assert item["channels"] == [f"job:{job.id}"]
        assert item["targets"] == ["table"]
        assert item["last_run_at"] is None

        assert cli.cmd_list(_args(workspace_id=other.id))["total"] == 0
        assert cli.cmd_list(_args(workspace_id=ws.id))["total"] == 1

    def test_print_list_shows_state_and_last_status(self, capsys) -> None:
        cli._print_list(
            {
                "total": 2,
                "strategies": [
                    {
                        "id": 1,
                        "workspace_id": 1,
                        "name": "启用策略",
                        "enabled": True,
                        "rule_version": 3,
                        "channels": ["rss:x"],
                        "targets": ["table"],
                        "last_status": "success",
                        "last_run_at": "2026-11-02T09:00:00+00:00",
                    },
                    {
                        "id": 2,
                        "workspace_id": 1,
                        "name": "停用策略",
                        "enabled": False,
                        "rule_version": 1,
                        "channels": [],
                        "targets": [None],
                        "last_status": None,
                        "last_run_at": None,
                    },
                ],
            }
        )
        out = capsys.readouterr().out
        assert "共 2 条策略" in out
        assert "启用策略 [启用] v3 channels=1 targets=table last=success@" in out
        assert "停用策略 [停用] v1 channels=0 targets=- last=-@" in out


class TestCmdRun:
    def test_success_and_busy(self, cli_session, db_engine, db, monkeypatch) -> None:
        ws, _user = _make_workspace(db, "CLI 运行")
        table = _make_table(db, db_engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = _table_strategy(db, workspace_id=ws.id, table_id=table.id, job_id=job.id)

        monkeypatch.setattr(
            "cndb.plugins.acquisition.services.runner.execute_strategy",
            lambda *a, **kw: _execution(),
        )
        payload = cli.cmd_run(_args(strategy_id=strategy.id))
        assert payload["run_id"] == 7
        assert payload["status"] == "success"
        assert payload["inserted"] == 2
        assert payload["error"] == ""

        def _busy(*_a: Any, **_kw: Any) -> Any:
            from cndb.plugins.acquisition.services.runner import StrategyBusyError

            raise StrategyBusyError("已在运行")

        monkeypatch.setattr("cndb.plugins.acquisition.services.runner.execute_strategy", _busy)
        busy = cli.cmd_run(_args(strategy_id=strategy.id))
        assert busy["status"] == "skipped"
        assert busy["skipped"] == "已在运行"

    def test_missing_strategy_exits(self, cli_session) -> None:
        with pytest.raises(SystemExit):
            cli.cmd_run(_args(strategy_id=99999))

    def test_print_run_branches(self, capsys) -> None:
        cli._print_run({"strategy_id": 3, "skipped": "租约被占用"})
        assert "跳过：租约被占用" in capsys.readouterr().out

        cli._print_run(
            {
                "strategy_id": 3,
                "name": "策略",
                "run_id": 9,
                "status": "partial",
                "collected": 5,
                "after_dedup": 4,
                "after_filter": 3,
                "inserted": 2,
                "updated": 1,
                "skipped": 0,
                "channel_errors": [{"channel": "rss:x", "error": "超时"}],
                "target_errors": [{"target": "table:1", "error": "字段缺失"}],
                "error": "部分渠道失败",
            }
        )
        out = capsys.readouterr().out
        assert "run#9 status=partial" in out
        assert "! rss:x: 超时" in out
        assert "! table:1: 字段缺失" in out
        assert "! 部分渠道失败" in out


class TestCmdPreview:
    def test_limit_and_payload(self, cli_session, db_engine, db, monkeypatch) -> None:
        ws, _user = _make_workspace(db, "CLI 预览")
        table = _make_table(db, db_engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = _table_strategy(db, workspace_id=ws.id, table_id=table.id, job_id=job.id)

        monkeypatch.setattr(
            "cndb.plugins.acquisition.services.runner.preview_strategy",
            lambda *a, **kw: _execution(samples=[{"title": "a"}, {"title": "b"}]),
        )
        payload = cli.cmd_preview(_args(strategy_id=strategy.id, limit=1))
        assert payload["samples"] == [{"title": "a"}]
        assert payload["by_channel"] == {"rss": 5}
        # limit 缺省 / 0 回落到 SAMPLE_SIZE
        assert len(cli.cmd_preview(_args(strategy_id=strategy.id, limit=None))["samples"]) == 2

    def test_print_preview(self, capsys) -> None:
        cli._print_preview(
            {
                "strategy_id": 1,
                "name": "预览策略",
                "status": "success",
                "collected": 5,
                "after_dedup": 4,
                "after_filter": 3,
                "by_channel": {"rss": 5},
                "channel_errors": [{"channel": "rss:x", "error": "超时"}],
                "samples": [{"title": "样例"}],
            }
        )
        out = capsys.readouterr().out
        assert "acquisition preview] #1 预览策略" in out
        assert "- rss: 5 条" in out
        assert "! rss:x: 超时" in out
        assert '"title": "样例"' in out


class TestCmdResume:
    def _run(self, db, strategy):
        import datetime as dt

        from cndb.plugins.acquisition.models import AcquisitionRun, RunStatus

        run = AcquisitionRun(
            strategy_id=strategy.id,
            status=RunStatus.AWAITING_REVIEW.value,
            trigger="manual",
            rule_snapshot={},
            started_at=dt.datetime(2026, 11, 2, 9, 0, tzinfo=dt.UTC),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    def test_success_busy_and_failure(self, cli_session, db_engine, db, monkeypatch) -> None:
        ws, _user = _make_workspace(db, "CLI 续跑")
        table = _make_table(db, db_engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = _table_strategy(db, workspace_id=ws.id, table_id=table.id, job_id=job.id)
        run = self._run(db, strategy)

        seen: dict[str, Any] = {}

        def _resume(_db, _run, *, keywords=None, query=None, now=None):
            seen.update(keywords=keywords, query=query)
            return _execution(run=_run, status="success", by_channel={})

        monkeypatch.setattr("cndb.plugins.acquisition.services.runner.resume_run", _resume)
        payload = cli.cmd_resume(_args(run_id=run.id, keywords=["固态", "界面"], query=None))
        assert payload["run_id"] == run.id
        assert payload["docs_created"] == 1
        assert seen == {"keywords": ["固态", "界面"], "query": None}

        def _busy(*_a: Any, **_kw: Any) -> Any:
            from cndb.plugins.acquisition.services.runner import StrategyBusyError

            raise StrategyBusyError("运行中")

        monkeypatch.setattr("cndb.plugins.acquisition.services.runner.resume_run", _busy)
        assert cli.cmd_resume(_args(run_id=run.id))["status"] == "skipped"

        def _boom(*_a: Any, **_kw: Any) -> Any:
            raise ValueError("规则非法")

        monkeypatch.setattr("cndb.plugins.acquisition.services.runner.resume_run", _boom)
        failed = cli.cmd_resume(_args(run_id=run.id))
        assert failed["status"] == "failed"
        assert failed["error"] == "规则非法"

    def test_missing_run_exits(self, cli_session) -> None:
        with pytest.raises(SystemExit):
            cli.cmd_resume(_args(run_id=99999))

    def test_print_resume_branches(self, capsys) -> None:
        cli._print_resume({"run_id": 1, "skipped": "运行中"})
        assert "跳过：运行中" in capsys.readouterr().out
        cli._print_resume({"run_id": 1, "error": "规则非法"})
        assert "失败：规则非法" in capsys.readouterr().out
        cli._print_resume(
            {
                "run_id": 5,
                "strategy_id": 2,
                "status": "success",
                "rounds": 2,
                "collected": 5,
                "after_filter": 3,
                "inserted": 2,
                "updated": 1,
                "docs_created": 1,
                "docs_updated": 0,
            }
        )
        assert "run#5 strategy#2 status=success" in capsys.readouterr().out


class TestCmdTick:
    def test_payload_passthrough(self, cli_session, monkeypatch) -> None:
        report = SimpleNamespace(to_dict=lambda: {"examined": 3, "executed": 1})
        seen: dict[str, Any] = {}

        def _tick(_db, *, now=None, limit=None, workspace_id=None, strategy_id=None):
            seen.update(limit=limit, workspace_id=workspace_id, strategy_id=strategy_id)
            return report

        monkeypatch.setattr("cndb.plugins.acquisition.services.scheduler.tick", _tick)
        payload = cli.cmd_tick(_args(limit=None, workspace_id=4, strategy_id=9))
        assert payload == {"examined": 3, "executed": 1}
        assert seen == {"limit": 20, "workspace_id": 4, "strategy_id": 9}

    def test_print_tick(self, capsys) -> None:
        cli._print_tick(
            {
                "examined": 5,
                "executed": 2,
                "succeeded": 1,
                "partial": 0,
                "failed": 1,
                "awaiting_review": 0,
                "resumed_timeout": 0,
                "skipped_leased": 1,
                "skipped_pending": 2,
                "strategy_ids": [3, 4],
            }
        )
        out = capsys.readouterr().out
        assert "扫描 5 条，执行 2 条" in out
        assert "- strategy#3" in out


class TestAcquisitionCommand:
    def test_missing_subcommand_exits_2(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            cli.acquisition_command(_args())
        assert exc.value.code == 2
        assert "缺少 acquisition 子命令" in capsys.readouterr().err

    def test_json_output_and_exit_codes(self, cli_session, db_engine, db, monkeypatch, capsys) -> None:
        ws, _user = _make_workspace(db, "CLI 分发")
        table = _make_table(db, db_engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = _table_strategy(db, workspace_id=ws.id, table_id=table.id, job_id=job.id)

        # list --json
        cli.acquisition_command(_args(acquisition_cmd="list", json=True))
        listed = json.loads(capsys.readouterr().out)
        assert listed["total"] == 1

        # run --json + 失败退出码 1
        monkeypatch.setattr(
            "cndb.plugins.acquisition.services.runner.execute_strategy",
            lambda *a, **kw: _execution(status="failed"),
        )
        with pytest.raises(SystemExit) as exc:
            cli.acquisition_command(_args(acquisition_cmd="run", json=True, strategy_id=strategy.id))
        assert exc.value.code == 1
        assert json.loads(capsys.readouterr().out)["status"] == "failed"

        # tick --json + 有失败退出码 1
        monkeypatch.setattr(
            "cndb.plugins.acquisition.services.scheduler.tick",
            lambda *a, **kw: SimpleNamespace(to_dict=lambda: {"failed": 1, "executed": 1}),
        )
        with pytest.raises(SystemExit) as exc2:
            cli.acquisition_command(_args(acquisition_cmd="tick", json=True, limit=1))
        assert exc2.value.code == 1
        assert json.loads(capsys.readouterr().out)["failed"] == 1

    def test_human_readable_dispatch(self, cli_session, monkeypatch, capsys) -> None:
        monkeypatch.setattr(
            "cndb.plugins.acquisition.services.scheduler.tick",
            lambda *a, **kw: SimpleNamespace(
                to_dict=lambda: {
                    "examined": 0,
                    "executed": 0,
                    "succeeded": 0,
                    "partial": 0,
                    "failed": 0,
                    "awaiting_review": 0,
                    "resumed_timeout": 0,
                    "skipped_leased": 0,
                    "skipped_pending": 0,
                    "strategy_ids": [],
                }
            ),
        )
        cli.acquisition_command(_args(acquisition_cmd="tick"))
        assert "acquisition tick]" in capsys.readouterr().out

        monkeypatch.setattr(
            "cndb.plugins.acquisition.services.runner.execute_strategy",
            lambda *a, **kw: _execution(),
        )
        # 不存在的策略 → SystemExit（_load_strategy），走异常分支而非打印
        with pytest.raises(SystemExit):
            cli.acquisition_command(_args(acquisition_cmd="run", strategy_id=99999))

    def test_register_subparser_wires_all_subcommands(self) -> None:
        parser = argparse.ArgumentParser()
        cli.register_acquisition_subparser(parser.add_subparsers(dest="cmd"))
        for name in ("list", "run", "preview", "resume", "tick"):
            ns = parser.parse_args(
                [
                    "acquisition",
                    name,
                    *(
                        ["--strategy-id", "1"]
                        if name in ("run", "preview")
                        else ["--run-id", "1"]
                        if name == "resume"
                        else []
                    ),
                ]
            )
            assert ns.acquisition_cmd == name
