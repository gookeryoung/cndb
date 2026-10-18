"""修改申请写模式典型工况测试（自建数据，不依赖 seed）.

覆盖：
- 直编开放工作区（allow_edit=True）：viewer 提交的 update/delete 均生成 open 申请；
- 直编关闭工作区（allow_edit=False）：editor 也走申请轨道，同行合并后其余申请自动 stale；
- 工作区 viewer + 表成员 write：写模式仍为 change_request（边界工况登记）；
- 各角色写模式与工作区配置一致（与 resolve_write_mode 互证）；
- 问题清单登记（表成员授权边界 open、直编提示矛盾 closed，各带评论）。
"""

from __future__ import annotations

import datetime as _dt

import pytest

from cndb.plugins.change_requests import services as cr_services
from cndb.plugins.change_requests.models import CR_STATUS_MERGED, CR_STATUS_OPEN, ChangeItem, ChangeRequest

USERNAME_WORKFLOW = ("wf_editor", "wf_viewer", "wf_review", "wf_member")
PASSWORD = "wf1234"
WS_OPEN = "写模式-直编开放"
WS_OFF = "写模式-直编关闭"


def _make_user(db, username: str, nickname: str):
    from cndb.plugins.accounts.models import User

    u = User(username=username, nickname=nickname)
    u.set_password(PASSWORD)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_table(db, engine, ws, owner):
    """建一张 3 字段 3 行的表，返回 (table, row_ids)."""
    from cndb.plugins.tables.models import DataField, DataTable
    from cndb.plugins.tables.services.core.ddl import create_table
    from cndb.plugins.tables.services.core.records import create_row

    tbl = DataTable(workspace_id=ws.id, owner_id=owner.id, name="写模式演示表", description="写模式工况测试数据")
    tbl.ensure_db_name()
    db.add(tbl)
    db.commit()
    db.refresh(tbl)
    for idx, (fname, ftype) in enumerate([("名称", "text"), ("数量", "number"), ("备注", "text")]):
        f = DataField(table_id=tbl.id, name=fname, field_type=ftype, order=idx)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    create_table(engine, tbl)
    row_ids = []
    for values in [
        {"名称": "甲", "数量": 1, "备注": ""},
        {"名称": "乙", "数量": 2, "备注": ""},
        {"名称": "丙", "数量": 3, "备注": ""},
    ]:
        row = create_row(engine, tbl, values=values)
        assert row is not None
        row_ids.append(row["id"])
    return tbl, row_ids


