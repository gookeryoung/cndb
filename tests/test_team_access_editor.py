"""ADR 0163：团队数据授权扩展为 viewer / editor（修订 ADR 0154 D11 / H57）.

锁定口径（ADR 0163 D2-D6）：
- `POST /team-access` 可授 editor，仍只产 `data_role`，不产任何管理面（I1 / H57）；
- 覆盖语义：同 (工作区, 团队) 唯一行，显式传 role 时覆盖角色（D2）；
- 链接批准不降级：链接路径不传 role，已有 editor 授权保持 editor（D3）；
- `private` 不放宽（I2）；显式成员优先于授权（D5）；
- 事件摘要按角色写「只读 / 编辑」（D6）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.core.events import CoreEvent
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


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user(db: Session, username: str):
    from cndb.plugins.accounts.models import User

    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class Env:
    """源工作区（仅 owner）+ 两个外部团队（成员不是源工作区成员）。"""

    def __init__(self, db: Session) -> None:
        self.owner = _user(db, "t63_owner")
        self.member_a = _user(db, "t63_member_a")
        self.member_b = _user(db, "t63_member_b")

        self.source = Workspace(name="共享源", created_by_id=self.owner.id)
        db.add(self.source)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.source.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))

        self.team_a = Team(name="团队A", slug="t63a", description="", policy={}, created_by_id=self.owner.id)
        self.team_b = Team(name="团队B", slug="t63b", description="", policy={}, created_by_id=self.owner.id)
        db.add_all([self.team_a, self.team_b])
        db.flush()
        db.add(TeamMember(team_id=self.team_a.id, user_id=self.member_a.id, role=TeamRole.MEMBER))
        db.add(TeamMember(team_id=self.team_b.id, user_id=self.member_b.id, role=TeamRole.MEMBER))
        db.commit()
        db.refresh(self.source)


@pytest.fixture()
def env(db: Session) -> Env:
    return Env(db)


class TestGrantEditorApi:
    def test_owner_grants_editor(self, client, db, env):
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{WS}/{env.source.id}/team-access",
            json={"team_id": env.team_a.id, "role": "editor", "ttl_days": 10},
            headers=auth,
        )
        assert r.status_code == 201, r.text
        assert r.json()["role"] == "editor"

        db.expire_all()
        caps = resolve_capabilities(env.member_a, env.source, db)
        assert caps.data_role is WorkspaceRole.EDITOR
        assert caps.sources["data"] == "team_grant:editor"
        # I1：只产数据面，editor 数据面允许写，但不产任何管理面能力位
        assert caps.allows(WorkspaceCapability.WRITE)
        assert not caps.allows(WorkspaceCapability.EDIT_SETTINGS)
        assert not caps.allows(WorkspaceCapability.MANAGE_MEMBERS)
        assert not caps.allows(WorkspaceCapability.MANAGE_ACCESS)
        assert "manage" not in caps.sources

    def test_role_default_is_viewer(self, client, db, env):
        auth = _login(client, env.owner.username)
        r = client.post(f"{WS}/{env.source.id}/team-access", json={"team_id": env.team_a.id}, headers=auth)
        assert r.status_code == 201
        assert r.json()["role"] == "viewer"

    def test_role_invalid_is_422(self, client, db, env):
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{WS}/{env.source.id}/team-access",
            json={"team_id": env.team_a.id, "role": "owner"},
            headers=auth,
        )
        assert r.status_code == 422

    def test_non_owner_cannot_grant_editor(self, client, db, env):
        editor = _user(db, "t63_editor")
        db.add(WorkspaceMember(workspace_id=env.source.id, user_id=editor.id, role=WorkspaceRole.EDITOR))
        db.commit()
        r = client.post(
            f"{WS}/{env.source.id}/team-access",
            json={"team_id": env.team_a.id, "role": "editor"},
            headers=_login(client, editor.username),
        )
        assert r.status_code == 403

    def test_regrant_overwrites_role(self, client, db, env):
        """显式传 role 覆盖已有行（D2）；行数不增。"""
        auth = _login(client, env.owner.username)
        first = client.post(
            f"{WS}/{env.source.id}/team-access", json={"team_id": env.team_a.id, "role": "editor"}, headers=auth
        ).json()
        second = client.post(
            f"{WS}/{env.source.id}/team-access",
            json={"team_id": env.team_a.id, "role": "viewer", "ttl_days": 90},
            headers=auth,
        ).json()
        assert second["id"] == first["id"]
        assert second["role"] == "viewer"
        db.expire_all()
        assert db.query(WorkspaceTeamAccess).filter(WorkspaceTeamAccess.workspace_id == env.source.id).count() == 1

    def test_grant_event_summary_mentions_editor(self, client, db, env):
        auth = _login(client, env.owner.username)
        client.post(
            f"{WS}/{env.source.id}/team-access", json={"team_id": env.team_a.id, "role": "editor"}, headers=auth
        )
        event = (
            db.query(CoreEvent)
            .filter(CoreEvent.action == "workspace.team_access_grant")
            .order_by(CoreEvent.id.desc())
            .first()
        )
        assert event is not None
        assert "编辑" in event.summary


class TestEditorGrantBoundaries:
    def test_private_workspace_not_widened(self, db, env):
        """I2：private 工作区的 editor 授权不放宽数据面（H66）。"""
        env.source.visibility = WorkspaceVisibility.PRIVATE
        db.commit()
        db.add(
            WorkspaceTeamAccess(
                workspace_id=env.source.id, team_id=env.team_a.id, role="editor", granted_by_id=env.owner.id
            )
        )
        db.commit()
        caps = resolve_capabilities(env.member_a, env.source, db)
        assert caps.data_role is None
        assert caps.sources["data"].startswith("workspace_private")

    def test_explicit_member_role_beats_editor_grant(self, db, env):
        """D5：显式成员角色优先，团队授权永不覆盖显式角色。"""
        db.add(
            WorkspaceTeamAccess(
                workspace_id=env.source.id, team_id=env.team_a.id, role="editor", granted_by_id=env.owner.id
            )
        )
        db.add(WorkspaceMember(workspace_id=env.source.id, user_id=env.member_a.id, role=WorkspaceRole.VIEWER))
        db.commit()
        caps = resolve_capabilities(env.member_a, env.source, db)
        assert caps.data_role is WorkspaceRole.VIEWER
        assert caps.sources["data"] == "workspace_member:viewer"

    def test_multi_team_hits_take_highest_rank(self, db, env):
        """C1 / C3：用户分属多团队，工作区对不同团队授权，取角色最高命中。"""
        db.add_all(
            [
                WorkspaceTeamAccess(
                    workspace_id=env.source.id, team_id=env.team_a.id, role="viewer", granted_by_id=env.owner.id
                ),
                WorkspaceTeamAccess(
                    workspace_id=env.source.id, team_id=env.team_b.id, role="editor", granted_by_id=env.owner.id
                ),
            ]
        )
        # member_a 同时属于两个团队（非工作区成员，走授权分支）
        db.add(TeamMember(team_id=env.team_b.id, user_id=env.member_a.id, role=TeamRole.MEMBER))
        db.commit()
        caps = resolve_capabilities(env.member_a, env.source, db)
        assert caps.data_role is WorkspaceRole.EDITOR
        assert caps.sources["data"] == "team_grant:editor"


class TestDeniedDetailAttribution:
    def test_grant_editor_denied_detail_mentions_team_grant(self, db, env):
        """D6：持有 editor 团队授权被管理面拒绝时，403 文案归因到「团队授权 · 编辑」。"""
        from cndb.plugins.workspaces.permissions import permission_denied_detail

        db.add(
            WorkspaceTeamAccess(
                workspace_id=env.source.id, team_id=env.team_a.id, role="editor", granted_by_id=env.owner.id
            )
        )
        db.commit()
        detail = permission_denied_detail(db, env.source, env.member_a, scope="表级")
        assert "团队【团队A】的编辑授权" in detail
        assert "不含管理权限" in detail
        assert "你不是该工作区成员" in detail

    def test_no_grant_detail_unchanged(self, db, env):
        """无授权时文案不含授权归因段（存量口径不变）。"""
        from cndb.plugins.workspaces.permissions import permission_denied_detail

        detail = permission_denied_detail(db, env.source, env.member_a)
        assert "来自团队" not in detail


class TestLinkDoesNotDowngrade:
    def _table(self, db: Session, env: Env) -> DataTable:
        table = DataTable(
            workspace_id=env.source.id,
            owner_id=env.owner.id,
            name="明细",
            description="",
            db_table_name="t_t63_detail",
        )
        db.add(table)
        db.commit()
        db.refresh(table)
        return table

    def test_link_approve_preserves_existing_editor_grant(self, client, db, env):
        """D3：链接批准覆盖同一行时不把已有 editor 授权静默降级成 viewer。"""
        db.add(
            WorkspaceTeamAccess(
                workspace_id=env.source.id,
                team_id=env.team_a.id,
                role="editor",
                granted_by_id=env.owner.id,
                note="独立授权",
            )
        )
        db.commit()
        table = self._table(db, env)

        consumer = Workspace(name="消费方", created_by_id=env.member_a.id)
        db.add(consumer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=consumer.id, user_id=env.member_a.id, role=WorkspaceRole.OWNER))
        db.commit()
        db.refresh(consumer)

        con_auth = _login(client, env.member_a.username)
        link = client.post(
            f"{WS}/{consumer.id}/links",
            json={
                "source_workspace_id": env.source.id,
                "target_table_id": table.id,
                "audience": "team",
                "team_id": env.team_a.id,
                "ttl_days": 7,
            },
            headers=con_auth,
        )
        assert link.status_code == 201, link.text
        r = client.post(
            f"{WS}/{env.source.id}/links/{link.json()['id']}/approve",
            json={},
            headers=_login(client, env.owner.username),
        )
        assert r.status_code == 200, r.text

        db.expire_all()
        row = db.query(WorkspaceTeamAccess).filter(WorkspaceTeamAccess.workspace_id == env.source.id).one()
        # 链接行覆盖了 note，但 role 保持 editor（不降级）
        assert row.role == "editor"
