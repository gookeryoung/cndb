"""cndb views CLI 测试：孤儿视图体检 / 回收命令.

测试策略与 ``test_cli_docs.py`` 一致：直接调用 ``cli.views`` 的函数（不走 subprocess），
用 tmp_path 建临时 SQLite 文件 —— CLI 每次自建 engine，必须落在**文件库**上才能看到
测试写入的数据（内存库在另一个连接里是空的）。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from cndb.core.config import settings


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch) -> Path:
    """临时 SQLite 文件库（settings.DATABASE_URL）+ 一份最小可用数据."""
    from sqlalchemy import create_engine

    import cndb.plugins.accounts.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401
    from cndb.models.base import Base

    db_path = tmp_path / "cli_views.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    engine.dispose()
    return db_path


def _ns(**kwargs: Any) -> argparse.Namespace:
    ns = argparse.Namespace()
    for key, value in kwargs.items():
        setattr(ns, key, value)
    return ns


def _seed(db_path: Path) -> dict[str, int]:
    """建 工作区/表/用户 + 三类视图，返回关键 id.

    孤儿夹具：``离职视角`` 的 ``owner_id`` 直接置空（= 账号已删除后的落库状态）；
    另有 ``他组视角`` 的创建者被移出工作区（= 离开工作区的情形）。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from cndb.plugins.accounts.models import User
    from cndb.plugins.tables.models import DataField, DataTable, DataView, ViewVisibility
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session = sessionmaker(bind=engine)()
    try:
        owner = User(username="v_owner", email="v_owner@example.com")
        owner.set_password("pw")
        session.add(owner)
        session.flush()

        ws = Workspace(name="VWS", created_by_id=owner.id)
        session.add(ws)
        session.flush()
        session.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER))

        leaver = User(username="v_leaver", email="v_leaver@example.com")
        leaver.set_password("pw")
        session.add(leaver)
        session.flush()
        session.add(WorkspaceMember(workspace_id=ws.id, user_id=leaver.id, role=WorkspaceRole.VIEWER))

        dt = DataTable(workspace_id=ws.id, name="VTable", owner_id=owner.id)
        dt.ensure_db_name()
        session.add(dt)
        session.flush()
        df = DataField(table_id=dt.id, name="姓名", field_type="text", order=0)
        df.ensure_db_name()
        session.add(df)

        def _view(name: str, *, visibility: str, owner_id: int | None, scope: int) -> int:
            dv = DataView(
                table_id=dt.id,
                name=name,
                view_type="grid",
                visibility=visibility,
                scope_key=scope,
                owner_id=owner_id,
            )
            session.add(dv)
            session.flush()
            return int(dv.id)

        ids = {
            "ws": int(ws.id),
            "table": int(dt.id),
            "leaver": int(leaver.id),
            "deleted_view": _view("离职视角", visibility=ViewVisibility.PRIVATE, owner_id=None, scope=99),
            "leaver_view": _view(
                "他组视角", visibility=ViewVisibility.PRIVATE, owner_id=int(leaver.id), scope=int(leaver.id)
            ),
            "table_view": _view("全部", visibility=ViewVisibility.TABLE, owner_id=int(owner.id), scope=0),
        }
        session.commit()
        return ids
    finally:
        session.close()


def _delete_workspace_member(db_path: Path, workspace_id: int, user_id: int) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from cndb.plugins.workspaces.models import WorkspaceMember

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session = sessionmaker(bind=engine)()
    try:
        row = (
            session.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
            .first()
        )
        if row is not None:
            session.delete(row)
            session.commit()
    finally:
        session.close()