@pytest.fixture
def workflow(db, db_engine):
    """自建写模式工况：4 个典型权限用户 + 直编开放/关闭两个工作区 + 申请与问题清单."""
    from cndb.plugins.issues.models import (
        ISSUE_ACTION_CREATED,
        ISSUE_CATEGORY_QUESTION,
        ISSUE_CATEGORY_SUGGESTION,
        ISSUE_STATUS_CLOSED,
        ISSUE_STATUS_OPEN,
        Issue,
        IssueComment,
        IssueEvent,
    )
    from cndb.plugins.tables.models import TableMember
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

    owner = _make_user(db, "wf_owner", "工况Owner")
    u_editor = _make_user(db, "wf_editor", "编辑者-直编工况")
    u_viewer = _make_user(db, "wf_viewer", "查看者-申请工况")
    u_review = _make_user(db, "wf_review", "编辑者-关闭直编工况")
    u_member = _make_user(db, "wf_member", "查看者+表成员授权边界")

    def _open_cr(table, user, op, row_id, values):
        return cr_services.create_dispatch_request(db, table, user, op, row_id, values)

    # 工作区 1：直编开放（editor 直接落库，viewer 自动生成申请）
    ws_open = Workspace(name=WS_OPEN, description="editor 直编直存 / viewer 走修改申请", created_by_id=owner.id)
    db.add(ws_open)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws_open.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.add(WorkspaceMember(workspace_id=ws_open.id, user_id=u_editor.id, role=WorkspaceRole.EDITOR))
    db.add(WorkspaceMember(workspace_id=ws_open.id, user_id=u_viewer.id, role=WorkspaceRole.VIEWER))
    db.commit()
    db.refresh(ws_open)
    tbl_open, rows_open = _make_table(db, db_engine, ws_open, owner)
    _open_cr(tbl_open, u_viewer, "update", rows_open[0], {"数量": 10})
    _open_cr(tbl_open, u_viewer, "delete", rows_open[2], {})

    # 工作区 2：直编关闭（editor 也走申请轨道）
    ws_off = Workspace(
        name=WS_OFF,
        description="allow_edit=False：editor 与 viewer 写路径均自动生成修改申请",
        created_by_id=owner.id,
        allow_edit=False,
    )
    db.add(ws_off)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws_off.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.add(WorkspaceMember(workspace_id=ws_off.id, user_id=u_review.id, role=WorkspaceRole.EDITOR))
    db.add(WorkspaceMember(workspace_id=ws_off.id, user_id=u_member.id, role=WorkspaceRole.VIEWER))
    db.commit()
    db.refresh(ws_off)
    tbl_off, rows_off = _make_table(db, db_engine, ws_off, owner)

    # 同行双申请 → merge 其一，另一个自动 stale
    cr_kept = _open_cr(tbl_off, u_review, "update", rows_off[0], {"数量": 100})
    cr_stale = _open_cr(tbl_off, u_review, "update", rows_off[0], {"数量": 200})
    kept_item = db.query(ChangeItem).filter(ChangeItem.request_id == cr_kept.id).first()
    cr_services.merge_request(db, cr_kept, tbl_off, owner, {kept_item.id: "apply"}, "同行合并后其余申请自动 stale")
    db.refresh(cr_stale)
    assert cr_stale.stale is True
    _open_cr(tbl_off, u_review, "create", None, {"名称": "丁", "数量": 4, "备注": ""})

    # 表成员授权边界工况：工作区 viewer + TableMember write（分派仅看工作区角色，仍走申请轨道）
    db.add(TableMember(table_id=tbl_off.id, user_id=u_member.id, role="write"))
    db.commit()

    # 问题清单：登记写模式相关已知问题与结论
    now = _dt.datetime.now(_dt.UTC)
    issue_open = Issue(
        workspace_id=ws_off.id,
        table_id=tbl_off.id,
        title="工作区 viewer 获得表成员 write 授权后，编辑仍走修改申请轨道",
        description="表成员 write 授权不参与写路径分派，与表级 write 授权预期不一致。",
        category=ISSUE_CATEGORY_QUESTION,
        status=ISSUE_STATUS_OPEN,
        created_by_id=u_member.id,
    )
    db.add(issue_open)
    db.flush()
    db.add(IssueEvent(issue_id=issue_open.id, action=ISSUE_ACTION_CREATED, actor_id=u_member.id, created_at=now))
    db.add(
        IssueComment(
            issue_id=issue_open.id,
            content="can_write_directly 仅判定工作区角色，表成员授权不参与分派。",
            created_by_id=owner.id,
        )
    )
    issue_closed = Issue(
        workspace_id=ws_open.id,
        table_id=tbl_open.id,
        title="owner 编辑表格未生成修改申请，新建申请提示与行为矛盾",
        description="申请页曾无条件提示『系统会自动生成修改申请』，但 owner 编辑直接落库。",
        category=ISSUE_CATEGORY_SUGGESTION,
        status=ISSUE_STATUS_CLOSED,
        created_by_id=u_viewer.id,
    )
    db.add(issue_closed)
    db.flush()
    db.add(IssueEvent(issue_id=issue_closed.id, action=ISSUE_ACTION_CREATED, actor_id=u_viewer.id, created_at=now))
    db.add(
        IssueComment(
            issue_id=issue_closed.id,
            content="已修复：申请列表返回 write_mode，列表与新建提示按模式适配。",
            created_by_id=owner.id,
        )
    )
    db.commit()

    return {
        "owner": owner,
        "ws_open": ws_open,
        "ws_off": ws_off,
        "tbl_open": tbl_open,
        "tbl_off": tbl_off,
        "issues": [issue_open, issue_closed],
    }


