"""问题清单 API 测试（设计 3.5 节）：提交/列表/详情/评论/关闭重开/权限边界/跨工作区隔离。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

ISSUES = "/api/v1/workspaces/{ws}/tables/{tb}/issues"


def make_table(db: Session, ws: Workspace, name: str = "IssueTable") -> DataTable:
    """建一张带两个字段的物理表."""
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name=name)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for fname, ftype in [("名称", "text"), ("数量", "number")]:
        f = DataField(table_id=dt.id, name=fname, field_type=ftype)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    return dt


@pytest.fixture
def owner(db):
    u = User(username="issue_owner", nickname="IssueOwner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="IssueWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def viewer(db, ws):
    u = User(username="issue_viewer", nickname="IssueViewer")
    u.set_password("passw0rd")
    db.add(u)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.VIEWER))
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def table(db, ws):
    return make_table(db, ws)


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth_owner(client, owner):
    return _login(client, owner.username)


@pytest.fixture
def auth_viewer(client, viewer):
    return _login(client, viewer.username)


class TestIssueCreate:
    def test_viewer_can_submit(self, client, ws, table, auth_viewer) -> None:
        r = client.post(
            ISSUES.format(ws=ws.id, tb=table.id),
            json={"title": "第 3 行数量有误", "description": "应为 42", "category": "data_error"},
            headers=auth_viewer,
        )
        assert r.status_code == 201
        body = r.json()
        assert body["title"] == "第 3 行数量有误"
        assert body["category"] == "data_error"
        assert body["status"] == "open"
        assert [e["action"] for e in body["events"]] == ["created"]

    def test_default_category_other(self, client, ws, table, auth_viewer) -> None:
        r = client.post(ISSUES.format(ws=ws.id, tb=table.id), json={"title": "疑问"}, headers=auth_viewer)
        assert r.status_code == 201
        assert r.json()["category"] == "other"

    def test_invalid_category_400(self, client, ws, table, auth_viewer) -> None:
        r = client.post(
            ISSUES.format(ws=ws.id, tb=table.id),
            json={"title": "x", "category": "bogus"},
            headers=auth_viewer,
        )
        assert r.status_code == 400

    def test_title_required(self, client, ws, table, auth_viewer) -> None:
        r = client.post(ISSUES.format(ws=ws.id, tb=table.id), json={"title": ""}, headers=auth_viewer)
        assert r.status_code == 422

    def test_unauthenticated_401(self, client, ws, table) -> None:
        r = client.post(ISSUES.format(ws=ws.id, tb=table.id), json={"title": "x"})
        assert r.status_code == 401


class TestIssueListAndDetail:
    def test_list_status_filter_and_comment_count(self, client, ws, table, auth_owner, auth_viewer) -> None:
        url = ISSUES.format(ws=ws.id, tb=table.id)
        r1 = client.post(url, json={"title": "问题一"}, headers=auth_viewer).json()
        client.post(url, json={"title": "问题二"}, headers=auth_viewer)
        client.post(f"{url}/{r1['id']}/comments", json={"content": "收到"}, headers=auth_owner)
        client.post(f"{url}/{r1['id']}/close", headers=auth_owner)

        open_list = client.get(url, headers=auth_owner).json()
        assert open_list["total"] == 1
        assert open_list["items"][0]["title"] == "问题二"

        closed_list = client.get(url, params={"status": "closed"}, headers=auth_owner).json()
        assert closed_list["total"] == 1
        assert closed_list["items"][0]["comment_count"] == 1

        all_list = client.get(url, params={"status": "all"}, headers=auth_owner).json()
        assert all_list["total"] == 2

    def test_detail_has_comments_and_events(self, client, ws, table, auth_owner, auth_viewer) -> None:
        url = ISSUES.format(ws=ws.id, tb=table.id)
        issue = client.post(url, json={"title": "详情问题"}, headers=auth_viewer).json()
        client.post(f"{url}/{issue['id']}/comments", json={"content": "第一条"}, headers=auth_owner)
        client.post(f"{url}/{issue['id']}/close", headers=auth_owner)

        detail = client.get(f"{url}/{issue['id']}", headers=auth_viewer).json()
        assert [c["content"] for c in detail["comments"]] == ["第一条"]
        assert [e["action"] for e in detail["events"]] == ["created", "closed"]

    def test_invalid_status_422(self, client, ws, table, auth_owner) -> None:
        r = client.get(ISSUES.format(ws=ws.id, tb=table.id), params={"status": "bogus"}, headers=auth_owner)
        assert r.status_code == 422  # pattern 校验


class TestIssueCloseReopen:
    def test_owner_close_then_reopen(self, client, ws, table, auth_owner, auth_viewer) -> None:
        url = ISSUES.format(ws=ws.id, tb=table.id)
        issue = client.post(url, json={"title": "流转"}, headers=auth_viewer).json()
        r = client.post(f"{url}/{issue['id']}/close", headers=auth_owner)
        assert r.status_code == 200
        assert r.json()["status"] == "closed"
        r = client.post(f"{url}/{issue['id']}/reopen", headers=auth_owner)
        assert r.status_code == 200
        assert r.json()["status"] == "open"
        actions = [e["action"] for e in r.json()["events"]]
        assert actions == ["created", "closed", "reopened"]

    def test_creator_can_close_own_issue(self, client, ws, table, auth_viewer) -> None:
        url = ISSUES.format(ws=ws.id, tb=table.id)
        issue = client.post(url, json={"title": "自关"}, headers=auth_viewer).json()
        r = client.post(f"{url}/{issue['id']}/close", headers=auth_viewer)
        assert r.status_code == 200

    def test_creator_can_reopen_own_issue(self, client, ws, table, auth_viewer, auth_owner) -> None:
        url = ISSUES.format(ws=ws.id, tb=table.id)
        issue = client.post(url, json={"title": "自重开"}, headers=auth_viewer).json()
        client.post(f"{url}/{issue['id']}/close", headers=auth_viewer)
        r = client.post(f"{url}/{issue['id']}/reopen", headers=auth_viewer)
        assert r.status_code == 200

    def test_viewer_cannot_close_others_issue(self, client, ws, table, owner, auth_owner, auth_viewer) -> None:
        url = ISSUES.format(ws=ws.id, tb=table.id)
        issue = client.post(url, json={"title": "他人的"}, headers=auth_owner).json()
        r = client.post(f"{url}/{issue['id']}/close", headers=auth_viewer)
        assert r.status_code == 403

    def test_close_twice_409(self, client, ws, table, auth_owner, auth_viewer) -> None:
        url = ISSUES.format(ws=ws.id, tb=table.id)
        issue = client.post(url, json={"title": "重复关"}, headers=auth_viewer).json()
        client.post(f"{url}/{issue['id']}/close", headers=auth_owner)
        r = client.post(f"{url}/{issue['id']}/close", headers=auth_owner)
        assert r.status_code == 409

    def test_reopen_open_issue_409(self, client, ws, table, auth_owner, auth_viewer) -> None:
        url = ISSUES.format(ws=ws.id, tb=table.id)
        issue = client.post(url, json={"title": "重复开"}, headers=auth_viewer).json()
        r = client.post(f"{url}/{issue['id']}/reopen", headers=auth_owner)
        assert r.status_code == 409


class TestIssueIsolation:
    def test_cross_workspace_404(self, client, db, owner, ws, table, auth_owner) -> None:
        """另一工作区的 owner 访问本工作区问题 → 404."""
        other = User(username="issue_other", nickname="IssueOther")
        other.set_password("passw0rd")
        db.add(other)
        db.flush()
        other_ws = Workspace(name="IssueOtherWS", created_by_id=other.id)
        db.add(other_ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=other_ws.id, user_id=other.id, role=WorkspaceRole.OWNER))
        db.commit()
        other_table = make_table(db, other_ws, name="OtherIssueTable")
        auth_other = _login(client, other.username)

        url = ISSUES.format(ws=ws.id, tb=table.id)
        issue = client.post(url, json={"title": "隔离"}, headers=auth_owner).json()
        r = client.get(
            ISSUES.format(ws=other_ws.id, tb=other_table.id) + f"/{issue['id']}",
            headers=auth_other,
        )
        assert r.status_code == 404

    def test_non_member_403(self, client, db, owner, ws, table, auth_owner) -> None:
        outsider = User(username="issue_outsider", nickname="IssueOutsider")
        outsider.set_password("passw0rd")
        db.add(outsider)
        db.commit()
        auth = _login(client, outsider.username)
        r = client.get(ISSUES.format(ws=ws.id, tb=table.id), headers=auth)
        assert r.status_code == 403
