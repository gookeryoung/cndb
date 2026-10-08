"""数据治理 API 测试：任务创建 / 进度轮询 / 报告 / 权限 403（plan 步骤 11）。"""

from __future__ import annotations

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core.records import bulk_create
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

GOV = "/api/v1/workspaces/{ws}/tables/{tb}/governance"


@pytest.fixture
def owner(db):
    u = User(username="gov_api_owner", nickname="GovApiOwner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth_owner(client, owner):
    r = client.post("/api/v1/accounts/auth/login", json={"login": owner.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="GovApiWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def editor(db, ws):
    u = User(username="gov_api_editor", nickname="GovApiEditor")
    u.set_password("passw0rd")
    db.add(u)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.EDITOR))
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth_editor(client, editor):
    r = client.post("/api/v1/accounts/auth/login", json={"login": editor.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def dup_table(db, ws):
    """共享引擎上的物理表 + 2 行重复数据."""
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="GovApiTable")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for fname, ftype in [("姓名", "text"), ("城市", "text")]:
        f = DataField(table_id=dt.id, name=fname, field_type=ftype)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    bulk_create(engine, dt, [{"姓名": "张三", "城市": None}, {"姓名": "张三", "城市": "北京"}], db=db)
    return dt


class TestGovernanceDetectAPI:
    def test_detect_creates_task_and_completes(self, client, ws, dup_table, auth_owner) -> None:
        r = client.post(
            GOV.format(ws=ws.id, tb=dup_table.id) + "/detect",
            json={"match_fields": ["姓名"]},
            headers=auth_owner,
        )
        assert r.status_code in (200, 201)
        body = r.json()
        assert body["kind"] == "detect"
        assert body["status"] in ("pending", "running", "done")

        # 轮询（测试中后台任务同步执行，此时应已完成）
        rid = client.get(
            GOV.format(ws=ws.id, tb=dup_table.id) + f"/tasks/{body['id']}",
            headers=auth_owner,
        )
        assert rid.status_code == 200
        task = rid.json()
        assert task["status"] == "done"
        assert task["total_groups"] == 1

        # 报告
        rr = client.get(
            GOV.format(ws=ws.id, tb=dup_table.id) + f"/tasks/{body['id']}/report",
            headers=auth_owner,
        )
        assert rr.status_code == 200
        report = rr.json()["report"]
        assert report["group_count"] == 1
        assert report["groups"][0]["match_key_values"] == {"姓名": "张三"}

    def test_detect_invalid_field_400(self, client, ws, dup_table, auth_owner) -> None:
        r = client.post(
            GOV.format(ws=ws.id, tb=dup_table.id) + "/detect",
            json={"match_fields": []},
            headers=auth_owner,
        )
        assert r.status_code == 422  # Pydantic 校验

    def test_second_active_task_400(self, client, ws, dup_table, auth_owner, monkeypatch) -> None:
        # 会话级 fixture 会让任务同步完成，这里将后台执行替换为 no-op，
        # 让第一个任务保持 pending 以触发同表活跃任务互斥
        import cndb.plugins.tables.routers.governance as governance_router

        monkeypatch.setattr(governance_router, "run_governance_task_in_background", lambda *a, **kw: None)
        payload = {"match_fields": ["姓名"]}
        url = GOV.format(ws=ws.id, tb=dup_table.id) + "/detect"
        client.post(url, json=payload, headers=auth_owner)
        r2 = client.post(url, json=payload, headers=auth_owner)
        assert r2.status_code == 400


class TestGovernanceMergeAPI:
    def test_merge_flow(self, client, ws, dup_table, auth_owner) -> None:
        r = client.post(
            GOV.format(ws=ws.id, tb=dup_table.id) + "/merge",
            json={
                "match_fields": ["姓名"],
                "groups": [{"member_row_ids": [1, 2], "survivor_row_id": 1}],
            },
            headers=auth_owner,
        )
        assert r.status_code in (200, 201)
        task_id = r.json()["id"]
        rid = client.get(
            GOV.format(ws=ws.id, tb=dup_table.id) + f"/tasks/{task_id}",
            headers=auth_owner,
        )
        assert rid.json()["status"] == "done"
        rr = client.get(
            GOV.format(ws=ws.id, tb=dup_table.id) + f"/tasks/{task_id}/report",
            headers=auth_owner,
        )
        assert rr.status_code == 200
        assert rr.json()["report"]["merged_count"] == 1

    def test_merge_bad_group_400(self, client, ws, dup_table, auth_owner) -> None:
        r = client.post(
            GOV.format(ws=ws.id, tb=dup_table.id) + "/merge",
            json={"groups": [{"member_row_ids": [1], "survivor_row_id": 1}]},
            headers=auth_owner,
        )
        assert r.status_code == 422


class TestGovernanceCleanAPI:
    def test_clean_preview_then_execute(self, client, ws, dup_table, auth_owner) -> None:
        url = GOV.format(ws=ws.id, tb=dup_table.id) + "/clean"
        actions = [{"action": "fill_null", "column": "城市", "strategy": "default", "fill_value": "未知"}]

        rp = client.post(url, json={"actions": actions, "preview": True}, headers=auth_owner)
        assert rp.status_code in (200, 201)
        preview_task_id = rp.json()["id"]
        rr = client.get(
            GOV.format(ws=ws.id, tb=dup_table.id) + f"/tasks/{preview_task_id}/report",
            headers=auth_owner,
        )
        preview = rr.json()["report"]
        assert preview["mode"] == "preview"
        assert preview["affected"][0]["affected_rows"] == 1

        re_ = client.post(url, json={"actions": actions, "preview": False}, headers=auth_owner)
        assert re_.status_code in (200, 201)
        exec_task_id = re_.json()["id"]
        rr2 = client.get(
            GOV.format(ws=ws.id, tb=dup_table.id) + f"/tasks/{exec_task_id}/report",
            headers=auth_owner,
        )
        executed = rr2.json()["report"]
        assert executed["mode"] == "execute"
        assert executed["affected"] == preview["affected"]


class TestGovernancePermissions:
    """MANAGE_DATA 默认 ADMIN：EDITOR 403."""

    def test_editor_forbidden(self, client, ws, dup_table, auth_editor) -> None:
        r = client.post(
            GOV.format(ws=ws.id, tb=dup_table.id) + "/detect",
            json={"match_fields": ["姓名"]},
            headers=auth_editor,
        )
        assert r.status_code == 403

    def test_task_access_requires_manage_data(self, client, ws, dup_table, owner, auth_editor) -> None:
        # owner 创建任务后，editor 无权查看任务
        r = client.post(
            GOV.format(ws=ws.id, tb=dup_table.id) + "/detect",
            json={"match_fields": ["姓名"]},
            headers={"Authorization": f"Bearer {owner_tokens(client, owner)}"},
        )
        assert r.status_code in (200, 201)
        rid = client.get(
            GOV.format(ws=ws.id, tb=dup_table.id) + f"/tasks/{r.json()['id']}",
            headers=auth_editor,
        )
        assert rid.status_code == 403


def owner_tokens(client, owner) -> str:
    r = client.post("/api/v1/accounts/auth/login", json={"login": owner.username, "password": "passw0rd"})
    assert r.status_code == 200
    return r.json()["access_token"]