def _user(db, username: str):
    from cndb.plugins.accounts.models import User

    return db.query(User).filter(User.username == username).one()


class TestPermissionWorkflowScenario:
    def test_workflow_users_created(self, db, workflow) -> None:
        for username in USERNAME_WORKFLOW:
            assert _user(db, username).check_password(PASSWORD)

    def test_workspace_allow_edit_config(self, workflow) -> None:
        assert workflow["ws_open"].allow_edit is True
        assert workflow["ws_off"].allow_edit is False

    def test_tables_have_three_rows(self, db, workflow) -> None:
        from cndb.plugins.tables.services.core import records as rec

        engine = db.get_bind()
        for tbl in (workflow["tbl_open"], workflow["tbl_off"]):
            _rows, total = rec.list_rows(engine, tbl, db=db)
            assert total == 3

    def test_open_workshop_requests(self, db, workflow) -> None:
        """直编开放区：viewer 提交 2 条 open（update + delete）."""
        viewer = _user(db, "wf_viewer")
        crs = db.query(ChangeRequest).filter(ChangeRequest.workspace_id == workflow["ws_open"].id).all()
        assert [c.status for c in crs] == [CR_STATUS_OPEN, CR_STATUS_OPEN]
        assert all(c.submitted_by_id == viewer.id for c in crs)
        assert {c.title.split(" #")[0] for c in crs} == {"修改行", "删除行"}

    def test_closed_workshop_request_states(self, db, workflow) -> None:
        """直编关闭区：1 条 merged + 1 条 stale（同行合并触发）+ 1 条 open（create）."""
        crs = db.query(ChangeRequest).filter(ChangeRequest.workspace_id == workflow["ws_off"].id).all()
        assert sorted(c.status for c in crs) == sorted([CR_STATUS_MERGED, CR_STATUS_OPEN, CR_STATUS_OPEN])
        stale = [c for c in crs if c.stale]
        assert len(stale) == 1
        assert stale[0].status == CR_STATUS_OPEN

    def test_member_write_grant_boundary(self, db, workflow) -> None:
        """工作区 viewer + 表成员 write —— 写模式仍为 change_request（边界工况登记）."""
        from cndb.plugins.tables.models import TableMember

        tbl = workflow["tbl_off"]
        member = _user(db, "wf_member")
        tm = db.query(TableMember).filter(TableMember.table_id == tbl.id, TableMember.user_id == member.id).one()
        assert tm.role == "write"
        assert cr_services.resolve_write_mode(db, tbl, member) == "change_request"

    def test_write_modes_match_workspace_config(self, db, workflow) -> None:
        """各角色写模式与工作区配置一致."""
        tbl_open, tbl_off = workflow["tbl_open"], workflow["tbl_off"]
        assert cr_services.resolve_write_mode(db, tbl_open, _user(db, "wf_editor")) == "direct"
        assert cr_services.resolve_write_mode(db, tbl_open, _user(db, "wf_viewer")) == "change_request"
        assert cr_services.resolve_write_mode(db, tbl_open, workflow["owner"]) == "direct"
        assert cr_services.resolve_write_mode(db, tbl_off, _user(db, "wf_review")) == "change_request"

    def test_issues_registered(self, db, workflow) -> None:
        """问题清单：2 条，1 open（表成员授权边界）+ 1 closed（直编提示矛盾），各带评论."""
        issues = workflow["issues"]
        assert len(issues) == 2
        by_status = {i.status: i for i in issues}
        assert set(by_status) == {"open", "closed"}
        assert "表成员" in by_status["open"].title
        assert "修改申请" in by_status["closed"].title
