"""数据表分组 API（需求 0137）.

覆盖：列表 / 建组（owner-editor / viewer 403）/ 重名校验 / 改名 / 排序 /
删除后表回落未分组 / 表建组与移动分组 / 跨工作区分组拒绝。
"""

from __future__ import annotations

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


def _user(db, username: str, *, password: str = "passw0rd") -> User:
    u = User(username=username, nickname=username)
    u.set_password(password)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def owner(db):
    return _user(db, "group_owner")


@pytest.fixture
def viewer(db):
    return _user(db, "group_viewer")


@pytest.fixture
def ws(db, owner, viewer):
    w = Workspace(name="GroupWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.add(WorkspaceMember(workspace_id=w.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def other_ws(db, owner):
    w = Workspace(name="OtherWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


def _auth(client, user: User) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": user.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth_owner(client, owner):
    return _auth(client, owner)


@pytest.fixture
def auth_viewer(client, viewer):
    return _auth(client, viewer)


GROUPS_URL = "/api/v1/workspaces/{wid}/table-groups"
TABLES_URL = "/api/v1/workspaces/{wid}/tables"


def test_list_empty(client, ws, auth_owner):
    r = client.get(GROUPS_URL.format(wid=ws.id), headers=auth_owner)
    assert r.status_code == 200
    assert r.json() == []


def test_create_list_and_order(client, ws, auth_owner):
    r1 = client.post(GROUPS_URL.format(wid=ws.id), json={"name": " 销售 "}, headers=auth_owner)
    assert r1.status_code == 201
    assert r1.json()["name"] == "销售"
    r2 = client.post(GROUPS_URL.format(wid=ws.id), json={"name": "运营"}, headers=auth_owner)
    assert r2.status_code == 201

    listed = client.get(GROUPS_URL.format(wid=ws.id), headers=auth_owner).json()
    assert [g["name"] for g in listed] == ["销售", "运营"]

    # 重排：反序
    ids = [listed[1]["id"], listed[0]["id"]]
    reordered = client.post(f"{GROUPS_URL.format(wid=ws.id)}/reorder", json=ids, headers=auth_owner)
    assert reordered.status_code == 200
    assert [g["name"] for g in reordered.json()] == ["运营", "销售"]


def test_create_validation(client, ws, auth_owner):
    url = GROUPS_URL.format(wid=ws.id)
    assert client.post(url, json={"name": "   "}, headers=auth_owner).status_code == 400
    assert client.post(url, json={"name": "x" * 81}, headers=auth_owner).status_code == 400
    assert client.post(url, json={"name": "重复"}, headers=auth_owner).status_code == 201
    dup = client.post(url, json={"name": "重复"}, headers=auth_owner)
    assert dup.status_code == 400
    assert "已存在" in dup.json()["detail"]


def test_viewer_cannot_write(client, ws, auth_owner, auth_viewer):
    url = GROUPS_URL.format(wid=ws.id)
    created = client.post(url, json={"name": "销售"}, headers=auth_owner).json()
    assert client.get(url, headers=auth_viewer).status_code == 200
    assert client.post(url, json={"name": "运营"}, headers=auth_viewer).status_code == 403
    assert client.patch(f"{url}/{created['id']}", json={"name": "改名"}, headers=auth_viewer).status_code == 403
    assert client.delete(f"{url}/{created['id']}", headers=auth_viewer).status_code == 403


def test_rename_and_delete_falls_back_ungrouped(client, db, ws, auth_owner):
    url = GROUPS_URL.format(wid=ws.id)
    group = client.post(url, json={"name": "销售"}, headers=auth_owner).json()
    renamed = client.patch(f"{url}/{group['id']}", json={"name": "销售二组"}, headers=auth_owner)
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "销售二组"

    created = client.post(
        TABLES_URL.format(wid=ws.id),
        json={"name": "客户", "group_id": group["id"]},
        headers=auth_owner,
    )
    assert created.status_code == 201
    assert created.json()["group_id"] == group["id"]

    assert client.delete(f"{url}/{group['id']}", headers=auth_owner).status_code == 204
    db.expire_all()
    table = db.get(DataTable, created.json()["id"])
    assert table is not None
    assert table.group_id is None


def test_table_group_assignment(client, db, ws, auth_owner):
    url = GROUPS_URL.format(wid=ws.id)
    group = client.post(url, json={"name": "销售"}, headers=auth_owner).json()

    created = client.post(TABLES_URL.format(wid=ws.id), json={"name": "客户"}, headers=auth_owner)
    assert created.status_code == 201
    assert created.json()["group_id"] is None

    tid = created.json()["id"]
    moved = client.patch(
        TABLES_URL.format(wid=ws.id) + f"/{tid}",
        json={"group_id": group["id"]},
        headers=auth_owner,
    )
    assert moved.status_code == 200
    assert moved.json()["group_id"] == group["id"]

    cleared = client.patch(
        TABLES_URL.format(wid=ws.id) + f"/{tid}",
        json={"group_id": None},
        headers=auth_owner,
    )
    assert cleared.status_code == 200
    assert cleared.json()["group_id"] is None


def test_reject_foreign_or_missing_group(client, ws, other_ws, auth_owner):
    foreign = client.post(
        GROUPS_URL.format(wid=other_ws.id), json={"name": "别的工作区分组"}, headers=auth_owner
    ).json()
    bad = client.post(
        TABLES_URL.format(wid=ws.id),
        json={"name": "客户", "group_id": foreign["id"]},
        headers=auth_owner,
    )
    assert bad.status_code == 400
    missing = client.post(
        TABLES_URL.format(wid=ws.id),
        json={"name": "客户", "group_id": 999999},
        headers=auth_owner,
    )
    assert missing.status_code == 400