class TestCmdPruneOrphans:
    def test_dry_run_lists_without_deleting(self, cli_env, capsys):
        from cndb.cli.views import cmd_prune_orphans, views_command

        ids = _seed(cli_env)
        payload = cmd_prune_orphans(_ns(workspace=str(ids["ws"]), table=None, apply=False))

        assert payload["dry_run"] is True
        assert payload["workspace"] == {"id": ids["ws"], "name": "VWS"}
        assert payload["table"] is None
        assert payload["removed"] == []
        assert {o["name"] for o in payload["orphans"]} == {"离职视角"}, "他组视角的创建者仍是工作区成员，不是孤儿"
        assert payload["orphans"][0]["table_name"] == "VTable"
        assert payload["orphans"][0]["created_at"], "应输出创建时间供人工核对"

        views_command(_ns(views_cmd="prune-orphans", workspace=str(ids["ws"]), table=None, apply=False, json=False))
        out = capsys.readouterr().out
        assert "[views prune-orphans]" in out and "dry-run" in out and "--apply" in out

        # 库中仍在
        payload2 = cmd_prune_orphans(_ns(workspace=str(ids["ws"]), table=None, apply=False))
        assert len(payload2["orphans"]) == 1

    def test_workspace_name_and_table_scope(self, cli_env):
        from cndb.cli.views import cmd_prune_orphans

        ids = _seed(cli_env)
        by_name = cmd_prune_orphans(_ns(workspace="VWS", table="VTable", apply=False))
        assert by_name["table"] == {"id": ids["table"], "name": "VTable"}
        assert len(by_name["orphans"]) == 1

    def test_apply_deletes_orphans_only(self, cli_env):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from cndb.cli.views import cmd_prune_orphans, find_orphan_views
        from cndb.plugins.tables.models import DataView

        ids = _seed(cli_env)
        _delete_workspace_member(cli_env, ids["ws"], ids["leaver"])  # 创建者离开 → 两个都成孤儿
        payload = cmd_prune_orphans(_ns(workspace=str(ids["ws"]), table=None, apply=True))

        assert payload["dry_run"] is False
        assert set(payload["removed"]) == {ids["deleted_view"], ids["leaver_view"]}

        engine = create_engine(f"sqlite:///{cli_env}", connect_args={"check_same_thread": False})
        session = sessionmaker(bind=engine)()
        try:
            assert session.get(DataView, ids["deleted_view"]) is None
            assert session.get(DataView, ids["table_view"]) is not None, "table 档视图不是孤儿，不得被删"
            assert find_orphan_views(session, ids["ws"]) == []
        finally:
            session.close()

    def test_owner_leaving_workspace_marks_orphan(self, cli_env):
        from cndb.cli.views import cmd_prune_orphans

        ids = _seed(cli_env)
        _delete_workspace_member(cli_env, ids["ws"], ids["leaver"])

        payload = cmd_prune_orphans(_ns(workspace=str(ids["ws"]), table=None, apply=False))
        reasons = {o["name"]: o["reason"] for o in payload["orphans"]}
        assert reasons["他组视角"] == "创建者已不在该工作区"
        assert reasons["离职视角"] == "创建者已注销"

    def test_json_output_is_parseable(self, cli_env, capsys):
        from cndb.cli.views import views_command

        ids = _seed(cli_env)
        views_command(_ns(views_cmd="prune-orphans", workspace=str(ids["ws"]), table=None, apply=False, json=True))
        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is True
        assert len(payload["orphans"]) == 1

    def test_unknown_workspace_exits(self, cli_env):
        from cndb.cli.views import cmd_prune_orphans

        _seed(cli_env)
        with pytest.raises(SystemExit) as exc:
            cmd_prune_orphans(_ns(workspace="不存在的名字", table=None, apply=False))
        assert "不存在" in str(exc.value)

        with pytest.raises(SystemExit):
            cmd_prune_orphans(_ns(workspace="999999", table=None, apply=False))


class TestViewsCommandDispatch:
    def test_plain_output_lists_orphans(self, capsys):
        from cndb.cli.views import _print_prune

        _print_prune(
            {
                "workspace": {"id": 1, "name": "W"},
                "table": {"id": 2, "name": "T"},
                "dry_run": True,
                "orphans": [
                    {
                        "id": 9,
                        "name": "离职视角",
                        "table_id": 2,
                        "table_name": "T",
                        "owner_id": None,
                        "scope_key": 7,
                        "reason": "创建者已注销",
                        "created_at": "2026-10-16 10:00:00",
                        "updated_at": "2026-10-16 11:00:00",
                    }
                ],
                "removed": [],
            }
        )
        out = capsys.readouterr().out
        assert "孤儿视图 1 个" in out and "创建者已注销" in out and "--apply" in out

    def test_missing_subcommand_exits(self, capsys):
        from cndb.cli.views import views_command

        with pytest.raises(SystemExit) as exc:
            views_command(_ns(views_cmd=None))
        assert exc.value.code == 2
        assert "缺少 views 子命令" in capsys.readouterr().err

    def test_parser_registers_options(self):
        from cndb.cli.views import register_views_subparser

        parser = argparse.ArgumentParser(prog="cndb")
        sub = parser.add_subparsers(dest="command")
        register_views_subparser(sub)

        args = parser.parse_args(["views", "prune-orphans", "--workspace", "3", "--table", "T", "--apply", "--json"])
        assert args.command == "views" and args.views_cmd == "prune-orphans"
        assert args.workspace == "3" and args.table == "T"
        assert args.apply is True and args.json is True

        plain = parser.parse_args(["views", "prune-orphans", "--workspace", "3"])
        assert plain.apply is False and plain.dry_run is False and plain.table is None
