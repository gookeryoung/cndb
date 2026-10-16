"""协作者通知：授权时写入、按接收者隔离、已读语义.

动机：文档级授权此前是"静默"的 —— 被授权者只有自己翻目录树才发现多了一份文档。
本文件锁定：
- 授权写入通知（标题 / 角色 / 操作者），**只写给被授权者**；
- 列表只返回本人通知 + 正确未读数；
- 标记已读仅限本人（他人通知 → 404），全部已读返回影响条数；
- 撤销授权不产生"移除"通知（当前只做"被加入"，避免噪音；如后续需要可扩展）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
NOTIF = "/api/v1/accounts/notifications"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user(db: Session, username: str, nickname: str | None = None) -> User:
    u = User(username=username, nickname=nickname or username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class Env:
    def __init__(self, db: Session) -> None:
        self.owner = _user(db, "nt_owner", "所有者小周")
        self.ws = Workspace(name="NotifWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        self.viewer = _user(db, "nt_viewer", "同事小李")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        self.other = _user(db, "nt_other", "旁人小张")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.other.id, role=WorkspaceRole.VIEWER))
        db.commit()


def _draft(client: TestClient, env: Env, title: str = "通知用草稿") -> dict:
    r = client.post(
        DOCS.format(ws=env.ws.id),
        json={"title": title, "content": "x", "status": "draft"},
        headers=_login(client, env.owner.username),
    )
    assert r.status_code == 201, r.text
    return r.json()


def _grant(client: TestClient, env: Env, doc_id: int, user_id: int, role: str = "viewer") -> None:
    r = client.post(
        f"{DOCS.format(ws=env.ws.id)}/{doc_id}/permissions",
        json={"user_id": user_id, "role": role},
        headers=_login(client, env.owner.username),
    )
    assert r.status_code == 201, r.text


def _list(client: TestClient, env: Env, username: str, **params: object) -> dict:
    r = client.get(NOTIF, params=params, headers=_login(client, username))
    assert r.status_code == 200, r.text
    return r.json()


class TestGrantCreatesNotification:
    def test_target_receives_notification_with_context(self, client, db):
        env = Env(db)
        doc = _draft(client, env, "季度规划草稿")
        _grant(client, env, doc["id"], env.viewer.id, "editor")

        body = _list(client, env, env.viewer.username)
        assert body["unread_count"] == 1
        item = body["items"][0]
        assert item["type"] == "document.collaborator_added"
        assert item["document_id"] == doc["id"]
        assert item["document_title"] == "季度规划草稿"
        assert item["role"] == "editor"
        assert item["actor_name"] == "所有者小周"
        assert item["read"] is False

    def test_only_target_gets_notification(self, client, db):
        env = Env(db)
        doc = _draft(client, env)
        _grant(client, env, doc["id"], env.viewer.id)

        assert _list(client, env, env.viewer.username)["unread_count"] == 1
        assert _list(client, env, env.other.username)["unread_count"] == 0
        # 授权者本人不产生通知
        assert _list(client, env, env.owner.username)["unread_count"] == 0

    def test_revoke_does_not_create_noise(self, client, db):
        env = Env(db)
        doc = _draft(client, env)
        _grant(client, env, doc["id"], env.viewer.id)
        r = client.delete(
            f"{DOCS.format(ws=env.ws.id)}/{doc['id']}/permissions/{env.viewer.id}",
            headers=_login(client, env.owner.username),
        )
        assert r.status_code == 204
        assert _list(client, env, env.viewer.username)["unread_count"] == 1  # 仍是那条"被加入"


class TestListAndRead:
    def test_mark_read_and_read_all(self, client, db):
        env = Env(db)
        d1 = _draft(client, env, "草稿一")
        d2 = _draft(client, env, "草稿二")
        _grant(client, env, d1["id"], env.viewer.id)
        _grant(client, env, d2["id"], env.viewer.id)

        body = _list(client, env, env.viewer.username)
        assert body["unread_count"] == 2
        target = body["items"][0]["id"]

        auth = _login(client, env.viewer.username)
        assert client.post(f"{NOTIF}/{target}/read", headers=auth).status_code == 204
        after = _list(client, env, env.viewer.username)
        assert after["unread_count"] == 1
        assert next(i for i in after["items"] if i["id"] == target)["read"] is True

        # 未读过滤只剩 1 条
        only_unread = _list(client, env, env.viewer.username, unread_only=True)
        assert len(only_unread["items"]) == 1

        assert client.post(f"{NOTIF}/read-all", headers=auth).json()["updated"] == 1
        assert _list(client, env, env.viewer.username)["unread_count"] == 0

    def test_cannot_read_others_notification(self, client, db):
        env = Env(db)
        doc = _draft(client, env)
        _grant(client, env, doc["id"], env.viewer.id)
        target = _list(client, env, env.viewer.username)["items"][0]["id"]

        r = client.post(f"{NOTIF}/{target}/read", headers=_login(client, env.other.username))
        assert r.status_code == 404
        # 目标用户仍是未读
        assert _list(client, env, env.viewer.username)["unread_count"] == 1

    def test_pagination_before_id(self, client, db):
        env = Env(db)
        for idx in range(3):
            doc = _draft(client, env, f"分页草稿{idx}")
            _grant(client, env, doc["id"], env.viewer.id)

        first = _list(client, env, env.viewer.username, limit=2)
        assert len(first["items"]) == 2
        oldest_id = first["items"][-1]["id"]
        page2 = _list(client, env, env.viewer.username, limit=2, before_id=oldest_id)
        assert len(page2["items"]) == 1
        assert page2["items"][0]["id"] < oldest_id
