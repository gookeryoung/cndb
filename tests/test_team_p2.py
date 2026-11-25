"""ADR 0153 P2：团队策略生效面、团队内检索与团队级审计.

覆盖：
1. `allow_member_invite` 自助加入团队工作区（角色按策略默认，已存在时幂等）；
2. 团队内跨工作区检索只返回**可读**工作区（团队管理员默认无数据面，H49）；
3. 团队写操作写 `core_event`（`team.*`）；
4. 设计复用模块库 `visibility=team`：仅拥有工作区所属团队成员可见 / 可引用（D8）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.core.events import CoreEvent
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Team, TeamMember, TeamRole, Workspace, WorkspaceMember, WorkspaceRole

TEAMS = "/api/v1/teams"
WS = "/api/v1/workspaces"


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
    """owner（团队所有者 + 工作区所有者）/ member（团队成员，非工作区成员）/ outsider."""

    def __init__(self, db: Session, *, policy: dict | None = None) -> None:
        self.owner = _make_user(db, "p2_owner", "张三")
        self.member = _make_user(db, "p2_member", "李四")
        self.outsider = _make_user(db, "p2_outsider")
        self.team = Team(
            name="研发部",
            slug="p2rd",
            description="",
            policy=policy or {},
            created_by_id=self.owner.id,
        )
        db.add(self.team)
        db.flush()
        db.add(TeamMember(team_id=self.team.id, user_id=self.owner.id, role=TeamRole.OWNER))
        db.add(TeamMember(team_id=self.team.id, user_id=self.member.id, role=TeamRole.MEMBER))
        self.ws = Workspace(name="团队工作区", created_by_id=self.owner.id, team_id=self.team.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        db.commit()
        db.refresh(self.team)
        db.refresh(self.ws)


class TestSelfJoin:
    def test_join_requires_policy_switch(self, client, db):
        env = Env(db)  # 默认 allow_member_invite=false
        r = client.post(f"{WS}/{env.ws.id}/join", headers=_login(client, env.member.username))
        assert r.status_code == 403
        assert "未开放自助加入" in r.json()["detail"]

    def test_join_grants_policy_default_role(self, client, db):
        env = Env(db, policy={"allow_member_invite": True, "default_workspace_role": "editor"})
        auth = _login(client, env.member.username)
        r = client.post(f"{WS}/{env.ws.id}/join", headers=auth)
        assert r.status_code == 200, r.text

        caps = client.get(f"{WS}/{env.ws.id}/capabilities", headers=auth).json()
        assert caps["data_role"] == "editor"
        assert caps["sources"]["data"] == "workspace_member:editor"

    def test_join_falls_back_to_viewer_when_policy_none(self, client, db):
        env = Env(db, policy={"allow_member_invite": True})
        auth = _login(client, env.member.username)
        assert client.post(f"{WS}/{env.ws.id}/join", headers=auth).status_code == 200
        assert client.get(f"{WS}/{env.ws.id}/capabilities", headers=auth).json()["data_role"] == "viewer"

    def test_join_is_idempotent_and_keeps_existing_role(self, client, db):
        env = Env(db, policy={"allow_member_invite": True, "default_workspace_role": "editor"})
        db.add(WorkspaceMember(workspace_id=env.ws.id, user_id=env.member.id, role=WorkspaceRole.VIEWER))
        db.commit()
        auth = _login(client, env.member.username)
        assert client.post(f"{WS}/{env.ws.id}/join", headers=auth).status_code == 200
        assert client.get(f"{WS}/{env.ws.id}/capabilities", headers=auth).json()["data_role"] == "viewer"

    def test_non_team_member_cannot_join(self, client, db):
        env = Env(db, policy={"allow_member_invite": True})
        r = client.post(f"{WS}/{env.ws.id}/join", headers=_login(client, env.outsider.username))
        assert r.status_code == 404

    def test_personal_workspace_cannot_be_joined(self, client, db):
        env = Env(db, policy={"allow_member_invite": True})
        auth = _login(client, env.owner.username)
        personal = client.post(WS, json={"name": "个人工作区"}, headers=auth).json()
        assert client.post(f"{WS}/{personal['id']}/join", headers=auth).status_code == 404


class TestTeamScopedSearch:
    def _add_table_with_row(self, client, auth, wid: int, keyword: str) -> None:
        tid = client.post(f"{WS}/{wid}/tables", json={"name": f"{keyword}表"}, headers=auth).json()["id"]
        client.post(
            f"{WS}/{wid}/tables/{tid}/fields",
            json={"name": "名称", "field_type": "text", "order": 0},
            headers=auth,
        )
        client.post(f"{WS}/{wid}/tables/{tid}/records", json={"values": {"名称": keyword}}, headers=auth)

    def test_search_only_covers_readable_workspaces(self, client, db):
        env = Env(db)
        owner_auth = _login(client, env.owner.username)
        self._add_table_with_row(client, owner_auth, env.ws.id, "晶格检索词")

        # 团队成员但非工作区成员：无数据面 → 团队检索不返回该工作区结果
        member_auth = _login(client, env.member.username)
        r = client.get(f"{TEAMS}/{env.team.id}/search", params={"q": "晶格检索词"}, headers=member_auth)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tables"] == [] and body["rows"] == []

        # 自助加入后可读到（走 join 端点：会写事件并失效检索缓存）
        client.patch(f"{TEAMS}/{env.team.id}", json={"policy": {"allow_member_invite": True}}, headers=owner_auth)
        assert client.post(f"{WS}/{env.ws.id}/join", headers=member_auth).status_code == 200
        body = client.get(f"{TEAMS}/{env.team.id}/search", params={"q": "晶格检索词"}, headers=member_auth).json()
        assert any(t["workspace_id"] == env.ws.id for t in body["tables"])
        assert all(row["workspace_name"] == "团队工作区" for row in body["rows"])

    def test_search_requires_team_membership(self, client, db):
        env = Env(db)
        r = client.get(
            f"{TEAMS}/{env.team.id}/search", params={"q": "x"}, headers=_login(client, env.outsider.username)
        )
        assert r.status_code == 404


class TestTeamAuditEvents:
    def test_team_write_paths_emit_events(self, client, db):
        env = Env(db)
        auth = _login(client, env.owner.username)

        newcomer = _make_user(db, "p2_newcomer")
        member = client.post(
            f"{TEAMS}/{env.team.id}/members", json={"username": newcomer.username}, headers=auth
        ).json()
        client.patch(f"{TEAMS}/{env.team.id}", json={"policy": {"default_workspace_role": "viewer"}}, headers=auth)
        client.patch(f"{TEAMS}/{env.team.id}/members/{member['id']}", json={"role": "admin"}, headers=auth)
        client.delete(f"{TEAMS}/{env.team.id}/members/{member['id']}", headers=auth)

        actions = {row[0] for row in db.query(CoreEvent.action).filter(CoreEvent.action.like("team.%")).all()}
        assert {"team.member_add", "team.update", "team.member_role", "team.member_remove"} <= actions

    def test_team_create_and_delete_emit_events(self, client, db):
        user = _make_user(db, "p2_events")
        auth = _login(client, user.username)
        created = client.post(TEAMS, json={"name": "事件团队"}, headers=auth).json()
        assert client.delete(f"{TEAMS}/{created['id']}", headers=auth).status_code == 204

        actions = {row[0] for row in db.query(CoreEvent.action).filter(CoreEvent.action.like("team.%")).all()}
        assert {"team.create", "team.delete"} <= actions
        delete_event = (
            db.query(CoreEvent).filter(CoreEvent.action == "team.delete").order_by(CoreEvent.id.desc()).first()
        )
        assert delete_event is not None
        assert "转为独立工作区" in (delete_event.summary or "")


class TestTeamSearchBranches:
    def test_blank_keyword_returns_empty(self, client, db):
        env = Env(db)
        r = client.get(f"{TEAMS}/{env.team.id}/search", params={"q": " "}, headers=_login(client, env.owner.username))
        assert r.status_code == 200
        assert r.json() == {"query": "", "documents": [], "tables": [], "rows": []}

    def test_documents_hit_and_cache_reuse(self, client, db):
        env = Env(db)
        auth = _login(client, env.owner.username)
        client.post(f"{WS}/{env.ws.id}/documents", json={"title": "晶格团队文档"}, headers=auth)

        first = client.get(f"{TEAMS}/{env.team.id}/search", params={"q": "晶格团队文档"}, headers=auth)
        assert first.status_code == 200, first.text
        docs = first.json()["documents"]
        assert docs and docs[0]["workspace_id"] == env.ws.id
        assert docs[0]["workspace_name"] == "团队工作区"

        # 第二次命中缓存（同样载荷）
        second = client.get(f"{TEAMS}/{env.team.id}/search", params={"q": "晶格团队文档"}, headers=auth)
        assert second.json() == first.json()
