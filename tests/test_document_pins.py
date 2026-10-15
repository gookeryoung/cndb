"""文档个人置顶测试.

覆盖：置顶/取消置顶幂等、个人隔离（A 置顶不影响 B）、树与列表的置顶优先顺序、
详情/列表返回 pinned 字段、非成员 403、置顶回收站文档 404、彻底删除清理置顶行。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import DocumentPin
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _add_member(db: Session, ws: Workspace, username: str, role: WorkspaceRole) -> User:
    u = _make_user(db, username)
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=role))
    db.commit()
    return u


@pytest.fixture
def owner(db) -> User:
    return _make_user(db, "pin_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    w = Workspace(name="PinWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def viewer(db, ws) -> User:
    return _add_member(db, ws, "pin_viewer", WorkspaceRole.VIEWER)


@pytest.fixture
def outsider(db) -> User:
    return _make_user(db, "pin_outsider")


def _create_doc(client: TestClient, ws: Workspace, auth: dict[str, str], title: str) -> dict:
    r = client.post(DOCS.format(ws=ws.id), json={"title": title, "content": f"# {title}\n"}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


class TestPinToggle:
    def test_pin_and_unpin_idempotent(self, client, ws, owner):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws, auth, "甲")
        url = f"{DOCS.format(ws=ws.id)}/{doc['id']}/pin"

        r = client.post(url, headers=auth)
        assert r.status_code == 200, r.text
        assert r.json() == {"document_id": doc["id"], "pinned": True}
        # 重复置顶仍 200 且不报错
        assert client.post(url, headers=auth).status_code == 200

        assert client.delete(url, headers=auth).status_code == 204
        # 重复取消幂等
        assert client.delete(url, headers=auth).status_code == 204

    def test_detail_exposes_pinned(self, client, ws, owner):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws, auth, "乙")
        detail = f"{DOCS.format(ws=ws.id)}/{doc['id']}"

        assert client.get(detail, headers=auth).json()["pinned"] is False
        client.post(detail + "/pin", headers=auth)
        assert client.get(detail, headers=auth).json()["pinned"] is True

    def test_outsider_denied(self, client, ws, owner, outsider):
        auth_owner = _login(client, owner.username)
        doc = _create_doc(client, ws, auth_owner, "丙")
        auth = _login(client, outsider.username)

        assert client.post(f"{DOCS.format(ws=ws.id)}/{doc['id']}/pin", headers=auth).status_code == 403
        assert client.delete(f"{DOCS.format(ws=ws.id)}/{doc['id']}/pin", headers=auth).status_code == 403

    def test_missing_document_404(self, client, ws, owner):
        auth = _login(client, owner.username)
        assert client.post(f"{DOCS.format(ws=ws.id)}/999999/pin", headers=auth).status_code == 404

    def test_trashed_document_rejected(self, client, ws, owner):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws, auth, "丁")
        assert client.delete(f"{DOCS.format(ws=ws.id)}/{doc['id']}", headers=auth).status_code == 200

        assert client.post(f"{DOCS.format(ws=ws.id)}/{doc['id']}/pin", headers=auth).status_code == 404


class TestOrdering:
    def test_tree_lists_pinned_first_keeping_manual_order(self, client, ws, owner):
        auth = _login(client, owner.username)
        first = _create_doc(client, ws, auth, "一")
        second = _create_doc(client, ws, auth, "二")
        third = _create_doc(client, ws, auth, "三")

        def tree() -> list[int]:
            return [i["id"] for i in client.get(DOCS.format(ws=ws.id) + "/tree", headers=auth).json()["items"]]

        assert tree() == [first["id"], second["id"], third["id"]]

        # 置顶第三个：它排到最前，其余保持原顺序
        client.post(f"{DOCS.format(ws=ws.id)}/{third['id']}/pin", headers=auth)
        assert tree() == [third["id"], first["id"], second["id"]]

        items = {
            i["id"]: i["pinned"] for i in client.get(DOCS.format(ws=ws.id) + "/tree", headers=auth).json()["items"]
        }
        assert items[third["id"]] is True
        assert items[first["id"]] is False

    def test_list_endpoint_pinned_first(self, client, ws, owner):
        auth = _login(client, owner.username)
        a = _create_doc(client, ws, auth, "A")
        b = _create_doc(client, ws, auth, "B")
        client.post(f"{DOCS.format(ws=ws.id)}/{b['id']}/pin", headers=auth)

        items = client.get(DOCS.format(ws=ws.id), headers=auth).json()["items"]
        assert [i["id"] for i in items][:2] == [b["id"], a["id"]]
        assert items[0]["pinned"] is True

    def test_pin_is_per_user(self, client, ws, owner, viewer):
        auth_owner = _login(client, owner.username)
        doc_a = _create_doc(client, ws, auth_owner, "主人甲的文档")
        _create_doc(client, ws, auth_owner, "主人乙的文档")
        client.post(f"{DOCS.format(ws=ws.id)}/{doc_a['id']}/pin", headers=auth_owner)

        # viewer 未置顶任何文档：树顺序按 sort_order，pinned 全为 False
        auth_viewer = _login(client, viewer.username)
        items = client.get(DOCS.format(ws=ws.id) + "/tree", headers=auth_viewer).json()["items"]
        assert items[0]["id"] != doc_a["id"] or [i["pinned"] for i in items] == [False, False]
        assert all(i["pinned"] is False for i in items)

        # viewer 自己置顶另一篇，不影响 owner 看到的顺序
        second = items[-1]["id"]
        client.post(f"{DOCS.format(ws=ws.id)}/{second}/pin", headers=auth_viewer)
        owner_items = client.get(DOCS.format(ws=ws.id) + "/tree", headers=auth_owner).json()["items"]
        assert owner_items[0]["id"] == doc_a["id"]
        assert sum(1 for i in owner_items if i["pinned"]) == 1


class TestCleanup:
    def test_purge_removes_pins(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws, auth, "待彻底删除")
        client.post(f"{DOCS.format(ws=ws.id)}/{doc['id']}/pin", headers=auth)
        assert db.query(DocumentPin).count() == 1

        base = DOCS.format(ws=ws.id)
        assert client.delete(base + f"/{doc['id']}", headers=auth).status_code == 200
        assert client.delete(base + f"/{doc['id']}/purge", headers=auth).status_code == 200

        assert db.query(DocumentPin).count() == 0
