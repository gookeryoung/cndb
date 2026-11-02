"""ADR 0020 P3：`cndb llm` CLI（test / runs / prune）."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cndb.cli import llm as llm_cli
from cndb.core.config import settings
from cndb.plugins.accounts.models import User
from cndb.plugins.llm.models import LlmRun, LlmUserConfig


@pytest.fixture
def cli_db(tmp_path: Path, monkeypatch) -> Session:
    """临时 SQLite（settings.DATABASE_URL）+ 已建表 session."""
    import cndb.plugins.accounts.models
    import cndb.plugins.llm.models  # noqa: F401
    from cndb.models.base import Base

    db_path = tmp_path / "cli_llm.db"
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


def _add_user(db: Session, username: str = "llm_cli_user") -> User:
    user = User(username=username, nickname=username)
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestRuns:
    def test_lists_runs_and_filters(self, cli_db, capsys):
        user = _add_user(cli_db)
        cli_db.add_all(
            [
                LlmRun(user_id=user.id, action="document.polish", status="success", model="m", total_tokens=10),
                LlmRun(user_id=user.id, action="table.fill_field", status="failed", model="m", total_tokens=0),
            ]
        )
        cli_db.commit()
        payload = llm_cli.cmd_runs(_ns(user="llm_cli_user", action=None, status=None, limit=10))
        assert payload["total"] == 2
        assert {item["action"] for item in payload["items"]} == {"document.polish", "table.fill_field"}

        failed = llm_cli.cmd_runs(_ns(user=None, action=None, status="failed", limit=10))
        assert len(failed["items"]) == 1
        assert failed["items"][0]["action"] == "table.fill_field"
        # 人类可读输出
        llm_cli._print_runs(payload)
        assert "共 2 条" in capsys.readouterr().out

    def test_limit_clamped(self, cli_db):
        user = _add_user(cli_db)
        cli_db.add(LlmRun(user_id=user.id, action="document.polish", status="success", model="m"))
        cli_db.commit()
        payload = llm_cli.cmd_runs(_ns(user=None, action=None, status=None, limit=9999))
        assert len(payload["items"]) == 1


class TestPrune:
    def test_dry_run_then_delete(self, cli_db):
        user = _add_user(cli_db)
        old = dt.datetime.now(dt.UTC) - dt.timedelta(days=200)
        cli_db.add_all(
            [
                LlmRun(user_id=user.id, action="document.polish", status="success", model="m", created_at=old),
                LlmRun(user_id=user.id, action="document.polish", status="success", model="m"),
            ]
        )
        cli_db.commit()

        dry = llm_cli.cmd_prune(_ns(days=90, dry_run=True))
        assert dry["matched"] == 1
        assert dry["deleted"] == 0
        assert cli_db.query(LlmRun).count() == 2

        real = llm_cli.cmd_prune(_ns(days=90, dry_run=False))
        assert real["matched"] == 1
        assert real["deleted"] == 1
        assert cli_db.query(LlmRun).count() == 1


class TestTestCommand:
    def test_reports_connection_result(self, cli_db, monkeypatch):
        user = _add_user(cli_db)
        cli_db.add(
            LlmUserConfig(
                user_id=user.id,
                base_url="https://llm.example.com",
                model="model-a",
                api_key="enc:v1:fake",
                system_prompt="",
            )
        )
        cli_db.commit()

        from cndb.plugins.llm.services import client as llm_client

        monkeypatch.setattr(
            llm_client,
            "test_connection",
            lambda _connection: llm_client.LlmConnectionResult(
                ok=True, latency_ms=12, model="model-a", message="连通成功"
            ),
        )
        payload = llm_cli.cmd_test(_ns(user="llm_cli_user"))
        assert payload["ok"] is True
        assert payload["latency_ms"] == 12
        assert payload["model"] == "model-a"

    def test_missing_user_stops(self, cli_db):
        with pytest.raises(SystemExit):
            llm_cli.cmd_test(_ns(user="nobody"))


class TestDispatch:
    def test_command_requires_subcommand(self):
        with pytest.raises(SystemExit) as exc:
            llm_cli.llm_command(_ns(llm_cmd=None))
        assert exc.value.code == 2

    def test_json_dispatch(self, cli_db, capsys):
        payload = llm_cli.cmd_runs(_ns(user=None, action=None, status=None, limit=5))
        assert json.dumps(payload, ensure_ascii=False, default=str)


class TestResolveUserBranches:
    def test_no_users_stops(self, cli_db):
        with pytest.raises(SystemExit):
            llm_cli._resolve_user(cli_db, None)

    def test_multiple_users_require_flag(self, cli_db):
        _add_user(cli_db, "llm_cli_a")
        _add_user(cli_db, "llm_cli_b")
        with pytest.raises(SystemExit):
            llm_cli._resolve_user(cli_db, None)
        # 指定用户名时取该用户
        user = llm_cli._resolve_user(cli_db, "llm_cli_b")
        assert user.username == "llm_cli_b"

    def test_unknown_username_stops(self, cli_db):
        _add_user(cli_db)
        with pytest.raises(SystemExit):
            llm_cli._resolve_user(cli_db, "nobody")


class TestRunsFiltersAndPrint:
    def test_action_filter_and_user_scope(self, cli_db, capsys):
        user = _add_user(cli_db)
        cli_db.add_all(
            [
                LlmRun(user_id=user.id, action="document.polish", status="success", model="m", total_tokens=10),
                LlmRun(user_id=user.id, action="table.fill_field", status="failed", model=None),
            ]
        )
        cli_db.commit()

        payload = llm_cli.cmd_runs(_ns(user="llm_cli_user", action="document.polish", status=None, limit=10))
        assert [item["action"] for item in payload["items"]] == ["document.polish"]
        assert payload["user"] == "llm_cli_user"

        llm_cli._print_runs(payload)
        out = capsys.readouterr().out
        assert "用户 llm_cli_user" in out
        assert "tokens=10" in out

    def test_print_runs_all_users_and_error(self, capsys):
        llm_cli._print_runs(
            {
                "user": None,
                "total": 1,
                "items": [
                    {
                        "id": 1,
                        "action": "document.polish",
                        "status": "failed",
                        "model": None,
                        "total_tokens": None,
                        "latency_ms": 0,
                        "created_at": "2026-11-02T09:00:00",
                        "error": "鉴权失败",
                    }
                ],
            }
        )
        out = capsys.readouterr().out
        assert "全部用户" in out
        assert "! 鉴权失败" in out


class TestPruneGuards:
    def test_days_must_be_positive(self, cli_db):
        with pytest.raises(SystemExit):
            llm_cli.cmd_prune(_ns(days=-1, dry_run=True))

    def test_print_prune(self, capsys):
        llm_cli._print_prune(
            {
                "days": 30,
                "cutoff": "2026-10-03T00:00:00+00:00",
                "matched": 2,
                "deleted": 2,
            }
        )
        assert "保留 30 天" in capsys.readouterr().out


class TestDispatchVariants:
    def test_test_command_failure_exits_1(self, cli_db, monkeypatch, capsys):
        user = _add_user(cli_db)
        cli_db.add(
            LlmUserConfig(
                user_id=user.id,
                base_url="https://llm.example.com",
                model="model-a",
                api_key="enc:v1:fake",
                system_prompt="",
            )
        )
        cli_db.commit()

        from cndb.plugins.llm.services import client as llm_client

        monkeypatch.setattr(
            llm_client,
            "test_connection",
            lambda _c: llm_client.LlmConnectionResult(
                ok=False,
                latency_ms=3,
                model="model-a",
                message="401 未授权",
            ),
        )
        with pytest.raises(SystemExit) as exc:
            llm_cli.llm_command(_ns(llm_cmd="test", user="llm_cli_user"))
        assert exc.value.code == 1
        assert "失败" in capsys.readouterr().out

    def test_test_command_json_success(self, cli_db, monkeypatch, capsys):
        user = _add_user(cli_db)
        cli_db.add(
            LlmUserConfig(
                user_id=user.id,
                base_url="https://llm.example.com",
                model="model-a",
                api_key="enc:v1:fake",
                system_prompt="",
            )
        )
        cli_db.commit()
        from cndb.plugins.llm.services import client as llm_client

        monkeypatch.setattr(
            llm_client,
            "test_connection",
            lambda _c: llm_client.LlmConnectionResult(ok=True, latency_ms=1, model="m", message="ok"),
        )
        llm_cli.llm_command(_ns(llm_cmd="test", user="llm_cli_user", json=True))
        assert json.loads(capsys.readouterr().out)["ok"] is True

    def test_prune_human_output(self, cli_db, capsys):
        llm_cli.llm_command(_ns(llm_cmd="prune", days=30, dry_run=True))
        assert "[llm prune]" in capsys.readouterr().out

    def test_register_subparser(self):
        parser = argparse.ArgumentParser()
        llm_cli.register_llm_subparser(parser.add_subparsers(dest="cmd"))
        assert parser.parse_args(["llm", "runs", "--limit", "5"]).llm_cmd == "runs"
        assert parser.parse_args(["llm", "prune", "--days", "7"]).days == 7
