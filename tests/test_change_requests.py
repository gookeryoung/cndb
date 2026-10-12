"""表级变更单审批端到端测试：开关设置 / 三 op 分派 / 防叠加 / 落库冲突回滚."""

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


def _auth(client, user) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": user.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def owner(db):
    u = User(username="cr_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="ChangeReqWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def editor(db, ws):
    return _make_user(db, "cr_editor", WorkspaceRole.EDITOR, ws)


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="ChangeReqTable", owner_id=None)
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
    """单级审批链：start → a1(editor) → end."""
    headers = _auth(client, owner)
    r = client.post(
        f"{BASE.format(wid=ws.id)}/workflows",
        json={
            "name": "变更审批",
            "nodes": [
                {"key": "s", "name": "提交", "node_type": "start"},
                {"key": "a1", "name": "主管审批", "node_type": "approval", "approver_role": "editor"},
                {"key": "e", "name": "结束", "node_type": "end"},
            ],
            "edges": [
                {"source": "s", "target": "a1"},
                {"source": "a1", "target": "e"},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _rec_url(ws, table) -> str:
    return f"{BASE.format(wid=ws.id)}/tables/{table.id}/records"


def _patch_table_approval(client, ws, owner, table, workflow_id: int | None):
    """设置/清除表级编辑审批开关."""
    return client.patch(
        f"{BASE.format(wid=ws.id)}/tables/{table.id}",
        json={"edit_approval_workflow_id": workflow_id},
        headers=_auth(client, owner),
    )


@pytest.fixture
def workflow(client, ws, owner) -> dict:
    return _create_workflow(client, ws, owner)


def _seed_row(client, ws, table, headers) -> dict:
    """开关未开启时直接落库一行（作为变更单目标行）."""
    r = client.post(
        f"{_rec_url(ws, table)}",
        json={"values": {"姓名": "张三", "年龄": 30}},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _act(client, ws, instance_id: int, headers, action: str = "approve"):
    return client.post(
        f"{BASE.format(wid=ws.id)}/approvals/{instance_id}/{action}",
        json={"comment": ""},
        headers=headers,
    )


# ── 开关设置 ─────────────────────────────────────────────


class TestSwitchSetting:
    def test_set_switch(self, client, ws, owner, table, workflow):
        """设置 edit_approval_workflow_id → 表详情返回该字段."""
        r = _patch_table_approval(client, ws, owner, table, workflow["id"])
        assert r.status_code == 200, r.text
        assert r.json()["edit_approval_workflow_id"] == workflow["id"]

    def test_clear_switch(self, client, ws, owner, table, workflow):
        """置 NULL → 关闭审批，行为回到直编."""
        assert _patch_table_approval(client, ws, owner, table, workflow["id"]).status_code == 200
        r = _patch_table_approval(client, ws, owner, table, None)
        assert r.status_code == 200
        assert r.json()["edit_approval_workflow_id"] is None

    def test_invalid_workflow_400(self, client, ws, owner, table):
        """绑定不存在的审批流 → 400."""
        r = _patch_table_approval(client, ws, owner, table, 99999)
        assert r.status_code == 400
        assert "审批流" in r.json()["detail"]


# ── 新增分派 ─────────────────────────────────────────────


class TestDispatchCreate:
    def test_switch_off_creates_directly(self, client, ws, table, editor):
        """开关关闭：POST 直接落库（现状回归，AC-1）."""
        row = _seed_row(client, ws, table, _auth(client, editor))
        assert row["姓名"] == "张三"
        assert "approval" not in row

    def test_switch_on_submits_change_request(self, client, ws, owner, editor, table, workflow):
        """开关开启：POST 生成 create 变更单，不落库（AC-2/AC-4）."""
        assert _patch_table_approval(client, ws, owner, table, workflow["id"]).status_code == 200
        r = client.post(
            f"{_rec_url(ws, table)}",
            json={"values": {"姓名": "李四", "年龄": 25}},
            headers=_auth(client, editor),
        )
        assert r.status_code == 202, r.text
        approval = r.json()["approval"]
        assert approval["status"] == "pending"
        assert approval["op"] == "create"

        r = client.get(f"{_rec_url(ws, table)}", headers=_auth(client, editor))
        assert r.json()["total"] == 0

    def test_create_change_applies_on_approve(self, client, ws, owner, editor, table, workflow):
        """create 变更单审批通过 → 行落库（AC-4 通过分支）."""
        assert _patch_table_approval(client, ws, owner, table, workflow["id"]).status_code == 200
        headers = _auth(client, editor)
        approval = client.post(
            f"{_rec_url(ws, table)}",
            json={"values": {"姓名": "王五", "年龄": 40}},
            headers=headers,
        ).json()["approval"]

        r = _act(client, ws, approval["id"], headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
        assert r.json()["record_id"] is not None

        rows = client.get(f"{_rec_url(ws, table)}", headers=headers).json()
        assert rows["total"] == 1
        assert rows["rows"][0]["姓名"] == "王五"


# ── 编辑分派 ─────────────────────────────────────────────


class TestDispatchUpdate:
    def test_switch_off_updates_directly(self, client, ws, table, editor):
        """开关关闭：PATCH 直接落库（现状回归，AC-1）."""
        headers = _auth(client, editor)
        row = _seed_row(client, ws, table, headers)
        r = client.patch(
            f"{_rec_url(ws, table)}/{row['id']}",
            json={"values": {"年龄": 31}},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["年龄"] == 31
        assert "approval" not in r.json()

    def test_switch_on_submits_update(self, client, ws, owner, editor, table, workflow):
        """开关开启：PATCH 生成 update 变更单，原行值不变（AC-2/AC-3）."""
        headers = _auth(client, editor)
        row = _seed_row(client, ws, table, headers)
        assert _patch_table_approval(client, ws, owner, table, workflow["id"]).status_code == 200

        r = client.patch(
            f"{_rec_url(ws, table)}/{row['id']}",
            json={"values": {"年龄": 99}},
            headers=headers,
        )
        assert r.status_code == 202, r.text
        approval = r.json()["approval"]
        assert approval["op"] == "update"
        assert approval["status"] == "pending"

        cur = client.get(f"{_rec_url(ws, table)}/{row['id']}", headers=headers).json()
        assert cur["年龄"] == 30  # 原值未被修改

    def test_update_change_applies_on_approve(self, client, ws, owner, editor, table, workflow):
        """update 变更单审批通过 → 行更新且行解锁（AC-7）."""
        headers = _auth(client, editor)
        row = _seed_row(client, ws, table, headers)
        assert _patch_table_approval(client, ws, owner, table, workflow["id"]).status_code == 200

        approval = client.patch(
            f"{_rec_url(ws, table)}/{row['id']}",
            json={"values": {"年龄": 42}},
            headers=headers,
        ).json()["approval"]

        r = _act(client, ws, approval["id"], headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"

        cur = client.get(f"{_rec_url(ws, table)}/{row['id']}", headers=headers).json()
        assert cur["年龄"] == 42

    def test_reject_keeps_original(self, client, ws, owner, editor, table, workflow):
        """驳回 → 原行值不变（AC-7 拒绝分支）."""
        headers = _auth(client, editor)
        row = _seed_row(client, ws, table, headers)
        assert _patch_table_approval(client, ws, owner, table, workflow["id"]).status_code == 200

        approval = client.patch(
            f"{_rec_url(ws, table)}/{row['id']}",
            json={"values": {"年龄": 77}},
            headers=headers,
        ).json()["approval"]

        r = _act(client, ws, approval["id"], headers, action="reject")
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"

        cur = client.get(f"{_rec_url(ws, table)}/{row['id']}", headers=headers).json()
        assert cur["年龄"] == 30


# ── 删除分派 ─────────────────────────────────────────────


class TestDispatchDelete:
    def test_switch_on_submits_delete(self, client, ws, owner, editor, table, workflow):
        """开关开启：DELETE 生成 delete 变更单，行仍在（AC-5）."""
        headers = _auth(client, editor)
        row = _seed_row(client, ws, table, headers)
        assert _patch_table_approval(client, ws, owner, table, workflow["id"]).status_code == 200

        r = client.delete(f"{_rec_url(ws, table)}/{row['id']}", headers=headers)
        assert r.status_code == 202, r.text
        assert r.json()["approval"]["op"] == "delete"

        cur = client.get(f"{_rec_url(ws, table)}/{row['id']}", headers=headers).json()
        assert cur["年龄"] == 30  # 行未被删除

    def test_delete_change_applies_on_approve(self, client, ws, owner, editor, table, workflow):
        """delete 变更单审批通过 → 行软删进回收站（AC-5 通过分支）."""
        headers = _auth(client, editor)
        row = _seed_row(client, ws, table, headers)
        assert _patch_table_approval(client, ws, owner, table, workflow["id"]).status_code == 200

        approval = client.delete(f"{_rec_url(ws, table)}/{row['id']}", headers=headers).json()["approval"]
        r = _act(client, ws, approval["id"], headers)
        assert r.status_code == 200, r.text

        r = client.get(f"{_rec_url(ws, table)}", headers=headers)
        assert r.json()["total"] == 0

    def test_switch_off_deletes_directly(self, client, ws, table, editor):
        """开关关闭：DELETE 直接软删（现状回归，AC-1）."""
        headers = _auth(client, editor)
        row = _seed_row(client, ws, table, headers)
        r = client.delete(f"{_rec_url(ws, table)}/{row['id']}", headers=headers)
        assert r.status_code == 204


# ── 防叠加守卫 ───────────────────────────────────────────


class TestAntiStacking:
    def test_second_submission_409(self, client, ws, owner, editor, table, workflow):
        """同 row 已有 pending 变更单 → 再提交 409（AC-6 服务端）."""
        headers = _auth(client, editor)
        row = _seed_row(client, ws, table, headers)
        assert _patch_table_approval(client, ws, owner, table, workflow["id"]).status_code == 200

        r1 = client.patch(
            f"{_rec_url(ws, table)}/{row['id']}",
            json={"values": {"年龄": 50}},
            headers=headers,
        )
        assert r1.status_code == 202
        r2 = client.patch(
            f"{_rec_url(ws, table)}/{row['id']}",
            json={"values": {"年龄": 60}},
            headers=headers,
        )
        assert r2.status_code == 409
        assert "审批" in r2.json()["detail"]

    def test_after_reject_can_resubmit(self, client, ws, owner, editor, table, workflow):
        """驳回解锁后可再次提交新变更单."""
        headers = _auth(client, editor)
        row = _seed_row(client, ws, table, headers)
        assert _patch_table_approval(client, ws, owner, table, workflow["id"]).status_code == 200

        approval = client.patch(
            f"{_rec_url(ws, table)}/{row['id']}",
            json={"values": {"年龄": 50}},
            headers=headers,
        ).json()["approval"]
        assert _act(client, ws, approval["id"], headers, action="reject").status_code == 200

        r = client.patch(
            f"{_rec_url(ws, table)}/{row['id']}",
            json={"values": {"年龄": 51}},
            headers=headers,
        )
        assert r.status_code == 202


# ── 落库冲突回滚（AC-10）────────────────────────────────


class TestApplyConflictRollback:
    def test_apply_on_deleted_row_409(self, client, db, ws, owner, editor, table, workflow):
        """update 变更单审批时行已被硬删 → 409 且实例保持 pending（AC-10）."""
        from cndb.plugins.tables.services.core import records as rec

        headers = _auth(client, editor)
        row = _seed_row(client, ws, table, headers)
        assert _patch_table_approval(client, ws, owner, table, workflow["id"]).status_code == 200

        approval = client.patch(
            f"{_rec_url(ws, table)}/{row['id']}",
            json={"values": {"年龄": 88}},
            headers=headers,
        ).json()["approval"]

        # 模拟审批期间行被硬删（绕过软删）
        rec.delete_row(db.get_bind(), table, row["id"], db=db)

        r = _act(client, ws, approval["id"], headers)
        assert r.status_code == 409
        assert "已不存在" in r.json()["detail"]

        # 实例保持 pending（事务回滚），可由审批人驳回
        r = _act(client, ws, approval["id"], headers, action="reject")
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"


# ── 表单编辑分派（AC-8/AC-9）────────────────────────────


def _create_form(client, ws, table, owner) -> dict:
    r = client.post(
        f"{BASE.format(wid=ws.id)}/forms",
        json={
            "table_id": table.id,
            "name": "变更表单",
            "use_role": "viewer",
            "edit_role": "viewer",
            "field_config": [
                {"field_name": "姓名", "editable": True},
                {"field_name": "年龄", "editable": True},
            ],
        },
        headers=_auth(client, owner),
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestFormEditDispatch:
    def test_form_edit_submits_change_request(self, client, ws, owner, editor, table, workflow):
        """开关开启：表单编辑行同样提交变更单（AC-8）."""
        headers = _auth(client, editor)
        row = _seed_row(client, ws, table, headers)
        form = _create_form(client, ws, table, owner)
        assert _patch_table_approval(client, ws, owner, table, workflow["id"]).status_code == 200

        r = client.patch(
            f"{BASE.format(wid=ws.id)}/forms/{form['id']}/rows/{row['id']}",
            json={"values": {"年龄": 55}},
            headers=headers,
        )
        assert r.status_code == 202, r.text
        approval = r.json()["approval"]
        assert approval["op"] == "update"
        assert approval["status"] == "pending"

        cur = client.get(f"{_rec_url(ws, table)}/{row['id']}", headers=headers).json()
        assert cur["年龄"] == 30

    def test_form_edit_switch_off_direct(self, client, ws, owner, editor, table):
        """开关关闭：表单编辑行为与现状一致（AC-9）."""
        headers = _auth(client, editor)
        row = _seed_row(client, ws, table, headers)
        form = _create_form(client, ws, table, owner)

        r = client.patch(
            f"{BASE.format(wid=ws.id)}/forms/{form['id']}/rows/{row['id']}",
            json={"values": {"年龄": 33}},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["年龄"] == 33


# ── 在途变更查询（AC-6 前端数据源）──────────────────────


class TestPendingListByTable:
    def test_filter_by_table_id(self, client, ws, owner, editor, table, workflow):
        """list_approvals 支持 table_id 过滤，返回 op/row_id 供行锁定."""
        headers = _auth(client, editor)
        row = _seed_row(client, ws, table, headers)
        assert _patch_table_approval(client, ws, owner, table, workflow["id"]).status_code == 200
        approval = client.patch(
            f"{_rec_url(ws, table)}/{row['id']}",
            json={"values": {"年龄": 66}},
            headers=headers,
        ).json()["approval"]

        r = client.get(
            f"{BASE.format(wid=ws.id)}/approvals",
            params={"scope": "pending_for_me", "table_id": table.id},
            headers=headers,
        )
        assert r.status_code == 200
        items = r.json()
        assert [it["id"] for it in items] == [approval["id"]]
        assert items[0]["op"] == "update"
        assert items[0]["row_id"] == row["id"]

    def test_other_table_excluded(self, client, db, ws, owner, editor, table, workflow):
        """其他表的在途变更不出现在本表过滤结果中."""
        headers = _auth(client, editor)
        row = _seed_row(client, ws, table, headers)
        assert _patch_table_approval(client, ws, owner, table, workflow["id"]).status_code == 200
        client.patch(
            f"{_rec_url(ws, table)}/{row['id']}",
            json={"values": {"年龄": 66}},
            headers=headers,
        )

        r = client.get(
            f"{BASE.format(wid=ws.id)}/approvals",
            params={"scope": "pending_for_me", "table_id": table.id + 100},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json() == []


__all__ = []
