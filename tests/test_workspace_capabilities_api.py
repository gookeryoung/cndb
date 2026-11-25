"""ADR 0153 P0：`GET /workspaces/{wid}/capabilities` 接口层单测.

覆盖：
1. 三档角色与所有者的能力位载荷；
2. 非成员统一 404（I6 无泄露），不返回「存在但无权」；
3. 门控回归：`/capabilities` 接入后，既有写入口的 403 / 404 语义**没有变化**
   （viewer 导不出、editor 不能改设置与成员、非成员一律 404）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

CAPS = "/api/v1/workspaces/{ws}/capabilities"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_user(db: Session, username: str, nickname: str = "") -> User:
    u = User(username=username, nickname=nickname or username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class Env:
    def __init__(self, db: Session) -> None:
        self.owner = _make_user(db, "capapi_owner", "王五")
        self.ws = Workspace(name="CapApiWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        self.editor = _make_user(db, "capapi_editor")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.editor.id, role=WorkspaceRole.EDITOR))
        self.viewer = _make_user(db, "capapi_viewer")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        self.outsider = _make_user(db, "capapi_outsider")
        db.commit()
        db.refresh(self.ws)


class TestCapabilitiesEndpoint:
    def test_owner_payload(self, client, db):
        env = Env(db)
        r = client.get(CAPS.format(ws=env.ws.id), headers=_login(client, env.owner.username))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["data_role"] == "owner"
        assert data["team_role"] is None
        assert set(data["capabilities"]) == {
            "READ",
            "WRITE",
            "EXPORT",
            "EDIT_SETTINGS",
            "MANAGE_MEMBERS",
            "RESTORE",
            "DELETE_WORKSPACE",
        }
        assert data["sources"]["manage"] == "workspace_member:owner"

    def test_editor_payload(self, client, db):
        env = Env(db)
        r = client.get(CAPS.format(ws=env.ws.id), headers=_login(client, env.editor.username))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["data_role"] == "editor"
        assert set(data["capabilities"]) == {"READ", "WRITE", "EXPORT"}
        assert "manage" not in data["sources"]

    def test_viewer_payload(self, client, db):
        env = Env(db)
        r = client.get(CAPS.format(ws=env.ws.id), headers=_login(client, env.viewer.username))
        assert r.status_code == 200, r.text
        assert r.json() == {
            "data_role": "viewer",
            "team_role": None,
            "capabilities": ["READ"],
            "sources": {"data": "workspace_member:viewer"},
        }

    def test_non_member_gets_404(self, client, db):
        env = Env(db)
        r = client.get(CAPS.format(ws=env.ws.id), headers=_login(client, env.outsider.username))
        assert r.status_code == 404, r.text
        assert r.json()["detail"] == "工作区不存在"

    def test_unknown_workspace_gets_404(self, client, db):
        env = Env(db)
        r = client.get(CAPS.format(ws=999999), headers=_login(client, env.owner.username))
        assert r.status_code == 404, r.text


class TestExistingGatesUnchanged:
    """I3：能力位接入后既有入口的权限结果逐条不变."""

    def test_viewer_cannot_export_workspace(self, client, db):
        env = Env(db)
        r = client.get(f"/api/v1/workspaces/{env.ws.id}/export", headers=_login(client, env.viewer.username))
        assert r.status_code == 403, r.text
        assert "编辑者及以上权限才能导出工作区" in r.json()["detail"]

    def test_editor_can_export_workspace(self, client, db):
        env = Env(db)
        r = client.get(f"/api/v1/workspaces/{env.ws.id}/export", headers=_login(client, env.editor.username))
        assert r.status_code == 200, r.text

    def test_editor_cannot_update_workspace_settings(self, client, db):
        env = Env(db)
        r = client.patch(
            f"/api/v1/workspaces/{env.ws.id}",
            json={"name": "改名"},
            headers=_login(client, env.editor.username),
        )
        assert r.status_code == 403, r.text
        assert "仅所有者可执行此操作" in r.json()["detail"]

    def test_editor_cannot_add_member(self, client, db):
        env = Env(db)
        r = client.post(
            f"/api/v1/workspaces/{env.ws.id}/members",
            json={"username": env.outsider.username, "role": "viewer"},
            headers=_login(client, env.editor.username),
        )
        assert r.status_code == 403, r.text

    def test_viewer_cannot_delete_workspace(self, client, db):
        env = Env(db)
        r = client.delete(f"/api/v1/workspaces/{env.ws.id}", headers=_login(client, env.viewer.username))
        assert r.status_code == 403, r.text
        assert "仅所有者可删除工作区" in r.json()["detail"]

    def test_non_member_detail_and_members_are_404(self, client, db):
        env = Env(db)
        auth = _login(client, env.outsider.username)
        assert client.get(f"/api/v1/workspaces/{env.ws.id}", headers=auth).status_code == 404
        assert client.get(f"/api/v1/workspaces/{env.ws.id}/members", headers=auth).status_code == 404
        assert client.get(f"/api/v1/workspaces/{env.ws.id}/export", headers=auth).status_code == 403

    def test_owner_role_is_reported_in_detail(self, client, db):
        """详情载荷的 `current_user_role` 改由能力位派生，取值不变."""
        env = Env(db)
        r = client.get(f"/api/v1/workspaces/{env.ws.id}", headers=_login(client, env.owner.username))
        assert r.status_code == 200, r.text
        assert r.json()["current_user_role"] == "owner"
