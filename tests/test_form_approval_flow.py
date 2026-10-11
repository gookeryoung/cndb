"""表单提交审批流端到端测试：提交分流 / 多级推进 / 落库 / 并发与权限."""

from __future__ import annotations

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

BASE = "/api/v1/workspaces/{wid}"


def _make_user(db, username: str, role: WorkspaceRole, ws: Workspace) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=role))
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def owner(db):
    u = User(username="ap_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="ApprovalWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def editor(db, ws):
    return _make_user(db, "ap_editor", WorkspaceRole.EDITOR, ws)


@pytest.fixture
def admin(db, ws):
    return _make_user(db, "ap_admin", WorkspaceRole.ADMIN, ws)


@pytest.fixture
def viewer(db, ws):
    return _make_user(db, "ap_viewer", WorkspaceRole.VIEWER, ws)


def _auth(client, user) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": user.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="ApprovalTable", owner_id=None)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for i, (name, ftype) in enumerate([("姓名", "text"), ("年龄", "number")]):
        df = DataField(table_id=dt.id, name=name, field_type=ftype, order=i)
        df.ensure_db_name()
        db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    return dt


def _create_workflow(client, ws, owner) -> dict:
    """两级审批链：start → a1(editor) → a2(admin) → end."""
    headers = _auth(client, owner)
    r = client.post(
        f"{BASE.format(wid=ws.id)}/workflows",
        json={
            "name": "两级审批",
            "nodes": [
                {"key": "s", "name": "提交", "node_type": "start"},
                {"key": "a1", "name": "主管审批", "node_type": "approval", "approver_role": "editor"},
                {"key": "a2", "name": "经理审批", "node_type": "approval", "approver_role": "admin"},
                {"key": "e", "name": "结束", "node_type": "end"},
            ],
            "edges": [
                {"source": "s", "target": "a1"},
                {"source": "a1", "target": "a2"},
                {"source": "a2", "target": "e"},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_form(client, ws, table, owner, workflow_id: int | None) -> dict:
    headers = _auth(client, owner)
    r = client.post(
        f"{BASE.format(wid=ws.id)}/forms",
        json={
            "table_id": table.id,
            "name": "审批表单",
            "use_role": "viewer",
            "edit_role": "viewer",
            "approval_workflow_id": workflow_id,
            "field_config": [
                {"field_name": "姓名", "editable": True},
                {"field_name": "年龄", "editable": True},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _submit(client, ws, form_id: int, headers: dict) -> dict:
    r = client.post(
        f"{BASE.format(wid=ws.id)}/forms/{form_id}/rows",
        json={"values": {"姓名": "张三", "年龄": 30}},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _act(client, ws, instance_id: int, headers: dict, action: str = "approve") -> object:
    return client.post(
        f"{BASE.format(wid=ws.id)}/approvals/{instance_id}/{action}",
        json={"comment": ""},
        headers=headers,
    )


@pytest.fixture
def bound_form(client, ws, table, owner):
    """已绑定两级审批流的表单."""
    wf = _create_workflow(client, ws, owner)
    return _create_form(client, ws, table, owner, wf["id"])


# ── 提交分流 ─────────────────────────────────────────────


class TestSubmitSplit:
    def test_bound_submit_enters_approval(self, client, ws, bound_form, editor):
        """绑定审批流时提交 → 返回 approval 快照且不落库."""
        resp = _submit(client, ws, bound_form["id"], _auth(client, editor))
        approval = resp["approval"]
        assert approval["status"] == "pending"
        assert approval["current_approver_role"] == "editor"
        assert approval["workflow_name"] == "两级审批"

        r = client.get(f"{BASE.format(wid=ws.id)}/forms/{bound_form['id']}/rows", headers=_auth(client, editor))
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_unbound_submit_creates_row(self, client, ws, table, owner, editor):
        """解绑审批流后提交 → 直接落库（原行为）."""
        form = _create_form(client, ws, table, owner, None)
        resp = _submit(client, ws, form["id"], _auth(client, editor))
        assert "approval" not in resp
        assert resp["姓名"] == "张三"

    def test_invalid_workflow_binding_400(self, client, ws, table, owner):
        """绑定不存在的审批流 → 400."""
        headers = _auth(client, owner)
        r = client.post(
            f"{BASE.format(wid=ws.id)}/forms",
            json={"table_id": table.id, "name": "坏绑定", "approval_workflow_id": 99999},
            headers=headers,
        )
        assert r.status_code == 400
        assert "审批流" in r.json()["detail"]


# ── 多级推进与落库 ───────────────────────────────────────


class TestApprovalChain:
    def test_full_chain_creates_record(self, client, ws, bound_form, editor, admin):
        """两级全通过 → approved + record_id 回写 + 数据落库."""
        inst = _submit(client, ws, bound_form["id"], _auth(client, editor))["approval"]
        iid = inst["id"]

        r = _act(client, ws, iid, _auth(client, editor))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending"
        assert r.json()["current_approver_role"] == "admin"

        # editor 不满足 admin 阈值
        r = _act(client, ws, iid, _auth(client, editor))
        assert r.status_code == 403

        r = _act(client, ws, iid, _auth(client, admin))
        assert r.status_code == 200, r.text
        final = r.json()
        assert final["status"] == "approved"
        assert final["record_id"] is not None

        r = client.get(f"{BASE.format(wid=ws.id)}/forms/{bound_form['id']}/rows", headers=_auth(client, admin))
        assert r.status_code == 200
        assert r.json()["total"] == 1
        assert r.json()["rows"][0]["姓名"] == "张三"

    def test_reject_no_record(self, client, ws, bound_form, editor, admin):
        """驳回 → rejected，数据不落库."""
        inst = _submit(client, ws, bound_form["id"], _auth(client, editor))["approval"]
        r = _act(client, ws, inst["id"], _auth(client, admin), action="reject")
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"

        r = client.get(f"{BASE.format(wid=ws.id)}/forms/{bound_form['id']}/rows", headers=_auth(client, admin))
        assert r.json()["total"] == 0

    def test_act_on_finished_409(self, client, ws, bound_form, editor, admin):
        """终态实例再审批 → 409."""
        inst = _submit(client, ws, bound_form["id"], _auth(client, editor))["approval"]
        assert _act(client, ws, inst["id"], _auth(client, admin), action="reject").status_code == 200
        r = _act(client, ws, inst["id"], _auth(client, admin))
        assert r.status_code == 409

    def test_non_member_403(self, client, db, ws, bound_form, editor):
        """非工作区成员无法审批 → 403."""
        outsider = User(username="ap_outsider", nickname="外人")
        outsider.set_password("passw0rd")
        db.add(outsider)
        db.commit()
        db.refresh(outsider)
        inst = _submit(client, ws, bound_form["id"], _auth(client, editor))["approval"]
        r = _act(client, ws, inst["id"], _auth(client, outsider))
        assert r.status_code == 403


# ── 待办/我提交的列表 ────────────────────────────────────


class TestApprovalLists:
    def test_pending_for_me_and_mine(self, client, ws, bound_form, editor, admin, viewer):
        """待我审批按角色阈值过滤；mine 按提交人过滤."""
        inst = _submit(client, ws, bound_form["id"], _auth(client, editor))["approval"]
        base = f"{BASE.format(wid=ws.id)}/approvals"

        r = client.get(base, params={"scope": "pending_for_me"}, headers=_auth(client, editor))
        assert r.status_code == 200
        assert [it["id"] for it in r.json()] == [inst["id"]]

        r = client.get(base, params={"scope": "pending_for_me"}, headers=_auth(client, viewer))
        assert r.status_code == 200
        assert r.json() == []

        r = client.get(base, params={"scope": "mine"}, headers=_auth(client, editor))
        assert [it["id"] for it in r.json()] == [inst["id"]]

        r = client.get(base, params={"scope": "mine"}, headers=_auth(client, admin))
        assert r.json() == []


__all__ = []
