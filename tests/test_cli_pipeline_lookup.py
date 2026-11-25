"""`cndb pipeline tick` 与 `cndb lookup` 子命令的装配与输出（覆盖率补强）.

只验证 CLI 层：注册 / 分发 / 输出格式 / 失败退出码。真实扫描逻辑由
`tests/test_pipeline_*.py` 等覆盖。
"""

from __future__ import annotations

import argparse
import json

import pytest


def _pipeline_parser() -> argparse.ArgumentParser:
    from cndb.cli.pipeline import register_pipeline_subparser

    parser = argparse.ArgumentParser(prog="cndb")
    sub = parser.add_subparsers(dest="command")
    register_pipeline_subparser(sub)
    return parser


def test_pipeline_register_parses_tick_args():
    args = _pipeline_parser().parse_args(["pipeline", "tick", "--limit", "3", "--workspace-id", "2", "--json"])
    assert args.command == "pipeline"
    assert args.pipeline_cmd == "tick"
    assert args.limit == 3 and args.workspace_id == 2 and args.json is True


def test_pipeline_tick_prints_summary(monkeypatch, capsys):
    from cndb.cli import pipeline as cli

    monkeypatch.setattr(
        cli,
        "cmd_tick",
        lambda args: {
            "examined": 2,
            "executed": 1,
            "succeeded": 1,
            "failed": 0,
            "skipped_conflict": 1,
            "workflow_ids": [7],
        },
    )
    cli.pipeline_command(argparse.Namespace(pipeline_cmd="tick", limit=20, json=False))
    out = capsys.readouterr().out
    assert "到期 2，执行 1" in out
    assert "#7" in out


def test_pipeline_tick_json_and_failed_exit(monkeypatch, capsys):
    from cndb.cli import pipeline as cli

    payload = {"examined": 1, "executed": 1, "succeeded": 0, "failed": 1, "skipped_conflict": 0, "workflow_ids": []}
    monkeypatch.setattr(cli, "cmd_tick", lambda args: payload)
    with pytest.raises(SystemExit) as exc:
        cli.pipeline_command(argparse.Namespace(pipeline_cmd="tick", limit=20, json=True))
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out) == payload


def test_pipeline_missing_subcommand_exits_2(capsys):
    from cndb.cli import pipeline as cli

    with pytest.raises(SystemExit) as exc:
        cli.pipeline_command(argparse.Namespace(pipeline_cmd=None))
    assert exc.value.code == 2
    assert "缺少 pipeline 子命令" in capsys.readouterr().err


def test_pipeline_get_session_opens_configured_database(tmp_path, monkeypatch):
    from sqlalchemy import inspect, text

    from cndb.cli import pipeline as cli
    from cndb.core.config import settings

    target = tmp_path / "cli_pipeline.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{target}")
    db = cli._get_session()
    try:
        assert db.execute(text("select 1")).scalar() == 1
        assert inspect(db.bind).has_table("pipeline_workflow")
    finally:
        db.close()


class TestLookupCli:
    def _parser(self) -> argparse.ArgumentParser:
        from cndb.cli.lookup import register_lookup_subparser

        parser = argparse.ArgumentParser(prog="cndb")
        sub = parser.add_subparsers(dest="command")
        register_lookup_subparser(sub)
        return parser

    def test_register_and_parse(self):
        parser = self._parser()
        args = parser.parse_args(["lookup", "backfill", "--workspace", "1", "--json"])
        assert args.command == "lookup"
        assert args.lookup_cmd == "backfill"
        assert args.workspace == "1"
        assert args.json is True

    def test_missing_subcommand_exits_2(self, capsys):
        from cndb.cli import lookup as cli

        with pytest.raises(SystemExit) as exc:
            cli.lookup_command(argparse.Namespace(lookup_cmd=None))
        assert exc.value.code == 2
        assert "缺少 lookup 子命令" in capsys.readouterr().err

    def test_backfill_prints_and_exits_on_failures(self, monkeypatch, capsys):
        from cndb.cli import lookup as cli

        payload = {"tables": 2, "rows": 5, "failures": 1}
        monkeypatch.setattr(cli, "cmd_backfill", lambda args: payload)
        monkeypatch.setattr(cli, "_print_result", lambda p: print("human-summary"))
        with pytest.raises(SystemExit) as exc:
            cli.lookup_command(argparse.Namespace(lookup_cmd="backfill", json=False))
        assert exc.value.code == 1
        assert "human-summary" in capsys.readouterr().out

    def test_backfill_json_success(self, monkeypatch, capsys):
        from cndb.cli import lookup as cli

        payload = {"tables": 1, "rows": 3, "failures": 0}
        monkeypatch.setattr(cli, "cmd_backfill", lambda args: payload)
        cli.lookup_command(argparse.Namespace(lookup_cmd="backfill", json=True))
        assert json.loads(capsys.readouterr().out) == payload
