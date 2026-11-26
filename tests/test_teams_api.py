"""ADR 0153 P1：团队 API 接口层单测（CRUD / 成员 / 策略 / 工作区挂载 / 两平面分离）.

覆盖 H49-H52 的接口面：
- 团队角色只产管理面：`team_admin` 读工作区 → 404，改设置 → 200，删工作区 → 403；
- 团队与工作区删除安全：删团队只解绑（工作区仍在），删工作区仍仅工作区所有者；
- 一个工作区至多一个团队；非团队成员 404（不泄露存在性）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Team, TeamMember, TeamRole, Workspace, WorkspaceMember, WorkspaceRole

TEAMS = "/api/v1/teams"
WORKSPACES = "/api/v1/workspaces"


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
    """owner（团队所有者 + 工作区所有者）/ admin（团队管理员，非工作区成员）/ outsider."""

    def __init__(self, db: Session) -> None:
        self.owner = _make_user(db, "p1_owner", "张三")
        self.admin = _make_user(db, "p1_admin", "李四")
        self.outsider = _make_user(db, "p1_outsider")
        self.team = Team(name="研发部", slug="rd", description="", policy={}, created_by_id=self.owner.id)
        db.add(self.team)
        db.flush()
        db.add(TeamMember(team_id=self.team.id, user_id=self.owner.id, role=TeamRole.OWNER))
        db.add(TeamMember(team_id=self.team.id, user_id=self.admin.id, role=TeamRole.ADMIN))
        self.ws = Workspace(name="研发部工作区", created_by_id=self.owner.id, team_id=self.team.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        db.commit()
        db.refresh(self.team)
        db.refresh(self.ws)


class TestTeamCrud:
    def test_create_team_makes_creator_owner(self, client, db):
        user = _make_user(db, "p1_creator")
        auth = _login(client, user.username)
        r = client.post(TEAMS, json={"name": "设计部"}, headers=auth)
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["name"] == "设计部"
        assert data["slug"] == "she-ji-bu" or data["slug"] == "team"  # 中文名回落 team
        assert data["current_user_role"] == "owner"
        assert data["policy"]["default_workspace_role"] == "none"

        listed = client.get(TEAMS, headers=auth).json()
        assert [t["id"] for t in listed] == [data["id"]]

    def test_create_team_rejects_duplicate_slug(self, client, db):
        user = _make_user(db, "p1_dup")
        auth = _login(client, user.username)
        assert client.post(TEAMS, json={"name": "A", "slug": "dup"}, headers=auth).status_code == 201
        r = client.post(TEAMS, json={"name": "B", "slug": "dup"}, headers=auth)
        assert r.status_code == 400

    def test_detail_requires_membership(self, client, db):
        env = Env(db)
        assert client.get(f"{TEAMS}/{env.team.id}", headers=_login(client, env.owner.username)).status_code == 200
        assert client.get(f"{TEAMS}/{env.team.id}", headers=_login(client, env.outsider.username)).status_code == 404
        assert (
            client.get(f"{TEAMS}/{env.team.id}/members", headers=_login(client, env.outsider.username)).status_code
            == 404
        )
        assert (
            client.get(f"{TEAMS}/{env.team.id}/workspaces", headers=_login(client, env.outsider.username)).status_code
            == 404
        )

    def test_update_policy_owner_only_and_validated(self, client, db):
        env = Env(db)
        admin_auth = _login(client, env.admin.username)
        owner_auth = _login(client, env.owner.username)

        r = client.patch(
            f"{TEAMS}/{env.team.id}", json={"policy": {"default_workspace_role": "viewer"}}, headers=admin_auth
        )
        assert r.status_code == 403, r.text
        assert "团队管理员" in r.json()["detail"]

        r = client.patch(
            f"{TEAMS}/{env.team.id}", json={"policy": {"default_workspace_role": "nope"}}, headers=owner_auth
        )
        assert r.status_code == 400

        r = client.patch(
            f"{TEAMS}/{env.team.id}", json={"policy": {"default_workspace_role": "viewer"}}, headers=owner_auth
        )
        assert r.status_code == 200, r.text
        assert r.json()["policy"]["default_workspace_role"] == "viewer"

    def test_delete_team_only_unbinds_workspaces(self, client, db):
        env = Env(db)
        r = client.delete(f"{TEAMS}/{env.team.id}", headers=_login(client, env.owner.username))
        assert r.status_code == 204, r.text

        db.expire_all()
        ws = db.get(Workspace, env.ws.id)
        assert ws is not None  # 工作区不删（I5）
        assert ws.team_id is None
        assert db.get(Team, env.team.id) is None
        # 工作区成员身份不受影响
        assert db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == env.ws.id).count() == 1


class TestTeamMembers:
    def test_member_lifecycle_and_last_owner_guard(self, client, db):
        env = Env(db)
        owner_auth = _login(client, env.owner.username)
        newcomer = _make_user(db, "p1_newcomer")

        r = client.post(f"{TEAMS}/{env.team.id}/members", json={"username": newcomer.username}, headers=owner_auth)
        assert r.status_code == 201, r.text
        member_id = r.json()["id"]
        assert r.json()["role"] == "member"

        # 不得直接添加为 owner
        assert (
            client.post(
                f"{TEAMS}/{env.team.id}/members",
                json={"username": env.outsider.username, "role": "owner"},
                headers=owner_auth,
            ).status_code
            == 400
        )
        # 重复添加 400
        assert (
            client.post(
                f"{TEAMS}/{env.team.id}/members", json={"username": newcomer.username}, headers=owner_auth
            ).status_code
            == 400
        )
        # 改角色
        r = client.patch(f"{TEAMS}/{env.team.id}/members/{member_id}", json={"role": "admin"}, headers=owner_auth)
        assert r.status_code == 200, r.text
        # 最后一个 owner 不可降级
        owner_member = (
            db.query(TeamMember).filter(TeamMember.team_id == env.team.id, TeamMember.role == TeamRole.OWNER).first()
        )
        r = client.patch(
            f"{TEAMS}/{env.team.id}/members/{owner_member.id}", json={"role": "member"}, headers=owner_auth
        )
        assert r.status_code == 400
        # 移除成员不影响工作区成员身份（两套授权独立）
        assert client.delete(f"{TEAMS}/{env.team.id}/members/{member_id}", headers=owner_auth).status_code == 204

    def test_admin_can_add_but_not_change_roles(self, client, db):
        env = Env(db)
        admin_auth = _login(client, env.admin.username)
        newcomer = _make_user(db, "p1_via_admin")

        r = client.post(f"{TEAMS}/{env.team.id}/members", json={"username": newcomer.username}, headers=admin_auth)
        assert r.status_code == 201, r.text
        r = client.patch(f"{TEAMS}/{env.team.id}/members/{r.json()['id']}", json={"role": "admin"}, headers=admin_auth)
        assert r.status_code == 403


class TestTwoPlaneSeparation:
    """H49：团队管理员默认读不到数据，但能管理工作区设置."""

    def test_team_admin_cannot_read_workspace(self, client, db):
        env = Env(db)
        auth = _login(client, env.admin.username)
        assert client.get(f"{WORKSPACES}/{env.ws.id}", headers=auth).status_code == 404
        assert client.get(f"{WORKSPACES}/{env.ws.id}/members", headers=auth).status_code == 404
        # ADR 0161 D6：有管理面无数据面时能力位端点返回 200，便于前端渲染管理入口
        r = client.get(f"{WORKSPACES}/{env.ws.id}/capabilities", headers=auth)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["data_role"] is None
        assert "EDIT_SETTINGS" in payload["capabilities"]

    def test_team_admin_can_update_settings(self, client, db):
        env = Env(db)
        auth = _login(client, env.admin.username)
        r = client.patch(f"{WORKSPACES}/{env.ws.id}", json={"name": "改名后的工作区"}, headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "改名后的工作区"

    def test_team_admin_cannot_delete_workspace(self, client, db):
        """D9：删除属不可逆操作，仅工作区所有者."""
        env = Env(db)
        auth = _login(client, env.admin.username)
        r = client.delete(f"{WORKSPACES}/{env.ws.id}", headers=auth)
        assert r.status_code == 403, r.text
        assert "仅所有者可删除工作区" in r.json()["detail"]
        assert db.get(Workspace, env.ws.id) is not None

    def test_policy_default_role_lets_team_member_read(self, client, db):
        env = Env(db)
        owner_auth = _login(client, env.owner.username)
        client.patch(
            f"{TEAMS}/{env.team.id}", json={"policy": {"default_workspace_role": "viewer"}}, headers=owner_auth
        )
        auth = _login(client, env.admin.username)
        r = client.get(f"{WORKSPACES}/{env.ws.id}", headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["current_user_role"] == "viewer"
        caps = client.get(f"{WORKSPACES}/{env.ws.id}/capabilities", headers=auth).json()
        assert caps["data_role"] == "viewer"
        assert caps["team_role"] == "admin"
        assert "team_role:admin" in caps["sources"]["manage"]

    def test_public_workspace_grants_team_member_read(self, client, db):
        env = Env(db)
        owner_auth = _login(client, env.owner.username)
        client.patch(f"{WORKSPACES}/{env.ws.id}", json={"visibility": "public"}, headers=owner_auth)

        auth = _login(client, env.admin.username)
        caps = client.get(f"{WORKSPACES}/{env.ws.id}/capabilities", headers=auth).json()
        assert caps["data_role"] == "viewer"
        assert caps["sources"]["data"] == "workspace_public"
        # 团队成员之外的登录用户仍 404
        assert client.get(f"{WORKSPACES}/{env.ws.id}", headers=_login(client, env.outsider.username)).status_code == 404


class TestWorkspaceTeamBinding:
    def test_create_workspace_in_team(self, client, db):
        env = Env(db)
        auth = _login(client, env.admin.username)
        r = client.post(WORKSPACES, json={"name": "团队新工作区", "team_id": env.team.id}, headers=auth)
        assert r.status_code == 201, r.text
        assert r.json()["team_id"] == env.team.id
        assert r.json()["team"]["name"] == "研发部"

        # 列表带 team 与 ?team_id 过滤
        listed = client.get(WORKSPACES, params={"team_id": env.team.id}, headers=auth).json()
        names = {item["name"] for item in listed}
        assert "团队新工作区" in names
        assert all(item["team_id"] == env.team.id for item in listed)

    def test_create_workspace_in_other_team_forbidden(self, client, db):
        env = Env(db)
        other_team = Team(name="市场部", slug="mkt", description="", policy={}, created_by_id=env.outsider.id)
        db.add(other_team)
        db.flush()
        db.add(TeamMember(team_id=other_team.id, user_id=env.outsider.id, role=TeamRole.OWNER))
        db.commit()

        r = client.post(
            WORKSPACES, json={"name": "偷偷挂载", "team_id": other_team.id}, headers=_login(client, env.admin.username)
        )
        assert r.status_code == 403, r.text

    def test_allowed_modules_policy_enforced(self, client, db):
        env = Env(db)
        owner_auth = _login(client, env.owner.username)
        r = client.patch(f"{TEAMS}/{env.team.id}", json={"policy": {"allowed_modules": ["tables"]}}, headers=owner_auth)
        assert r.status_code == 200, r.text
        r = client.post(
            WORKSPACES,
            json={"name": "带文档的新工作区", "team_id": env.team.id, "modules": ["tables", "documents"]},
            headers=owner_auth,
        )
        assert r.status_code == 400, r.text
        assert "documents" in r.json()["detail"]

    def test_move_workspace_into_team_and_out(self, client, db):
        env = Env(db)
        owner_auth = _login(client, env.owner.username)
        personal = client.post(WORKSPACES, json={"name": "个人工作区"}, headers=owner_auth).json()
        assert personal["team_id"] is None

        r = client.patch(f"{WORKSPACES}/{personal['id']}", json={"team_id": env.team.id}, headers=owner_auth)
        assert r.status_code == 200, r.text
        assert r.json()["team_id"] == env.team.id

        r = client.patch(f"{WORKSPACES}/{personal['id']}", json={"team_id": None}, headers=owner_auth)
        assert r.status_code == 200, r.text
        assert r.json()["team_id"] is None

    def test_team_workspaces_list_is_flat(self, client, db):
        env = Env(db)
        auth = _login(client, env.owner.username)
        items = client.get(f"{TEAMS}/{env.team.id}/workspaces", headers=auth).json()
        assert [item["id"] for item in items] == [env.ws.id]
        assert "children" not in items[0]


class TestTeamErrorBranches:
    """错误分支覆盖（404 / 400 / 403 口径与文案）。"""

    def test_unknown_team_is_404(self, client, db):
        env = Env(db)
        auth = _login(client, env.owner.username)
        assert client.get(f"{TEAMS}/999999", headers=auth).status_code == 404
        assert client.patch(f"{TEAMS}/999999", json={"name": "x"}, headers=auth).status_code == 404
        assert client.delete(f"{TEAMS}/999999", headers=auth).status_code == 404
        assert client.get(f"{TEAMS}/999999/members", headers=auth).status_code == 404
        assert client.get(f"{TEAMS}/999999/workspaces", headers=auth).status_code == 404

    def test_create_team_validation(self, client, db):
        user = _make_user(db, "p1_create_invalid")
        auth = _login(client, user.username)
        assert client.post(TEAMS, json={"name": "   "}, headers=auth).status_code == 400

    def test_update_name_and_description(self, client, db):
        env = Env(db)
        auth = _login(client, env.owner.username)
        r = client.patch(f"{TEAMS}/{env.team.id}", json={"name": "研发中心", "description": "改描述"}, headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "研发中心"
        assert r.json()["description"] == "改描述"
        # 名称不能改成空白
        assert client.patch(f"{TEAMS}/{env.team.id}", json={"name": "  "}, headers=auth).status_code == 400

    def test_admin_cannot_delete_team(self, client, db):
        env = Env(db)
        r = client.delete(f"{TEAMS}/{env.team.id}", headers=_login(client, env.admin.username))
        assert r.status_code == 403
        assert "团队管理员" in r.json()["detail"]

    def test_member_error_branches(self, client, db):
        env = Env(db)
        auth = _login(client, env.owner.username)
        url = f"{TEAMS}/{env.team.id}/members"

        # 用户不存在
        assert client.post(url, json={"username": "nobody-here"}, headers=auth).status_code == 404
        # 非法角色
        assert (
            client.post(url, json={"username": env.outsider.username, "role": "boss"}, headers=auth).status_code == 400
        )
        # 成员不存在
        assert client.patch(f"{url}/999999", json={"role": "member"}, headers=auth).status_code == 404
        assert client.delete(f"{url}/999999", headers=auth).status_code == 404
        # 非法角色（改）
        member = client.post(url, json={"username": env.outsider.username}, headers=auth).json()
        assert client.patch(f"{url}/{member['id']}", json={"role": "boss"}, headers=auth).status_code == 400

    def test_cannot_remove_last_owner(self, client, db):
        env = Env(db)
        auth = _login(client, env.owner.username)
        owner_member = (
            db.query(TeamMember).filter(TeamMember.team_id == env.team.id, TeamMember.role == TeamRole.OWNER).first()
        )
        r = client.delete(f"{TEAMS}/{env.team.id}/members/{owner_member.id}", headers=auth)
        assert r.status_code == 400
        assert "至少保留一名所有者" in r.json()["detail"]

    def test_owner_can_leave_after_another_owner_added(self, client, db):
        env = Env(db)
        auth = _login(client, env.owner.username)
        url = f"{TEAMS}/{env.team.id}/members"
        member = client.post(url, json={"username": env.outsider.username}, headers=auth).json()
        client.patch(f"{url}/{member['id']}", json={"role": "owner"}, headers=auth)

        owner_member = (
            db.query(TeamMember)
            .filter(
                TeamMember.team_id == env.team.id, TeamMember.role == TeamRole.OWNER, TeamMember.user_id == env.owner.id
            )
            .first()
        )
        assert client.delete(f"{url}/{owner_member.id}", headers=auth).status_code == 204

    def test_workspace_team_not_found_is_404(self, client, db):
        env = Env(db)
        r = client.post(
            WORKSPACES, json={"name": "挂到不存在的团队", "team_id": 999999}, headers=_login(client, env.owner.username)
        )
        assert r.status_code == 404

    def test_empty_team_workspace_list(self, client, db):
        env = Env(db)
        empty_team = Team(name="空团队", slug="empty", description="", policy={}, created_by_id=env.owner.id)
        db.add(empty_team)
        db.flush()
        db.add(TeamMember(team_id=empty_team.id, user_id=env.owner.id, role=TeamRole.OWNER))
        db.commit()
        r = client.get(f"{TEAMS}/{empty_team.id}/workspaces", headers=_login(client, env.owner.username))
        assert r.status_code == 200, r.text
        assert r.json() == []


class TestPrivateVisibilityEnforced:
    """D6 收口（P2 补充）：`private` = 仅工作区所有者可见 / 可读."""

    def _set_private(self, client, auth, wid: int) -> None:
        r = client.patch(f"{WORKSPACES}/{wid}", json={"visibility": "private"}, headers=auth)
        assert r.status_code == 200, r.text

    def test_viewer_member_loses_read_but_still_owner_ok(self, client, db):
        env = Env(db)
        owner_auth = _login(client, env.owner.username)
        db.add(WorkspaceMember(workspace_id=env.ws.id, user_id=env.admin.id, role=WorkspaceRole.VIEWER))
        db.commit()
        self._set_private(client, owner_auth, env.ws.id)

        viewer_auth = _login(client, env.admin.username)
        assert client.get(f"{WORKSPACES}/{env.ws.id}", headers=viewer_auth).status_code == 404
        # 该用户同时是团队管理员：能力位端点 200，但数据面仍为 None（ADR 0161 D6 / I3）
        r = client.get(f"{WORKSPACES}/{env.ws.id}/capabilities", headers=viewer_auth)
        assert r.status_code == 200, r.text
        assert r.json()["data_role"] is None
        assert client.get(f"{WORKSPACES}/{env.ws.id}/members", headers=viewer_auth).status_code == 404
        assert client.get(f"{WORKSPACES}/{env.ws.id}", headers=owner_auth).status_code == 200

    def test_private_workspace_hidden_from_viewer_list(self, client, db):
        env = Env(db)
        owner_auth = _login(client, env.owner.username)
        db.add(WorkspaceMember(workspace_id=env.ws.id, user_id=env.admin.id, role=WorkspaceRole.EDITOR))
        db.commit()
        self._set_private(client, owner_auth, env.ws.id)

        viewer_ids = {item["id"] for item in client.get(WORKSPACES, headers=_login(client, env.admin.username)).json()}
        assert env.ws.id not in viewer_ids
        owner_ids = {item["id"] for item in client.get(WORKSPACES, headers=owner_auth).json()}
        assert env.ws.id in owner_ids

    def test_private_workspace_excluded_from_global_search(self, client, db):
        env = Env(db)
        owner_auth = _login(client, env.owner.username)
        db.add(WorkspaceMember(workspace_id=env.ws.id, user_id=env.admin.id, role=WorkspaceRole.VIEWER))
        client.post(f"{WORKSPACES}/{env.ws.id}/documents", json={"title": "私有工作区文档"}, headers=owner_auth)
        self._set_private(client, owner_auth, env.ws.id)

        body = client.get(
            "/api/v1/search", params={"q": "私有工作区文档"}, headers=_login(client, env.admin.username)
        ).json()
        assert body["documents"] == []
        owner_body = client.get("/api/v1/search", params={"q": "私有工作区文档"}, headers=owner_auth).json()
        assert any(doc["title"] == "私有工作区文档" for doc in owner_body["documents"])

    def test_private_blocks_team_member_public_read(self, client, db):
        """private 与 public 互斥：私有工作区不因团队成员身份获读."""
        env = Env(db)
        owner_auth = _login(client, env.owner.username)
        self._set_private(client, owner_auth, env.ws.id)
        assert client.get(f"{WORKSPACES}/{env.ws.id}", headers=_login(client, env.admin.username)).status_code == 404
