"""`cndb link` 子命令（ADR 0154 D10）单测：注册 / 分发 / 输出.

只验证 CLI 装配与输出格式；清扫逻辑本身由 ``tests/test_link_sweep.py`` 覆盖。
"""

from __future__ import annotations

import argparse
import json

import pytest


def _parser() -> argparse.ArgumentParser:
    from cndb.cli.link import register_link_subparser

    parser = argparse.ArgumentParser(prog="cndb")
    sub = parser.add_subparsers(dest="command")
    register_link_subparser(sub)
    return parser


def test_register_parses_sweep_args():
    parser = _parser()
    args = parser.parse_args(["link", "sweep", "--limit", "5", "--json"])
    assert args.command == "link"
    assert args.link_cmd == "sweep"
    assert args.limit == 5
    assert args.json is True


def test_link_command_prints_json(monkeypatch, capsys):
    from cndb.cli import link as link_cli

    payload = {"expired": 2, "details": [{"link_id": 7, "removed_members": 3}]}
    monkeypatch.setattr(link_cli, "cmd_sweep", lambda args: payload)

    link_cli.link_command(argparse.Namespace(link_cmd="sweep", limit=200, json=True))
    printed = capsys.readouterr().out
    assert json.loads(printed) == payload


def test_link_command_prints_human_summary(monkeypatch, capsys):
    from cndb.cli import link as link_cli

    monkeypatch.setattr(
        link_cli,
        "cmd_sweep",
        lambda args: {"expired": 1, "details": [{"link_id": 3, "removed_members": 2}]},
    )
    link_cli.link_command(argparse.Namespace(link_cmd="sweep", limit=200, json=False))
    out = capsys.readouterr().out
    assert "过期链接 1 条" in out
    assert "link 3: 回收成员 2 个" in out


def test_print_sweep_empty(monkeypatch, capsys):
    from cndb.cli import link as link_cli

    monkeypatch.setattr(link_cli, "cmd_sweep", lambda args: {"expired": 0, "details": []})
    link_cli.link_command(argparse.Namespace(link_cmd="sweep", limit=200, json=False))
    out = capsys.readouterr().out
    assert "（无）" in out


def test_get_session_opens_configured_database(tmp_path, monkeypatch):
    """`_get_session` 按 settings.DATABASE_URL 打开库；缺表时自愈建表."""
    from sqlalchemy import text

    from cndb.cli import link as link_cli
    from cndb.core.config import settings

    target = tmp_path / "cli_link.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{target}")
    db = link_cli._get_session()
    try:
        assert db.execute(text("select 1")).scalar() == 1
        from sqlalchemy import inspect

        assert inspect(db.bind).has_table("workspaces_workspacelink")
    finally:
        db.close()


def test_missing_subcommand_exits_2(capsys):
    from cndb.cli import link as link_cli

    with pytest.raises(SystemExit) as exc:
        link_cli.link_command(argparse.Namespace(link_cmd=None))
    assert exc.value.code == 2
    assert "缺少 link 子命令" in capsys.readouterr().err


def test_unknown_subcommand_exits_2(capsys):
    from cndb.cli import link as link_cli

    with pytest.raises(SystemExit) as exc:
        link_cli.link_command(argparse.Namespace(link_cmd="nope"))
    assert exc.value.code == 2
    assert "未知 link 子命令" in capsys.readouterr().err
