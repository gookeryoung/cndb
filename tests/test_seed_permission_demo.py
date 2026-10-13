"""权限演示 seed 数据单元测试（_seed_permission_demo）.

覆盖：
- 典型权限用户创建（perm_editor/perm_viewer/perm_review/perm_member）；
- 两个演示工作区的 allow_edit 与成员角色配置；
- 修改申请状态覆盖：open / merged / 同行合并后自动 stale；
- 问题清单登记（表成员授权边界 open、直编提示矛盾 closed）；
- 各演示用户写模式与工作区配置一致（seed 数据与 resolve_write_mode 互证）。
"""

from __future__ import annotations

import pytest

from cndb.plugins.change_requests import services as cr_services
from cndb.plugins.change_requests.models import CR_STATUS_MERGED, CR_STATUS_OPEN, ChangeRequest

USERNAME_PERM_DEMO = ("perm_editor", "perm_viewer", "perm_review", "perm_member")


@pytest.fixture
def perm_demo(db, db_engine):
    """端到端 fixture：建 owner 用户后执行 _seed_permission_demo，返回 (owner, 按名索引的工件)."""
    from cndb.cli.seed import _seed_permission_demo
    from cndb.plugins.accounts.models import User
    from cndb.plugins.issues.models import Issue
    from cndb.plugins.workspaces.models import Workspace

    owner = User(username="perm_seed_owner", email="pso@example.com", nickname="权限演示种子Owner")
    owner.set_password("passw0rd")
    db.add(owner)
    db.commit()
    db.refresh(owner)

    _seed_permission_demo(db, db_engine, owner)

    def _ws(name: str) -> Workspace:
        return db.query(Workspace).filter(Workspace.name == name).one()

    ws_open = _ws("权限演示-直编开放")
    ws_off = _ws("权限演示-直编关闭")
    return {
        "owner": owner,
        "ws_open": ws_open,
        "ws_off": ws_off,
        "issues": db.query(Issue).all(),
        "requests": db.query(ChangeRequest).all(),
    }


def _user(db, username: str):
    from cndb.plugins.accounts.models import User

    return db.query(User).filter(User.username == username).one()


def _table_of(db, ws):
    from cndb.plugins.tables.models import DataTable

    return db.query(DataTable).filter(DataTable.workspace_id == ws.id).one()


class TestPermissionDemoSeed:
    def test_demo_users_created(self, db, perm_demo) -> None:
        for username in USERNAME_PERM_DEMO:
            u = _user(db, username)
            assert u.check_password("perm1234")

    def test_workspace_allow_edit_config(self, perm_demo) -> None:
        assert perm_demo["ws_open"].allow_edit is True
        assert perm_demo["ws_off"].allow_edit is False

    def test_tables_have_three_rows(self, db, perm_demo) -> None:
        from cndb.plugins.tables.services.core import records as rec

        engine = db.get_bind()
        for ws in (perm_demo["ws_open"], perm_demo["ws_off"]):
            tbl = _table_of(db, ws)
            _rows, total = rec.list_rows(engine, tbl, db=db)
            assert total == 3

    def test_open_workshop_requests(self, db, perm_demo) -> None:
        """直编开放区：viewer 提交 2 条 open（update + delete）."""
        ws = perm_demo["ws_open"]
        viewer = _user(db, "perm_viewer")
        crs = db.query(ChangeRequest).filter(ChangeRequest.workspace_id == ws.id).all()
        assert [c.status for c in crs] == [CR_STATUS_OPEN, CR_STATUS_OPEN]
        assert all(c.submitted_by_id == viewer.id for c in crs)
        assert {c.title.split(" #")[0] for c in crs} == {"修改行", "删除行"}

    def test_closed_workshop_request_states(self, db, perm_demo) -> None:
        """直编关闭区：1 条 merged + 1 条 stale（同行合并触发）+ 1 条 open（create）."""
        ws = perm_demo["ws_off"]
        crs = db.query(ChangeRequest).filter(ChangeRequest.workspace_id == ws.id).all()
        statuses = sorted(c.status for c in crs)
        assert statuses == sorted([CR_STATUS_MERGED, CR_STATUS_OPEN, CR_STATUS_OPEN])
        stale = [c for c in crs if c.stale]
        assert len(stale) == 1
        assert stale[0].status == CR_STATUS_OPEN

    def test_member_write_grant_boundary(self, db, perm_demo) -> None:
        """perm_member：工作区 viewer + 表成员 write —— 写模式仍为 change_request（边界工况登记）."""
        from cndb.plugins.tables.models import TableMember

        ws = perm_demo["ws_off"]
        tbl = _table_of(db, ws)
        member = _user(db, "perm_member")
        tm = db.query(TableMember).filter(TableMember.table_id == tbl.id, TableMember.user_id == member.id).one()
        assert tm.role == "write"
        assert cr_services.resolve_write_mode(db, tbl, member) == "change_request"

    def test_write_modes_match_workspace_config(self, db, perm_demo) -> None:
        """各演示用户写模式与工作区配置一致（seed 与 resolve_write_mode 互证）."""
        tbl_open = _table_of(db, perm_demo["ws_open"])
        tbl_off = _table_of(db, perm_demo["ws_off"])
        assert cr_services.resolve_write_mode(db, tbl_open, _user(db, "perm_editor")) == "direct"
        assert cr_services.resolve_write_mode(db, tbl_open, _user(db, "perm_viewer")) == "change_request"
        assert cr_services.resolve_write_mode(db, tbl_open, perm_demo["owner"]) == "direct"
        assert cr_services.resolve_write_mode(db, tbl_off, _user(db, "perm_review")) == "change_request"

    def test_issues_registered(self, db, perm_demo) -> None:
        """问题清单：2 条，1 open（表成员授权边界）+ 1 closed（直编提示矛盾），各带评论."""
        issues = perm_demo["issues"]
        assert len(issues) == 2
        by_status = {i.status: i for i in issues}
        assert set(by_status) == {"open", "closed"}
        assert "表成员" in by_status["open"].title
        assert "修改申请" in by_status["closed"].title
