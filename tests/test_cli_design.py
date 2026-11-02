"""cndb design-refactor 子命令：分发 / 输出 / 退出码（ADR 0086 D8）."""

from __future__ import annotations

import argparse
import json

import pytest

from cndb.cli import design as cli
from cndb.plugins.design.services.refactor import RefactorEntry, RefactorReport


class _SessionProxy:
    """CLI 会 close()：包一层让测试 session 活到断言之后."""

    def __init__(self, db):
        self._db = db

    def close(self) -> None:
        return None

    def __getattr__(self, name):
        return getattr(self._db, name)


def _args(**kwargs):
    return argparse.Namespace(**kwargs)


@pytest.fixture()
def cli_session(monkeypatch, db):
    monkeypatch.setattr(cli, "_get_session", lambda: _SessionProxy(db))
    return db


def _report(**kwargs) -> RefactorReport:
    return RefactorReport(**kwargs)


class TestGetSession:
    def test_creates_design_tables_then_reuses(self, tmp_path, monkeypatch) -> None:
        from cndb.core.config import settings

        db_path = tmp_path / "design-cli.sqlite3"
        monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}", raising=False)

        first = cli._get_session()
        try:
            assert db_path.exists()
        finally:
            first.close()

        second = cli._get_session()
        try:
            from sqlalchemy import text

            assert second.execute(text("select count(*) from design_design")).scalar() == 0
        finally:
            second.close()


class TestCmdRefactor:
    def test_passes_flags_and_returns_dict(self, cli_session, monkeypatch) -> None:
        seen: dict[str, object] = {}

        def _run_refactor(_db, *, workspace_id=None, dry_run=False):
            seen.update(workspace_id=workspace_id, dry_run=dry_run)
            return _report(
                dry_run=dry_run,
                refactored=[RefactorEntry(design_id=1, title="装配", parts=["part-a"], version_number=2)],
            )

        monkeypatch.setattr("cndb.plugins.design.services.refactor.run_refactor", _run_refactor)
        payload = cli.cmd_refactor(_args(workspace_id=4, dry_run=True))
        assert seen == {"workspace_id": 4, "dry_run": True}
        assert payload["dry_run"] is True
        assert payload["refactored"][0]["parts"] == ["part-a"]

        # 缺省参数：workspace_id=None / dry_run=False
        cli.cmd_refactor(_args())
        assert seen == {"workspace_id": None, "dry_run": False}


class TestPrintReport:
    def test_lists_all_three_buckets(self, capsys) -> None:
        cli._print_report(
            {
                "dry_run": True,
                "refactored": [{"design_id": 1, "title": "装配", "parts": ["p1", "p2"]}],
                "skipped": [{"design_id": 2, "title": "已重构", "reason": "已重构过"}],
                "failed": [{"design_id": 3, "title": "坏设计", "error": "编译失败"}],
            }
        )
        out = capsys.readouterr().out
        assert "dry-run refactored=1 skipped=1 failed=1" in out
        assert "+ #1 装配 -> parts: p1, p2" in out
        assert "= #2 已重构 跳过：已重构过" in out
        assert "! #3 坏设计 失败：编译失败" in out

    def test_omits_dry_run_marker_when_false(self, capsys) -> None:
        cli._print_report({"dry_run": False, "refactored": [], "skipped": [], "failed": []})
        assert "[design-refactor] refactored=0" in capsys.readouterr().out


class TestDesignCommand:
    def test_json_output(self, cli_session, monkeypatch, capsys) -> None:
        monkeypatch.setattr(
            "cndb.plugins.design.services.refactor.run_refactor",
            lambda *_a, **_kw: _report(refactored=[RefactorEntry(design_id=1, title="装配", parts=["p"])]),
        )
        cli.design_command(_args(json=True))
        assert json.loads(capsys.readouterr().out)["refactored"][0]["design_id"] == 1

    def test_human_output(self, cli_session, monkeypatch, capsys) -> None:
        monkeypatch.setattr(
            "cndb.plugins.design.services.refactor.run_refactor",
            lambda *_a, **_kw: _report(failed=[RefactorEntry(design_id=9, title="坏", error="编译失败")]),
        )
        with pytest.raises(SystemExit) as exc:
            cli.design_command(_args())
        assert exc.value.code == 1
        assert "失败：编译失败" in capsys.readouterr().out

    def test_register_subparser(self) -> None:
        parser = argparse.ArgumentParser()
        cli.register_design_subparser(parser.add_subparsers(dest="cmd"))
        ns = parser.parse_args(["design-refactor", "--workspace-id", "2", "--dry-run", "--json"])
        assert ns.workspace_id == 2 and ns.dry_run is True and ns.json is True
