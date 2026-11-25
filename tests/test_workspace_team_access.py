"""ADR 0154 P3.1（B′）：团队数据授权（`workspace_team_access`）与 `team_grant` 判定.

锁定口径（D11 / H57）：
- 团队授权只产 `data_role=viewer`，**不产管理面**（`can_manage=False`）；
- 到期惰性失效，无需清扫；
- 显式工作区角色优先于团队授权；
- 私有工作区（D6）不因团队授权而放宽；
- 链接可以按受众 `team` 批准，撤回时只回收「它创建」的那条授权。
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable
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
from cndb.plugins.workspaces.permissions import WorkspaceCapability, resolve_capabilities

WS = "/api/v1/workspaces"
TEAMS = "/api/v1/teams"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class Env:
    """源工作区（owner + editor）与一个**外部团队**（其成员不是源工作区成员）。"""

    def __init__(self, db: Session) -> None:
        self.owner = _user(db, "ta_owner")
        self.editor = _user(db, "ta_editor")
        self.team_member = _user(db, "ta_team_member")

        self.source = Workspace(name="授权源", created_by_id=self.owner.id)
        db.add(self.source)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.source.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        db.add(WorkspaceMember(workspace_id=self.source.id, user_id=self.editor.id, role=WorkspaceRole.EDITOR))

        self.team = Team(name="分析部", slug="ta", description="", policy={}, created_by_id=self.owner.id)
        db.add(self.team)
        db.flush()
        db.add(TeamMember(team_id=self.team.id, user_id=self.owner.id, role=TeamRole.OWNER))
        db.add(TeamMember(team_id=self.team.id, user_id=self.team_member.id, role=TeamRole.MEMBER))
        db.commit()
        db.refresh(self.source)
        db.refresh(self.team)


@pytest.fixture()
def env(db: Session) -> Env:
    return Env(db)


class TestGrantCrud:
    def test_owner_grants_and_lists(self, client, db, env):
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{WS}/{env.source.id}/team-access",
            json={"team_id": env.team.id, "ttl_days": 10, "note": "季度汇总"},
            headers=auth,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["team_name"] == "分析部"
        assert body["role"] == "viewer"
        assert body["active"] is True
        assert body["expires_at"] is not None

        listed = client.get(f"{WS}/{env.source.id}/team-access", headers=auth).json()
        assert [row["id"] for row in listed] == [body["id"]]

    def test_editor_cannot_grant_or_list(self, client, db, env):
        auth = _login(client, env.editor.username)
        assert (
            client.post(f"{WS}/{env.source.id}/team-access", json={"team_id": env.team.id}, headers=auth).status_code
            == 403
        )
        assert client.get(f"{WS}/{env.source.id}/team-access", headers=auth).status_code == 403

    def test_unknown_team_is_404(self, client, db, env):
        r = client.post(
            f"{WS}/{env.source.id}/team-access", json={"team_id": 999999}, headers=_login(client, env.owner.username)
        )
        assert r.status_code == 404

    def test_cannot_grant_to_own_team(self, client, db, env):
        """把工作区授给它自己所属的团队没有意义（成员本就按团队可见）."""
        env.source.team_id = env.team.id
        db.commit()
        r = client.post(
            f"{WS}/{env.source.id}/team-access",
            json={"team_id": env.team.id},
            headers=_login(client, env.owner.username),
        )
        assert r.status_code == 400

    def test_regrant_overwrites(self, client, db, env):
        auth = _login(client, env.owner.username)
        first = client.post(f"{WS}/{env.source.id}/team-access", json={"team_id": env.team.id}, headers=auth).json()
        second = client.post(
            f"{WS}/{env.source.id}/team-access",
            json={"team_id": env.team.id, "ttl_days": 90, "note": "续期"},
            headers=auth,
        ).json()
        assert second["id"] == first["id"]
        assert second["note"] == "续期"
        db.expire_all()
        assert db.query(WorkspaceTeamAccess).filter(WorkspaceTeamAccess.workspace_id == env.source.id).count() == 1

    def test_ttl_out_of_range_is_422(self, client, db, env):
        auth = _login(client, env.owner.username)
        r = client.post(f"{WS}/{env.source.id}/team-access", json={"team_id": env.team.id, "ttl_days": 0}, headers=auth)
        assert r.status_code == 422

    def test_revoke(self, client, db, env):
        auth = _login(client, env.owner.username)
        row = client.post(f"{WS}/{env.source.id}/team-access", json={"team_id": env.team.id}, headers=auth).json()
        assert client.delete(f"{WS}/{env.source.id}/team-access/{row['id']}", headers=auth).status_code == 204
        assert client.get(f"{WS}/{env.source.id}/team-access", headers=auth).json() == []
        assert client.delete(f"{WS}/{env.source.id}/team-access/{row['id']}", headers=auth).status_code == 404


class TestResolution:
    def _grant(self, db: Session, env: Env, *, expires_at: dt.datetime | None) -> WorkspaceTeamAccess:
        row = WorkspaceTeamAccess(
            workspace_id=env.source.id,
            team_id=env.team.id,
            role="viewer",
            expires_at=expires_at,
            granted_by_id=env.owner.id,
        )
        db.add(row)
        db.commit()
        return row

    def test_team_member_gets_viewer_data_role_without_manage(self, db, env):
        self._grant(db, env, expires_at=None)
        caps = resolve_capabilities(env.team_member, env.source, db)
        assert caps.data_role is WorkspaceRole.VIEWER
        assert caps.sources["data"] == "team_grant:viewer"
        assert caps.allows(WorkspaceCapability.READ)
        assert not caps.allows(WorkspaceCapability.WRITE)
        # D11 / H57：不产任何管理面能力位
        assert not caps.allows(WorkspaceCapability.EDIT_SETTINGS)
        assert not caps.allows(WorkspaceCapability.MANAGE_MEMBERS)
        assert not caps.allows(WorkspaceCapability.MANAGE_LINKS)
        assert "manage" not in caps.sources

    def test_expired_grant_is_ignored(self, db, env):
        self._grant(db, env, expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1))
        assert resolve_capabilities(env.team_member, env.source, db).data_role is None

    def test_explicit_member_role_beats_grant(self, db, env):
        self._grant(db, env, expires_at=None)
        db.add(WorkspaceMember(workspace_id=env.source.id, user_id=env.team_member.id, role=WorkspaceRole.EDITOR))
        db.commit()
        caps = resolve_capabilities(env.team_member, env.source, db)
        assert caps.data_role is WorkspaceRole.EDITOR
        assert caps.sources["data"] == "workspace_member:editor"

    def test_private_workspace_still_owner_only(self, db, env):
        env.source.visibility = WorkspaceVisibility.PRIVATE
        db.commit()
        self._grant(db, env, expires_at=None)
        caps = resolve_capabilities(env.team_member, env.source, db)
        assert caps.data_role is None
        assert caps.sources["data"].startswith("workspace_private")

    def test_editor_grant_is_honored_and_bogus_role_ignored(self, db, env):
        """库里存在非 viewer 的合法角色时按角色等级取最高；非法角色跳过（防御脏数据）."""
        db.add(
            WorkspaceTeamAccess(
                workspace_id=env.source.id, team_id=env.team.id, role="editor", granted_by_id=env.owner.id
            )
        )
        db.commit()
        caps = resolve_capabilities(env.team_member, env.source, db)
        assert caps.data_role is WorkspaceRole.EDITOR
        assert "manage" not in caps.sources

        # 非法角色（历史脏数据）不生效
        db.query(WorkspaceTeamAccess).update({WorkspaceTeamAccess.role: "boss"})
        db.commit()
        db.expire_all()
        assert resolve_capabilities(env.team_member, env.source, db).data_role is None

    def test_non_team_member_unaffected(self, db, env):
        outsider = _user(db, "ta_outsider")
        self._grant(db, env, expires_at=None)
        assert resolve_capabilities(outsider, env.source, db).data_role is None


class TestLinkWithTeamAudience:
    def test_apply_and_approve_creates_team_grant(self, client, db, env):
        table = DataTable(
            workspace_id=env.source.id,
            owner_id=env.owner.id,
            name="明细",
            description="",
            db_table_name="t_ta_sales2",
        )
        db.add(table)
        db.commit()
        db.refresh(table)

        # 消费方 = 团队成员自己的（个人）工作区
        consumer = Workspace(name="分析部汇总", created_by_id=env.team_member.id)
        db.add(consumer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=consumer.id, user_id=env.team_member.id, role=WorkspaceRole.OWNER))
        db.commit()
        db.refresh(consumer)

        con_auth = _login(client, env.team_member.username)
        link = client.post(
            f"{WS}/{consumer.id}/links",
            json={
                "source_workspace_id": env.source.id,
                "target_table_id": table.id,
                "audience": "team",
                "team_id": env.team.id,
                "ttl_days": 7,
            },
            headers=con_auth,
        )
        assert link.status_code == 201, link.text
        assert link.json()["audience"] == "team"
        assert link.json()["granted_team_name"] == "分析部"

        src_auth = _login(client, env.owner.username)
        r = client.post(f"{WS}/{env.source.id}/links/{link.json()['id']}/approve", json={}, headers=src_auth)
        assert r.status_code == 200, r.text

        # 只写了团队授权行，没有批量加成员
        db.expire_all()
        assert db.query(WorkspaceTeamAccess).filter(WorkspaceTeamAccess.workspace_id == env.source.id).count() == 1
        assert (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == env.source.id, WorkspaceMember.user_id == env.team_member.id)
            .first()
            is None
        )
        # 团队成员因此获得只读（links 取数走同一判定）
        caps = resolve_capabilities(env.team_member, env.source, db)
        assert caps.data_role is WorkspaceRole.VIEWER

    def test_audience_team_requires_membership_and_team_id(self, client, db, env):
        table = DataTable(
            workspace_id=env.source.id,
            owner_id=env.owner.id,
            name="明细2",
            description="",
            db_table_name="t_ta_sales3",
        )
        db.add(table)
        db.commit()
        db.refresh(table)

        consumer = Workspace(name="某汇总", created_by_id=env.owner.id)
        db.add(consumer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=consumer.id, user_id=env.owner.id, role=WorkspaceRole.OWNER))
        db.commit()
        db.refresh(consumer)

        auth = _login(client, env.owner.username)
        # 缺 team_id
        assert (
            client.post(
                f"{WS}/{consumer.id}/links",
                json={"source_workspace_id": env.source.id, "target_table_id": table.id, "audience": "team"},
                headers=auth,
            ).status_code
            == 400
        )

        # 授给一个自己不在其中的团队 → 403
        other_team = Team(name="别的团队", slug="ta-other", description="", policy={}, created_by_id=env.owner.id)
        db.add(other_team)
        db.commit()
        assert (
            client.post(
                f"{WS}/{consumer.id}/links",
                json={
                    "source_workspace_id": env.source.id,
                    "target_table_id": table.id,
                    "audience": "team",
                    "team_id": other_team.id,
                },
                headers=auth,
            ).status_code
            == 403
        )

    def test_approve_fails_when_team_deleted(self, client, db, env):
        table = DataTable(
            workspace_id=env.source.id,
            owner_id=env.owner.id,
            name="明细4",
            description="",
            db_table_name="t_ta_sales5",
        )
        db.add(table)
        db.commit()
        db.refresh(table)
        consumer = Workspace(name="汇总4", created_by_id=env.team_member.id)
        db.add(consumer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=consumer.id, user_id=env.team_member.id, role=WorkspaceRole.OWNER))
        db.commit()
        db.refresh(consumer)

        con_auth = _login(client, env.team_member.username)
        link = client.post(
            f"{WS}/{consumer.id}/links",
            json={
                "source_workspace_id": env.source.id,
                "target_table_id": table.id,
                "audience": "team",
                "team_id": env.team.id,
            },
            headers=con_auth,
        ).json()

        # 批准前团队被删 → 400（不静默放行）
        db.query(WorkspaceTeamAccess).delete()
        team = db.get(Team, env.team.id)
        db.delete(team)
        db.commit()

        r = client.post(
            f"{WS}/{env.source.id}/links/{link['id']}/approve",
            json={},
            headers=_login(client, env.owner.username),
        )
        assert r.status_code == 400

    def test_revoke_link_only_removes_its_own_grant(self, client, db, env):
        table = DataTable(
            workspace_id=env.source.id,
            owner_id=env.owner.id,
            name="明细3",
            description="",
            db_table_name="t_ta_sales4",
        )
        db.add(table)
        db.commit()
        db.refresh(table)
        consumer = Workspace(name="汇总3", created_by_id=env.team_member.id)
        db.add(consumer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=consumer.id, user_id=env.team_member.id, role=WorkspaceRole.OWNER))
        db.commit()
        db.refresh(consumer)

        # 先有一条「独立」团队授权（手工授的）
        independent = WorkspaceTeamAccess(
            workspace_id=env.source.id, team_id=env.team.id, role="viewer", granted_by_id=env.owner.id, note="独立授权"
        )
        db.add(independent)
        db.commit()

        con_auth = _login(client, env.team_member.username)
        link = client.post(
            f"{WS}/{consumer.id}/links",
            json={
                "source_workspace_id": env.source.id,
                "target_table_id": table.id,
                "audience": "team",
                "team_id": env.team.id,
            },
            headers=con_auth,
        ).json()
        src_auth = _login(client, env.owner.username)
        client.post(f"{WS}/{env.source.id}/links/{link['id']}/approve", json={}, headers=src_auth)

        # 同 (工作区, 团队) 只有一行：链接批准覆盖了独立授权（覆盖语义，见 D3 说明）
        db.expire_all()
        rows = db.query(WorkspaceTeamAccess).filter(WorkspaceTeamAccess.workspace_id == env.source.id).all()
        assert len(rows) == 1
        assert rows[0].note.startswith("link:")

        assert client.delete(f"{WS}/{consumer.id}/links/{link['id']}", headers=con_auth).status_code == 204
        db.expire_all()
        assert db.query(WorkspaceTeamAccess).filter(WorkspaceTeamAccess.workspace_id == env.source.id).count() == 0
