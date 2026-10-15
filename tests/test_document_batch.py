"""文档批量移动 / 删除测试.

覆盖：移动到文件夹 / 根目录、防环与非法目标逐项跳过、不存在与已删除项、跨工作区、
去重、批量删除（文件夹连同子孙）、viewer 403、请求体校验（空 ids / 超长 / 非法 action）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
BATCH = "/api/v1/workspaces/{ws}/documents/batch"


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


@pytest.fixture
def owner(db) -> User:
    return _make_user(db, "batch_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    w = Workspace(name="BatchWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def viewer(db, ws) -> User:
    u = _make_user(db, "batch_viewer")
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.VIEWER))
    db.commit()
    return u


@pytest.fixture
def other_ws(db) -> Workspace:
    u = _make_user(db, "batch_other")
    w = Workspace(name="OtherWS", created_by_id=u.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=u.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


def _create(
    client: TestClient,
    ws: Workspace,
    auth: dict[str, str],
    title: str,
    *,
    folder: bool = False,
    parent: int | None = None,
) -> dict:
    body: dict[str, object] = {"title": title, "content": "" if folder else f"# {title}\n", "is_folder": folder}
    if parent is not None:
        body["parent_id"] = parent
    r = client.post(DOCS.format(ws=ws.id), json=body, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def _tree(client: TestClient, ws: Workspace, auth: dict[str, str]) -> dict[int, dict]:
    items = client.get(DOCS.format(ws=ws.id) + "/tree", headers=auth).json()["items"]
    return {i["id"]: i for i in items}


class TestBatchMove:
    def test_move_multiple_docs_into_folder(self, client, ws, owner):
        auth = _login(client, owner.username)
        folder = _create(client, ws, auth, "目标文件夹", folder=True)
        a = _create(client, ws, auth, "甲")
        b = _create(client, ws, auth, "乙")
        keep = _create(client, ws, auth, "丙")

        r = client.post(
            BATCH.format(ws=ws.id),
            json={"action": "move", "ids": [a["id"], b["id"]], "parent_id": folder["id"]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"action": "move", "updated": 2, "skipped": []}

        tree = _tree(client, ws, auth)
        assert tree[a["id"]]["parent_id"] == folder["id"]
        assert tree[b["id"]]["parent_id"] == folder["id"]
        assert tree[keep["id"]]["parent_id"] is None

    def test_move_to_root_with_zero_and_null(self, client, ws, owner):
        auth = _login(client, owner.username)
        folder = _create(client, ws, auth, "文件夹", folder=True)
        a = _create(client, ws, auth, "甲", parent=folder["id"])
        b = _create(client, ws, auth, "乙", parent=folder["id"])

        r0 = client.post(
            BATCH.format(ws=ws.id), json={"action": "move", "ids": [a["id"]], "parent_id": 0}, headers=auth
        )
        assert r0.json()["updated"] == 1
        r1 = client.post(BATCH.format(ws=ws.id), json={"action": "move", "ids": [b["id"]]}, headers=auth)
        assert r1.json()["updated"] == 1

        tree = _tree(client, ws, auth)
        assert tree[a["id"]]["parent_id"] is None
        assert tree[b["id"]]["parent_id"] is None

    def test_cycle_and_invalid_target_are_skipped_not_fatal(self, client, ws, owner):
        auth = _login(client, owner.username)
        outer = _create(client, ws, auth, "外层", folder=True)
        inner = _create(client, ws, auth, "内层", folder=True, parent=outer["id"])
        doc = _create(client, ws, auth, "文档", parent=outer["id"])

        # 把外层移进自己的子孙（内层）→ 跳过；同批次的普通文档正常移动
        r = client.post(
            BATCH.format(ws=ws.id),
            json={"action": "move", "ids": [outer["id"], doc["id"]], "parent_id": inner["id"]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == 1
        assert [s["id"] for s in body["skipped"]] == [outer["id"]]
        assert "子孙" in body["skipped"][0]["reason"]

        # 移动到非文件夹 → 跳过
        r2 = client.post(
            BATCH.format(ws=ws.id),
            json={"action": "move", "ids": [doc["id"]], "parent_id": outer["id"]},
            headers=auth,
        )
        # outer 是文件夹，这里合法；改用普通文档作为目标
        plain = _create(client, ws, auth, "普通", parent=outer["id"])
        r3 = client.post(
            BATCH.format(ws=ws.id),
            json={"action": "move", "ids": [r2.json()["updated"] and doc["id"]], "parent_id": plain["id"]},
            headers=auth,
        )
        assert r3.json()["updated"] == 0
        assert r3.json()["skipped"][0]["reason"] == "父节点必须是文件夹"

    def test_move_to_self_skipped(self, client, ws, owner):
        auth = _login(client, owner.username)
        folder = _create(client, ws, auth, "自己", folder=True)

        r = client.post(
            BATCH.format(ws=ws.id),
            json={"action": "move", "ids": [folder["id"]], "parent_id": folder["id"]},
            headers=auth,
        )
        assert r.json()["updated"] == 0
        assert "自身" in r.json()["skipped"][0]["reason"]

    def test_missing_already_deleted_and_foreign_ids_skipped(self, client, ws, owner, other_ws):
        auth = _login(client, owner.username)
        doc = _create(client, ws, auth, "正常")
        gone = _create(client, ws, auth, "待删")
        assert client.delete(f"{DOCS.format(ws=ws.id)}/{gone['id']}", headers=auth).status_code == 200

        # 另一工作区的文档（用其 owner 创建）
        other_auth = _login(client, "batch_other")
        foreign = _create(client, other_ws, other_auth, "他处文档")

        r = client.post(
            BATCH.format(ws=ws.id),
            json={"action": "move", "ids": [doc["id"], gone["id"], foreign["id"], 999999], "parent_id": 0},
            headers=auth,
        )
        body = r.json()
        assert body["updated"] == 1
        skipped_ids = {s["id"] for s in body["skipped"]}
        assert skipped_ids == {gone["id"], foreign["id"], 999999}
        assert all("不存在" in s["reason"] for s in body["skipped"])

    def test_duplicate_ids_processed_once(self, client, ws, owner):
        auth = _login(client, owner.username)
        folder = _create(client, ws, auth, "文件夹", folder=True)
        doc = _create(client, ws, auth, "文档")

        r = client.post(
            BATCH.format(ws=ws.id),
            json={"action": "move", "ids": [doc["id"], doc["id"], doc["id"]], "parent_id": folder["id"]},
            headers=auth,
        )
        assert r.json()["updated"] == 1


class TestBatchDelete:
    def test_delete_docs_and_folder_subtree(self, client, ws, owner):
        auth = _login(client, owner.username)
        folder = _create(client, ws, auth, "文件夹", folder=True)
        child = _create(client, ws, auth, "子文档", parent=folder["id"])
        standalone = _create(client, ws, auth, "独立文档")

        r = client.post(
            BATCH.format(ws=ws.id), json={"action": "delete", "ids": [folder["id"], standalone["id"]]}, headers=auth
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"action": "delete", "updated": 2, "skipped": []}

        tree = _tree(client, ws, auth)
        assert folder["id"] not in tree
        assert child["id"] not in tree
        assert standalone["id"] not in tree

        # 回收站里能查到（软删除）
        trash = client.get(DOCS.format(ws=ws.id) + "/trash", headers=auth).json()
        trash_ids = {i["id"] for i in trash.get("items", trash if isinstance(trash, list) else [])}
        assert {folder["id"], child["id"], standalone["id"]} <= trash_ids

    def test_already_deleted_skipped(self, client, ws, owner):
        auth = _login(client, owner.username)
        doc = _create(client, ws, auth, "文档")
        assert client.delete(f"{DOCS.format(ws=ws.id)}/{doc['id']}", headers=auth).status_code == 200

        r = client.post(BATCH.format(ws=ws.id), json={"action": "delete", "ids": [doc["id"]]}, headers=auth)
        assert r.json()["updated"] == 0
        assert r.json()["skipped"][0]["reason"].startswith("文档不存在")


class TestBatchPermissionsAndValidation:
    def test_viewer_denied(self, client, ws, owner, viewer):
        auth_owner = _login(client, owner.username)
        doc = _create(client, ws, auth_owner, "文档")
        auth_viewer = _login(client, viewer.username)

        assert (
            client.post(
                BATCH.format(ws=ws.id), json={"action": "move", "ids": [doc["id"]], "parent_id": 0}, headers=auth_viewer
            ).status_code
            == 403
        )
        assert (
            client.post(
                BATCH.format(ws=ws.id), json={"action": "delete", "ids": [doc["id"]]}, headers=auth_viewer
            ).status_code
            == 403
        )

    def test_payload_validation(self, client, ws, owner):
        auth = _login(client, owner.username)
        base = BATCH.format(ws=ws.id)

        assert client.post(base, json={"action": "move", "ids": []}, headers=auth).status_code == 422
        assert client.post(base, json={"action": "archive", "ids": [1]}, headers=auth).status_code == 422
        assert client.post(base, json={"action": "delete", "ids": list(range(1, 202))}, headers=auth).status_code == 422


class TestSingleMoveStillValidated:
    def test_patch_move_cycle_rejected_with_same_reason(self, client, ws, owner):
        auth = _login(client, owner.username)
        outer = _create(client, ws, auth, "外层", folder=True)
        inner = _create(client, ws, auth, "内层", folder=True, parent=outer["id"])

        r = client.patch(f"{DOCS.format(ws=ws.id)}/{outer['id']}", json={"parent_id": inner["id"]}, headers=auth)
        assert r.status_code == 409
        assert "子孙" in r.json()["detail"]

    def test_patch_move_to_plain_doc_rejected(self, client, ws, owner):
        auth = _login(client, owner.username)
        doc = _create(client, ws, auth, "文档")
        target = _create(client, ws, auth, "目标")

        r = client.patch(f"{DOCS.format(ws=ws.id)}/{doc['id']}", json={"parent_id": target["id"]}, headers=auth)
        assert r.status_code == 409
        assert r.json()["detail"] == "父节点必须是文件夹"
