"""ADR 0161 P0：工作区 / 团队权限边界收紧（判定层 + 接口层）.

覆盖决策 D1 / D2 / D3 / D6 / D7 与不变量 H64-H67 的 P0 部分：

- 团队管理员不得把任何人（含自己）升为 owner，也不能转让 / 移除 owner；
- 团队管理员不得把自己加入所辖工作区（单 / 批端点）；
- 放宽 visibility / allow_edit 与变更 team_id 仅工作区所有者；
- 团队成员移除 / 降级不得操作角色高于自己的成员；
- `/capabilities` 对有管理面、无数据面的调用者返回 200；
- 系统管理员在统一入口按 owner 处理。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import (
    Team,
    TeamMember,
    TeamRole,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceTeamAccess,
    WorkspaceVisibility,
)
from cndb.plugins.workspaces.permissions import (
    WorkspaceCapability,
    resolve_capabilities,
    workspace_data_role,
)

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


@dataclass
class Env:
    owner: User  # 团队所有者 + 工作区所有者
    admin: User  # 团队管理员，非工作区成员
    viewer: User  # 工作区 viewer 成员，非团队成员
    team: Team
    ws: Workspace


def _env(db: Session, *, visibility: WorkspaceVisibility = WorkspaceVisibility.MEMBER) -> Env:
    owner = _make_user(db, "p2_owner", "张三")
    admin = _make_user(db, "p2_admin", "李四")
    viewer = _make_user(db, "p2_viewer", "王五")
    team = Team(name="研发部", slug="rd", description="", policy={}, created_by_id=owner.id)
    db.add(team)
    db.flush()
    db.add(TeamMember(team_id=team.id, user_id=owner.id, role=TeamRole.OWNER))
    db.add(TeamMember(team_id=team.id, user_id=admin.id, role=TeamRole.ADMIN))
    ws = Workspace(name="研发部工作区", created_by_id=owner.id, team_id=team.id, visibility=visibility)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
    db.commit()
    db.refresh(ws)
    db.refresh(team)
    return Env(owner=owner, admin=admin, viewer=viewer, team=team, ws=ws)


def _member_id(db: Session, workspace_id: int, user_id: int) -> int:
    row = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
        .first()
    )
    assert row is not None
    return row.id


class TestMemberEscalation:
    """D1 / D2：团队管理员不得进入 owner 层，也不得自加入。"""

    def test_team_admin_cannot_add_self(self, client, db):
        env = _env(db)
        auth = _login(client, env.admin.username)
        r = client.post(
            f"{WORKSPACES}/{env.ws.id}/members",
            json={"username": env.admin.username, "role": "viewer"},
            headers=auth,
        )
        assert r.status_code == 403, r.text
        assert (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == env.ws.id, WorkspaceMember.user_id == env.admin.id)
            .first()
            is None
        )

    def test_team_admin_can_add_other_member(self, client, db):
        env = _env(db)
        newcomer = _make_user(db, "p2_newcomer")
        r = client.post(
            f"{WORKSPACES}/{env.ws.id}/members",
            json={"username": newcomer.username, "role": "viewer"},
            headers=_login(client, env.admin.username),
        )
        assert r.status_code == 201, r.text

    def test_team_admin_batch_cannot_add_self(self, client, db):
        env = _env(db)
        newcomer = _make_user(db, "p2_batch_ok")
        r = client.post(
            f"{WORKSPACES}/{env.ws.id}/members/batch",
            json={
                "items": [
                    {"username": env.admin.username, "role": "viewer"},
                    {"username": newcomer.username, "role": "viewer"},
                ]
            },
            headers=_login(client, env.admin.username),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert env.admin.username not in body["added"]
        assert any(item["username"] == env.admin.username for item in body["errors"])
        assert newcomer.username in body["added"]

    def test_team_admin_cannot_promote_to_owner(self, client, db):
        env = _env(db)
        mid = _member_id(db, env.ws.id, env.viewer.id)
        r = client.patch(
            f"{WORKSPACES}/{env.ws.id}/members/{mid}",
            json={"role": "owner"},
            headers=_login(client, env.admin.username),
        )
        assert r.status_code == 403, r.text

    def test_team_admin_cannot_demote_owner(self, client, db):
        env = _env(db)
        mid = _member_id(db, env.ws.id, env.owner.id)
        r = client.patch(
            f"{WORKSPACES}/{env.ws.id}/members/{mid}",
            json={"role": "editor"},
            headers=_login(client, env.admin.username),
        )
        assert r.status_code == 403, r.text

    def test_team_admin_cannot_transfer_owner(self, client, db):
        env = _env(db)
        r = client.post(
            f"{WORKSPACES}/{env.ws.id}/owner",
            json={"user_id": env.viewer.id},
            headers=_login(client, env.admin.username),
        )
        assert r.status_code == 403, r.text
        owner_row = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == env.ws.id, WorkspaceMember.role == WorkspaceRole.OWNER)
            .first()
        )
        assert owner_row is not None and owner_row.user_id == env.owner.id

    def test_team_admin_cannot_remove_owner_even_with_multiple(self, client, db):
        env = _env(db)
        db.add(WorkspaceMember(workspace_id=env.ws.id, user_id=env.admin.id, role=WorkspaceRole.EDITOR))
        db.commit()
        second_owner = _make_user(db, "p2_second_owner")
        db.add(WorkspaceMember(workspace_id=env.ws.id, user_id=second_owner.id, role=WorkspaceRole.OWNER))
        db.commit()
        mid = _member_id(db, env.ws.id, env.owner.id)
        r = client.delete(f"{WORKSPACES}/{env.ws.id}/members/{mid}", headers=_login(client, env.admin.username))
        assert r.status_code == 403, r.text

    def test_team_admin_can_remove_viewer(self, client, db):
        env = _env(db)
        mid = _member_id(db, env.ws.id, env.viewer.id)
        r = client.delete(f"{WORKSPACES}/{env.ws.id}/members/{mid}", headers=_login(client, env.admin.username))
        assert r.status_code == 204, r.text

    def test_owner_can_still_promote_owner(self, client, db):
        env = _env(db)
        mid = _member_id(db, env.ws.id, env.viewer.id)
        r = client.patch(
            f"{WORKSPACES}/{env.ws.id}/members/{mid}",
            json={"role": "owner"},
            headers=_login(client, env.owner.username),
        )
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "owner"


class TestWorkspaceExposure:
    """D3：放宽暴露与团队归属仅工作区所有者。"""

    def test_team_admin_cannot_widen_visibility(self, client, db):
        env = _env(db)
        r = client.patch(
            f"{WORKSPACES}/{env.ws.id}",
            json={"visibility": "public"},
            headers=_login(client, env.admin.username),
        )
        assert r.status_code == 403, r.text

    def test_team_admin_can_narrow_visibility(self, client, db):
        env = _env(db, visibility=WorkspaceVisibility.PUBLIC)
        r = client.patch(
            f"{WORKSPACES}/{env.ws.id}",
            json={"visibility": "member"},
            headers=_login(client, env.admin.username),
        )
        assert r.status_code == 200, r.text
        assert r.json()["visibility"] == "member"

    def test_team_admin_cannot_enable_allow_edit(self, client, db):
        env = _env(db)
        env.ws.allow_edit = False
        db.commit()
        r = client.patch(
            f"{WORKSPACES}/{env.ws.id}",
            json={"allow_edit": True},
            headers=_login(client, env.admin.username),
        )
        assert r.status_code == 403, r.text

    def test_team_admin_cannot_detach_team(self, client, db):
        env = _env(db)
        r = client.patch(
            f"{WORKSPACES}/{env.ws.id}",
            json={"team_id": None},
            headers=_login(client, env.admin.username),
        )
        assert r.status_code == 403, r.text

    def test_owner_can_widen_visibility(self, client, db):
        env = _env(db)
        r = client.patch(
            f"{WORKSPACES}/{env.ws.id}",
            json={"visibility": "public"},
            headers=_login(client, env.owner.username),
        )
        assert r.status_code == 200, r.text
        assert r.json()["visibility"] == "public"


class TestTeamRankGuard:
    """D5：团队管理员不得移除 / 降级角色高于自己的成员。"""

    def test_admin_cannot_remove_team_owner(self, client, db):
        env = _env(db)
        second_owner = _make_user(db, "p2_team_owner2")
        db.add(TeamMember(team_id=env.ws.team_id, user_id=second_owner.id, role=TeamRole.OWNER))
        db.commit()
        owner_mid = (
            db.query(TeamMember)
            .filter(TeamMember.team_id == env.ws.team_id, TeamMember.user_id == env.owner.id)
            .first()
        )
        assert owner_mid is not None
        r = client.delete(
            f"{TEAMS}/{env.ws.team_id}/members/{owner_mid.id}", headers=_login(client, env.admin.username)
        )
        assert r.status_code == 403, r.text

    def test_admin_can_remove_member(self, client, db):
        env = _env(db)
        plain = _make_user(db, "p2_team_plain")
        row = TeamMember(team_id=env.ws.team_id, user_id=plain.id, role=TeamRole.MEMBER)
        db.add(row)
        db.commit()
        r = client.delete(f"{TEAMS}/{env.ws.team_id}/members/{row.id}", headers=_login(client, env.admin.username))
        assert r.status_code == 204, r.text


class TestCapabilitiesPayload:
    """D6：有管理面无数据面返回 200；纯 viewer 私有工作区仍 404。"""

    def test_team_admin_gets_management_capabilities(self, client, db):
        env = _env(db)
        r = client.get(f"{WORKSPACES}/{env.ws.id}/capabilities", headers=_login(client, env.admin.username))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["data_role"] is None
        assert "EDIT_SETTINGS" in body["capabilities"]
        assert "TRANSFER_OWNERSHIP" not in body["capabilities"]

    def test_private_viewer_gets_404(self, client, db):
        env = _env(db, visibility=WorkspaceVisibility.PRIVATE)
        r = client.get(f"{WORKSPACES}/{env.ws.id}/capabilities", headers=_login(client, env.viewer.username))
        assert r.status_code == 404, r.text

    def test_owner_capabilities_include_new_bits(self, client, db):
        env = _env(db)
        r = client.get(f"{WORKSPACES}/{env.ws.id}/capabilities", headers=_login(client, env.owner.username))
        assert r.status_code == 200, r.text
        caps = set(r.json()["capabilities"])
        assert {"TRANSFER_OWNERSHIP", "WIDEN_ACCESS"} <= caps


class TestUnifiedDataRole:
    """D4 / D7：判定层统一入口（资源层将在 P1 接入）。"""

    def test_private_editor_has_no_data_role(self, db):
        env = _env(db, visibility=WorkspaceVisibility.PRIVATE)
        editor = _make_user(db, "p2_editor")
        db.add(WorkspaceMember(workspace_id=env.ws.id, user_id=editor.id, role=WorkspaceRole.EDITOR))
        db.commit()
        assert workspace_data_role(editor, env.ws, db) is None
        # 原始成员角色仍存在，证明资源层若直查会绕过 private
        assert (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == env.ws.id, WorkspaceMember.user_id == editor.id)
            .first()
            .role
            is WorkspaceRole.EDITOR
        )

    def test_member_editor_keeps_data_role(self, db):
        env = _env(db)
        assert workspace_data_role(env.viewer, env.ws, db) is WorkspaceRole.VIEWER

    def test_private_owner_keeps_data_role(self, db):
        env = _env(db, visibility=WorkspaceVisibility.PRIVATE)
        assert workspace_data_role(env.owner, env.ws, db) is WorkspaceRole.OWNER

    def test_private_team_grant_does_not_override(self, db):
        """I3：private 下 team_grant 也不得放宽（只有 owner 有数据面）."""
        env = _env(db, visibility=WorkspaceVisibility.PRIVATE)
        db.add(
            WorkspaceTeamAccess(workspace_id=env.ws.id, team_id=env.team.id, role="viewer", granted_by_id=env.owner.id)
        )
        db.commit()
        assert workspace_data_role(env.admin, env.ws, db) is None

    def test_team_grant_viewer_is_consumed(self, db):
        """D4 反向：team_grant 的合法只读在统一入口生效（资源层 P1 开始消费）."""
        env = _env(db)
        db.add(
            WorkspaceTeamAccess(workspace_id=env.ws.id, team_id=env.team.id, role="viewer", granted_by_id=env.owner.id)
        )
        db.commit()
        assert workspace_data_role(env.admin, env.ws, db) is WorkspaceRole.VIEWER

    def test_policy_default_viewer_is_consumed(self, db):
        env = _env(db)
        env.team.policy = {"default_workspace_role": "viewer"}
        db.commit()
        assert workspace_data_role(env.admin, env.ws, db) is WorkspaceRole.VIEWER

    def test_public_grants_team_member_viewer(self, db):
        env = _env(db, visibility=WorkspaceVisibility.PUBLIC)
        assert workspace_data_role(env.admin, env.ws, db) is WorkspaceRole.VIEWER


class TestResourceLayerPrivate:
    """P1：private 工作区在资源层同样不生效（表 / 文档 / 设计 / 搜索）."""

    @staticmethod
    def _endpoints(ws_id: int) -> list[str]:
        return [
            f"{WORKSPACES}/{ws_id}/tables",
            f"{WORKSPACES}/{ws_id}/documents",
            f"{WORKSPACES}/{ws_id}/designs",
            f"{WORKSPACES}/{ws_id}/search?q=x",
            f"{WORKSPACES}/{ws_id}/document-issues",
            f"{WORKSPACES}/{ws_id}/document-change-requests",
        ]

    def test_private_editor_denied_everywhere(self, client, db):
        env = _env(db, visibility=WorkspaceVisibility.PRIVATE)
        editor = _make_user(db, "p1_private_editor")
        db.add(WorkspaceMember(workspace_id=env.ws.id, user_id=editor.id, role=WorkspaceRole.EDITOR))
        db.commit()
        auth = _login(client, editor.username)
        for path in self._endpoints(env.ws.id):
            r = client.get(path, headers=auth)
            assert r.status_code in (403, 404), f"{path} -> {r.status_code}: {r.text}"

    def test_private_owner_allowed(self, client, db):
        env = _env(db, visibility=WorkspaceVisibility.PRIVATE)
        auth = _login(client, env.owner.username)
        for path in self._endpoints(env.ws.id):
            r = client.get(path, headers=auth)
            assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text}"

    def test_member_workspace_editor_allowed(self, client, db):
        env = _env(db)
        editor = _make_user(db, "p1_member_editor")
        db.add(WorkspaceMember(workspace_id=env.ws.id, user_id=editor.id, role=WorkspaceRole.EDITOR))
        db.commit()
        auth = _login(client, editor.username)
        for path in self._endpoints(env.ws.id):
            r = client.get(path, headers=auth)
            assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text}"


class TestResourceLayerTeamAccess:
    """P1 反向：team_grant / policy / public 的合法只读在资源层被正确消费（不再 403）."""

    @staticmethod
    def _endpoints(ws_id: int) -> list[str]:
        return [
            f"{WORKSPACES}/{ws_id}/tables",
            f"{WORKSPACES}/{ws_id}/documents",
            f"{WORKSPACES}/{ws_id}/designs",
            f"{WORKSPACES}/{ws_id}/search?q=x",
        ]

    def _plain_team_member(self, db: Session, env: Env) -> User:
        user = _make_user(db, "p1_team_member")
        db.add(TeamMember(team_id=env.team.id, user_id=user.id, role=TeamRole.MEMBER))
        db.commit()
        return user

    def test_team_grant_viewer_reads(self, client, db):
        env = _env(db)
        user = self._plain_team_member(db, env)
        db.add(
            WorkspaceTeamAccess(workspace_id=env.ws.id, team_id=env.team.id, role="viewer", granted_by_id=env.owner.id)
        )
        db.commit()
        auth = _login(client, user.username)
        for path in self._endpoints(env.ws.id):
            r = client.get(path, headers=auth)
            assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text}"

    def test_policy_default_viewer_reads(self, client, db):
        env = _env(db)
        env.team.policy = {"default_workspace_role": "viewer"}
        db.commit()
        user = self._plain_team_member(db, env)
        auth = _login(client, user.username)
        for path in self._endpoints(env.ws.id):
            r = client.get(path, headers=auth)
            assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text}"

    def test_public_workspace_reads(self, client, db):
        env = _env(db, visibility=WorkspaceVisibility.PUBLIC)
        user = self._plain_team_member(db, env)
        auth = _login(client, user.username)
        for path in self._endpoints(env.ws.id):
            r = client.get(path, headers=auth)
            assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text}"

    def test_team_grant_does_not_write(self, client, db):
        """team_grant 只产 viewer：写入口仍 403（D11 不变）."""
        env = _env(db)
        user = self._plain_team_member(db, env)
        db.add(
            WorkspaceTeamAccess(workspace_id=env.ws.id, team_id=env.team.id, role="viewer", granted_by_id=env.owner.id)
        )
        db.commit()
        auth = _login(client, user.username)
        r = client.post(f"{WORKSPACES}/{env.ws.id}/tables", json={"name": "新表"}, headers=auth)
        assert r.status_code == 403, r.text


class TestSuperuserDataRole:
    """D7：系统管理员在统一入口按 owner 处理."""

    def test_superuser_is_workspace_owner(self, db):
        env = _env(db)
        su = _make_user(db, "p2_super")
        su.is_superuser = True
        db.commit()
        caps = resolve_capabilities(su, env.ws, db)
        assert caps.data_role is WorkspaceRole.OWNER
        assert caps.allows(WorkspaceCapability.TRANSFER_OWNERSHIP)
        assert caps.sources["manage"] == "superuser"
