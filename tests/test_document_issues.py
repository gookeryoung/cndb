"""文档问题清单（documents 插件）测试.

覆盖：提交（成员 / 类别校验 / 文档不存在）、列表（状态与文档过滤、评论数、文档标题）、
详情（评论 + 状态事件）、评论、关闭/重开（权限与 409）、越权与非成员 403、
文档彻底删除时问题及其评论/事件一并清理。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import DocumentIssueEvent
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
DI = "/api/v1/workspaces/{ws}/document-issues"


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
    return _make_user(db, "di_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    w = Workspace(name="DiWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def editor(db, ws) -> User:
    return _add_member(db, ws, "di_editor", WorkspaceRole.EDITOR)


@pytest.fixture
def viewer(db, ws) -> User:
    return _add_member(db, ws, "di_viewer", WorkspaceRole.VIEWER)


@pytest.fixture
def outsider(db) -> User:
    return _make_user(db, "di_outsider")


@pytest.fixture
def doc(client, ws, owner) -> dict:
    auth = _login(client, owner.username)
    r = client.post(DOCS.format(ws=ws.id), json={"title": "需求说明", "content": "# 标题\n"}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


class TestCreateAndList:
    def test_member_creates_issue(self, client, ws, owner, viewer, doc, db):
        auth = _login(client, viewer.username)

        r = client.post(
            DI.format(ws=ws.id),
            json={
                "document_id": doc["id"],
                "title": "第三节口径有误",
                "description": "与表格不一致",
                "category": "data_error",
            },
            headers=auth,
        )

        assert r.status_code == 201, r.text
        body = r.json()
        assert body["document_id"] == doc["id"]
        assert body["document_title"] == "需求说明"
        assert body["status"] == "open"
        assert body["category"] == "data_error"
        assert body["created_by_id"] == viewer.id
        assert [e["action"] for e in body["events"]] == ["created"]
        assert body["comments"] == []

    def test_invalid_category_rejected(self, client, ws, owner, doc, db):
        auth = _login(client, owner.username)
        r = client.post(
            DI.format(ws=ws.id),
            json={"document_id": doc["id"], "title": "x", "category": "bogus"},
            headers=auth,
        )
        assert r.status_code == 400

    def test_missing_document_rejected(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        r = client.post(
            DI.format(ws=ws.id),
            json={"document_id": 999999, "title": "x"},
            headers=auth,
        )
        assert r.status_code == 404

    def test_outsider_denied(self, client, ws, outsider, doc, db):
        auth = _login(client, outsider.username)
        r = client.post(DI.format(ws=ws.id), json={"document_id": doc["id"], "title": "x"}, headers=auth)
        assert r.status_code == 403
        assert client.get(DI.format(ws=ws.id), headers=auth).status_code == 403

    def test_list_filters_and_counts(self, client, ws, owner, doc, db):
        auth = _login(client, owner.username)
        first = client.post(
            DI.format(ws=ws.id), json={"document_id": doc["id"], "title": "问题一"}, headers=auth
        ).json()
        second = client.post(
            DI.format(ws=ws.id),
            json={"document_id": doc["id"], "title": "问题二", "category": "suggestion"},
            headers=auth,
        ).json()
        client.post(DI.format(ws=ws.id) + f"/{second['id']}/comments", json={"content": "补充说明"}, headers=auth)
        client.post(DI.format(ws=ws.id) + f"/{first['id']}/close", headers=auth)

        open_list = client.get(DI.format(ws=ws.id), headers=auth).json()
        assert open_list["total"] == 1
        assert open_list["items"][0]["id"] == second["id"]
        assert open_list["items"][0]["comment_count"] == 1

        closed_list = client.get(DI.format(ws=ws.id), params={"status": "closed"}, headers=auth).json()
        assert closed_list["total"] == 1
        assert closed_list["items"][0]["id"] == first["id"]

        all_list = client.get(DI.format(ws=ws.id), params={"status": "all"}, headers=auth).json()
        assert all_list["total"] == 2
        assert all_list["items"][0]["id"] == second["id"]  # 倒序

        by_doc = client.get(DI.format(ws=ws.id), params={"document_id": doc["id"]}, headers=auth).json()
        assert by_doc["total"] == 1
        other_doc = client.get(DI.format(ws=ws.id), params={"document_id": 999999}, headers=auth).json()
        assert other_doc["total"] == 0

        assert client.get(DI.format(ws=ws.id), params={"status": "bogus"}, headers=auth).status_code == 400

    def test_detail_contains_comments_and_events(self, client, ws, owner, doc, db):
        auth = _login(client, owner.username)
        issue = client.post(DI.format(ws=ws.id), json={"document_id": doc["id"], "title": "问题"}, headers=auth).json()
        client.post(DI.format(ws=ws.id) + f"/{issue['id']}/comments", json={"content": "已确认"}, headers=auth)

        detail = client.get(DI.format(ws=ws.id) + f"/{issue['id']}", headers=auth).json()

        assert detail["comment_count"] == 1
        assert [c["content"] for c in detail["comments"]] == ["已确认"]
        assert [e["action"] for e in detail["events"]] == ["created"]

    def test_not_found(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        assert client.get(DI.format(ws=ws.id) + "/999999", headers=auth).status_code == 404


class TestTransitions:
    def _issue(self, client, ws, owner, doc) -> dict:
        auth = _login(client, owner.username)
        return client.post(DI.format(ws=ws.id), json={"document_id": doc["id"], "title": "问题"}, headers=auth).json()

    def test_editor_closes_and_reopens(self, client, ws, owner, editor, doc, db):
        issue = self._issue(client, ws, owner, doc)
        auth = _login(client, editor.username)
        url = DI.format(ws=ws.id) + f"/{issue['id']}"

        closed = client.post(url + "/close", headers=auth)
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "closed"
        assert [e["action"] for e in closed.json()["events"]] == ["created", "closed"]

        # 重复关闭 → 409
        assert client.post(url + "/close", headers=auth).status_code == 409

        reopened = client.post(url + "/reopen", headers=auth)
        assert reopened.status_code == 200
        assert reopened.json()["status"] == "open"
        assert [e["action"] for e in reopened.json()["events"]] == ["created", "closed", "reopened"]
        assert client.post(url + "/reopen", headers=auth).status_code == 409

    def test_creator_closes_own_issue(self, client, ws, owner, viewer, doc, db):
        viewer_issue = client.post(
            DI.format(ws=ws.id),
            json={"document_id": doc["id"], "title": "查看者的问题"},
            headers=_login(client, viewer.username),
        ).json()

        r = client.post(
            DI.format(ws=ws.id) + f"/{viewer_issue['id']}/close",
            headers=_login(client, viewer.username),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "closed"

    def test_unrelated_viewer_cannot_close(self, client, ws, owner, viewer, doc, db):
        issue = self._issue(client, ws, owner, doc)
        other = _add_member(db, ws, "di_viewer2", WorkspaceRole.VIEWER)
        auth = _login(client, other.username)

        assert client.post(DI.format(ws=ws.id) + f"/{issue['id']}/close", headers=auth).status_code == 403


class TestPurgeCleanup:
    def test_purge_removes_issues_comments_events(self, client, ws, owner, doc, db):
        auth = _login(client, owner.username)
        issue = client.post(DI.format(ws=ws.id), json={"document_id": doc["id"], "title": "问题"}, headers=auth).json()
        client.post(DI.format(ws=ws.id) + f"/{issue['id']}/comments", json={"content": "评论"}, headers=auth)

        base = DOCS.format(ws=ws.id)
        assert client.delete(base + f"/{doc['id']}", headers=auth).status_code == 200
        purged = client.delete(base + f"/{doc['id']}/purge", headers=auth)
        assert purged.status_code == 200, purged.text

        # 问题及其评论/事件（含已删除文档的）全部清理，且不残留孤儿行
        assert client.get(DI.format(ws=ws.id) + f"/{issue['id']}", headers=auth).status_code == 404
        assert db.query(DocumentIssueEvent).count() == 0
        from cndb.plugins.documents.models import DocumentIssue, DocumentIssueComment

        assert db.query(DocumentIssue).count() == 0
        assert db.query(DocumentIssueComment).count() == 0
