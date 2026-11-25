"""ADR 0154 P0：工作区链接的申请 / 批准 / 拒绝 / 撤回（接口层）.

P0 只做生命周期与授权落地，**不提供取数**（fields / rows / export 在 P1）。

锁定口径：
- A 期批准 = 把受众批量加为源工作区真实 `viewer`（L1：链接不授予权限）；
- 只删「链接创建」的成员（L9 / D9）；撤回不影响原有成员；
- 门控：消费方 `EDIT_SETTINGS`、源工作区 `MANAGE_LINKS`（仅所有者）；
- 重复 active → 400；别名冲突 → 400；自身链接 → 400。
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.core.events import CoreEvent
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, DataView
from cndb.plugins.workspaces.models import Workspace, WorkspaceLink, WorkspaceLinkStatus, WorkspaceMember, WorkspaceRole

WS = "/api/v1/workspaces"
LINKS = "/api/v1/workspaces/{wid}/links"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_user(db: Session, username: str) -> User:
    u = User(username=username, nickname=f"{username}-昵称")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class Env:
    """consumer（消费方）与 source（源工作区）各自有 owner + 一个普通成员。"""

    def __init__(self, db: Session) -> None:
        self.source_owner = _make_user(db, "link_src_owner")
        self.consumer_owner = _make_user(db, "link_con_owner")
        self.consumer_member = _make_user(db, "link_con_member")

        self.source = Workspace(name="源工作区", created_by_id=self.source_owner.id)
        self.consumer = Workspace(name="消费方工作区", created_by_id=self.consumer_owner.id)
        db.add_all([self.source, self.consumer])
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.source.id, user_id=self.source_owner.id, role=WorkspaceRole.OWNER))
        db.add(WorkspaceMember(workspace_id=self.consumer.id, user_id=self.consumer_owner.id, role=WorkspaceRole.OWNER))
        db.add(
            WorkspaceMember(workspace_id=self.consumer.id, user_id=self.consumer_member.id, role=WorkspaceRole.VIEWER)
        )

        self.table = DataTable(
            workspace_id=self.source.id,
            owner_id=self.source_owner.id,
            name="销售明细",
            description="",
            db_table_name="t_link_sales",
        )
        db.add(self.table)
        db.commit()
        db.refresh(self.table)
        db.refresh(self.source)
        db.refresh(self.consumer)


@pytest.fixture()
def env(db: Session) -> Env:
    return Env(db)


def _apply(client: TestClient, env: Env, auth: dict[str, str], **overrides) -> dict:
    payload = {
        "source_workspace_id": env.source.id,
        "target_table_id": env.table.id,
        "ttl_days": 30,
        "note": "汇总用",
    }
    payload.update(overrides)
    r = client.post(LINKS.format(wid=env.consumer.id), json=payload, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


class TestApply:
    def test_apply_creates_pending_link(self, client, db, env):
        auth = _login(client, env.consumer_owner.username)
        body = _apply(client, env, auth)
        assert body["status"] == "pending"
        assert body["source_workspace_name"] == "源工作区"
        assert body["target_table_name"] == "销售明细"
        assert body["alias"] == "销售明细"
        assert body["readable"] is False  # 未批准 → 入口不可用
        assert body["approved_by_name"] is None

        listed = client.get(LINKS.format(wid=env.consumer.id), headers=auth).json()
        assert [item["id"] for item in listed] == [body["id"]]

    def test_member_without_edit_settings_cannot_apply(self, client, db, env):
        auth = _login(client, env.consumer_member.username)
        r = client.post(
            LINKS.format(wid=env.consumer.id),
            json={"source_workspace_id": env.source.id, "target_table_id": env.table.id},
            headers=auth,
        )
        assert r.status_code == 403, r.text

    def test_cannot_link_self(self, client, db, env):
        auth = _login(client, env.consumer_owner.username)
        r = client.post(
            LINKS.format(wid=env.consumer.id),
            json={"source_workspace_id": env.consumer.id, "target_table_id": env.table.id},
            headers=auth,
        )
        assert r.status_code == 400

    def test_target_must_belong_to_source_workspace(self, client, db, env):
        auth = _login(client, env.consumer_owner.username)
        other_table = DataTable(
            workspace_id=env.consumer.id,
            owner_id=env.consumer_owner.id,
            name="别的表",
            description="",
            db_table_name="t_link_other",
        )
        db.add(other_table)
        db.commit()
        r = client.post(
            LINKS.format(wid=env.consumer.id),
            json={"source_workspace_id": env.source.id, "target_table_id": other_table.id},
            headers=auth,
        )
        assert r.status_code == 404

    def test_alias_conflict_and_ttl_validation(self, client, db, env):
        auth = _login(client, env.consumer_owner.username)
        _apply(client, env, auth, alias="汇总")
        r = client.post(
            LINKS.format(wid=env.consumer.id),
            json={"source_workspace_id": env.source.id, "target_table_id": env.table.id, "alias": "汇总"},
            headers=auth,
        )
        assert r.status_code == 400
        r = client.post(
            LINKS.format(wid=env.consumer.id),
            json={"source_workspace_id": env.source.id, "target_table_id": env.table.id, "ttl_days": 0},
            headers=auth,
        )
        assert r.status_code == 422


class TestApprove:
    def test_source_owner_approves_and_grants_viewer(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        src_auth = _login(client, env.source_owner.username)

        inbox = client.get(f"{LINKS.format(wid=env.source.id)}/inbox", headers=src_auth).json()
        assert [item["id"] for item in inbox] == [link["id"]]

        r = client.post(
            f"{LINKS.format(wid=env.source.id)}/{link['id']}/approve", json={"ttl_days": 7}, headers=src_auth
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "active"
        assert body["ttl_days"] == 7
        assert body["approved_by_name"] == "link_src_owner-昵称"
        assert body["expires_at"] is not None

        # 受众（消费方成员）已被加为源工作区 viewer —— 链接本身不授权，成员行才是授权（L1）
        db.expire_all()
        ids = {
            row[0]
            for row in db.query(WorkspaceMember.user_id).filter(WorkspaceMember.workspace_id == env.source.id).all()
        }
        assert ids == {env.source_owner.id, env.consumer_owner.id, env.consumer_member.id}

        # 批准后 readable 对消费方成员为 True
        body = client.get(LINKS.format(wid=env.consumer.id), headers=con_auth).json()[0]
        assert body["readable"] is True

    def test_only_owner_can_approve(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        # 源工作区的普通成员（借批准前先加为 editor）无权审批
        editor = _make_user(db, "link_src_editor")
        db.add(WorkspaceMember(workspace_id=env.source.id, user_id=editor.id, role=WorkspaceRole.EDITOR))
        db.commit()
        r = client.post(
            f"{LINKS.format(wid=env.source.id)}/{link['id']}/approve",
            json={},
            headers=_login(client, editor.username),
        )
        assert r.status_code == 403, r.text

    def test_approve_requires_pending(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        src_auth = _login(client, env.source_owner.username)
        assert (
            client.post(f"{LINKS.format(wid=env.source.id)}/{link['id']}/reject", headers=src_auth).status_code == 200
        )
        r = client.post(f"{LINKS.format(wid=env.source.id)}/{link['id']}/approve", json={}, headers=src_auth)
        assert r.status_code == 400

    def test_duplicate_active_rejected(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        src_auth = _login(client, env.source_owner.username)
        first = _apply(client, env, con_auth)
        client.post(f"{LINKS.format(wid=env.source.id)}/{first['id']}/approve", json={}, headers=src_auth)

        r = client.post(
            LINKS.format(wid=env.consumer.id),
            json={"source_workspace_id": env.source.id, "target_table_id": env.table.id},
            headers=con_auth,
        )
        assert r.status_code == 400
        assert "生效中的链接" in r.json()["detail"]

    def test_approve_writes_audit_event(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        client.post(
            f"{LINKS.format(wid=env.source.id)}/{link['id']}/approve",
            json={},
            headers=_login(client, env.source_owner.username),
        )
        actions = {row[0] for row in db.query(CoreEvent.action).filter(CoreEvent.action.like("workspace.link%")).all()}
        assert {"workspace.link_request", "workspace.link_approve"} <= actions


class TestRejectAndRevoke:
    def test_reject(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        r = client.post(
            f"{LINKS.format(wid=env.source.id)}/{link['id']}/reject",
            headers=_login(client, env.source_owner.username),
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "rejected"

    def test_consumer_owner_revokes_and_keeps_existing_members(self, client, db, env):
        # 先让消费方成员「原本就是」源工作区成员（模拟历史协作关系）
        db.add(WorkspaceMember(workspace_id=env.source.id, user_id=env.consumer_member.id, role=WorkspaceRole.EDITOR))
        db.commit()

        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        src_auth = _login(client, env.source_owner.username)
        client.post(f"{LINKS.format(wid=env.source.id)}/{link['id']}/approve", json={}, headers=src_auth)

        db.expire_all()
        stored = db.get(WorkspaceLink, link["id"])
        assert env.consumer_member.id not in (stored.created_member_ids or [])  # L9：原本就在的不算「创建」
        assert env.consumer_owner.id in (stored.created_member_ids or [])

        r = client.delete(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}", headers=con_auth)
        assert r.status_code == 204, r.text

        db.expire_all()
        remaining = {
            row[0]
            for row in db.query(WorkspaceMember.user_id).filter(WorkspaceMember.workspace_id == env.source.id).all()
        }
        # 原有成员（含被提升为 editor 的那位）保留；链接创建的 owner 成员被回收
        assert env.consumer_member.id in remaining
        assert env.consumer_owner.id not in remaining
        assert db.get(WorkspaceLink, link["id"]) is None

    def test_source_owner_can_revoke(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        src_auth = _login(client, env.source_owner.username)
        client.post(f"{LINKS.format(wid=env.source.id)}/{link['id']}/approve", json={}, headers=src_auth)
        assert client.delete(f"{LINKS.format(wid=env.source.id)}/{link['id']}", headers=src_auth).status_code == 204

    def test_viewer_cannot_revoke(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        r = client.delete(
            f"{LINKS.format(wid=env.consumer.id)}/{link['id']}",
            headers=_login(client, env.consumer_member.username),
        )
        assert r.status_code == 403

    def test_unknown_link_is_404(self, client, db, env):
        auth = _login(client, env.consumer_owner.username)
        assert client.delete(f"{LINKS.format(wid=env.consumer.id)}/999999", headers=auth).status_code == 404
        assert (
            client.post(f"{LINKS.format(wid=env.consumer.id)}/999999/approve", json={}, headers=auth).status_code == 404
        )
        # 自己的工作区没有待批准链接 → 空列表（owner 有 MANAGE_LINKS）
        assert client.get(f"{LINKS.format(wid=env.consumer.id)}/inbox", headers=auth).json() == []


class TestRouteGuards:
    def test_reject_wrong_source_is_404(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        r = client.post(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/reject", headers=con_auth)
        assert r.status_code == 404

    def test_reject_non_pending_is_400(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        src_auth = _login(client, env.source_owner.username)
        client.post(f"{LINKS.format(wid=env.source.id)}/{link['id']}/reject", headers=src_auth)
        r = client.post(f"{LINKS.format(wid=env.source.id)}/{link['id']}/reject", headers=src_auth)
        assert r.status_code == 400

    def test_revoke_on_unrelated_workspace_is_404(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        other = Workspace(name="无关工作区", created_by_id=env.consumer_owner.id)
        db.add(other)
        db.flush()
        db.add(WorkspaceMember(workspace_id=other.id, user_id=env.consumer_owner.id, role=WorkspaceRole.OWNER))
        db.commit()
        r = client.delete(f"{LINKS.format(wid=other.id)}/{link['id']}", headers=con_auth)
        assert r.status_code == 404

    def test_source_editor_cannot_revoke(self, client, db, env):
        editor = _make_user(db, "link_src_editor2")
        db.add(WorkspaceMember(workspace_id=env.source.id, user_id=editor.id, role=WorkspaceRole.EDITOR))
        db.commit()
        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        r = client.delete(f"{LINKS.format(wid=env.source.id)}/{link['id']}", headers=_login(client, editor.username))
        assert r.status_code == 403

    def test_revoke_without_created_members_is_noop(self, client, db, env):
        """受众全是源工作区原有成员时，created 为空 → 撤回不删任何人（L9）."""
        db.add(WorkspaceMember(workspace_id=env.source.id, user_id=env.consumer_owner.id, role=WorkspaceRole.VIEWER))
        db.add(WorkspaceMember(workspace_id=env.source.id, user_id=env.consumer_member.id, role=WorkspaceRole.VIEWER))
        db.commit()

        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        src_auth = _login(client, env.source_owner.username)
        client.post(f"{LINKS.format(wid=env.source.id)}/{link['id']}/approve", json={}, headers=src_auth)

        db.expire_all()
        stored = db.get(WorkspaceLink, link["id"])
        assert stored.created_member_ids == []

        assert client.delete(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}", headers=con_auth).status_code == 204
        db.expire_all()
        members = {
            row[0]
            for row in db.query(WorkspaceMember.user_id).filter(WorkspaceMember.workspace_id == env.source.id).all()
        }
        assert {env.consumer_owner.id, env.consumer_member.id} <= members


class TestInboxGuards:
    def test_inbox_requires_owner_of_source(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        assert client.get(f"{LINKS.format(wid=env.source.id)}/inbox", headers=con_auth).status_code == 403

    def test_list_requires_membership(self, client, db, env):
        outsider = _make_user(db, "link_outsider")
        r = client.get(LINKS.format(wid=env.consumer.id), headers=_login(client, outsider.username))
        assert r.status_code == 404


class TestExpiryHelpers:
    def test_expired_link_is_not_readable(self, db, env):
        from cndb.plugins.workspaces.services.links import is_expired, link_is_readable

        link = WorkspaceLink(
            workspace_id=env.consumer.id,
            source_workspace_id=env.source.id,
            target_type="table",
            target_table_id=env.table.id,
            alias="过期链",
            status=WorkspaceLinkStatus.ACTIVE,
            ttl_days=1,
            granted_member_ids=[],
            created_member_ids=[],
            expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1),
        )
        db.add(link)
        db.commit()
        assert is_expired(link) is True
        assert link_is_readable(link) is False

    def test_active_link_without_expiry_is_readable(self, db, env):
        from cndb.plugins.workspaces.services.links import link_is_readable

        link = WorkspaceLink(
            workspace_id=env.consumer.id,
            source_workspace_id=env.source.id,
            target_type="table",
            target_table_id=env.table.id,
            alias="无到期链",
            status=WorkspaceLinkStatus.ACTIVE,
            ttl_days=30,
            granted_member_ids=[],
            created_member_ids=[],
        )
        db.add(link)
        db.commit()
        assert link_is_readable(link) is True


class TestViewTargetAndLimits:
    def test_link_to_view(self, client, db, env):
        view = DataView(
            table_id=env.table.id,
            name="本月",
            view_type="grid",
            filters=[],
            sortings=[],
            scope_key=0,
        )
        db.add(view)
        db.commit()
        db.refresh(view)

        auth = _login(client, env.consumer_owner.username)
        body = _apply(client, env, auth, target_view_id=view.id, alias="本月明细")
        assert body["target_type"] == "view"
        assert body["target_view_id"] == view.id

    def test_view_must_belong_to_table(self, client, db, env):
        other = DataTable(
            workspace_id=env.source.id,
            owner_id=env.source_owner.id,
            name="另一张表",
            description="",
            db_table_name="t_link_other_view",
        )
        db.add(other)
        db.flush()
        view = DataView(table_id=other.id, name="另一视图", view_type="grid", filters=[], sortings=[], scope_key=0)
        db.add(view)
        db.commit()
        db.refresh(view)
        r = client.post(
            LINKS.format(wid=env.consumer.id),
            json={
                "source_workspace_id": env.source.id,
                "target_table_id": env.table.id,
                "target_view_id": view.id,
            },
            headers=_login(client, env.consumer_owner.username),
        )
        assert r.status_code == 400

    def test_alias_auto_suffix_on_duplicate_name(self, client, db, env):
        auth = _login(client, env.consumer_owner.username)
        first = _apply(client, env, auth)
        second = _apply(client, env, auth)
        assert first["alias"] == "销售明细"
        assert second["alias"] == "销售明细-2"

    def test_audience_over_limit_rejected_on_approve(self, client, db, env):
        from cndb.plugins.workspaces.models import LINK_MAX_GRANTEES

        for index in range(LINK_MAX_GRANTEES + 1):
            u = _make_user(db, f"link_bulk_{index}")
            db.add(WorkspaceMember(workspace_id=env.consumer.id, user_id=u.id, role=WorkspaceRole.VIEWER))
        db.commit()

        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        r = client.post(
            f"{LINKS.format(wid=env.source.id)}/{link['id']}/approve",
            json={},
            headers=_login(client, env.source_owner.username),
        )
        assert r.status_code == 400
        assert "团队授权" in r.json()["detail"]

    def test_approve_rejects_out_of_range_ttl_from_row(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        stored = db.get(WorkspaceLink, link["id"])
        stored.ttl_days = 999  # 模拟历史脏数据
        db.commit()
        r = client.post(
            f"{LINKS.format(wid=env.source.id)}/{link['id']}/approve",
            json={},
            headers=_login(client, env.source_owner.username),
        )
        assert r.status_code == 400

    def test_approve_on_wrong_source_workspace_is_404(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        # 源 owner 拿「消费方工作区」路径去批准 → 404
        r = client.post(
            f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/approve",
            json={},
            headers=con_auth,
        )
        assert r.status_code == 404

    def test_revoke_keeps_promoted_member(self, client, db, env):
        con_auth = _login(client, env.consumer_owner.username)
        link = _apply(client, env, con_auth)
        src_auth = _login(client, env.source_owner.username)
        client.post(f"{LINKS.format(wid=env.source.id)}/{link['id']}/approve", json={}, headers=src_auth)

        # 批准后被提升为 editor → 撤回不应降级 / 删除
        row = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == env.source.id, WorkspaceMember.user_id == env.consumer_owner.id)
            .first()
        )
        assert row is not None
        row.role = WorkspaceRole.EDITOR
        db.commit()

        assert client.delete(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}", headers=con_auth).status_code == 204
        db.expire_all()
        kept = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == env.source.id, WorkspaceMember.user_id == env.consumer_owner.id)
            .first()
        )
        assert kept is not None
        assert kept.role is WorkspaceRole.EDITOR


class TestBatchMembers:
    """ADR 0154 D12：批量加成员（A 期链接批准所用）."""

    def test_batch_adds_skips_and_reports_errors(self, client, db, env):
        auth = _login(client, env.consumer_owner.username)
        newbie = _make_user(db, "link_batch_newbie")
        r = client.post(
            f"{WS}/{env.consumer.id}/members/batch",
            json={
                "items": [
                    {"username": newbie.username, "role": "viewer"},
                    {"username": env.consumer_member.username},  # 已是成员 → skipped
                    {"username": "no_such_user"},  # 不存在 → errors
                    {"username": "link_src_owner", "role": "owner"},  # 禁止 owner
                ]
            },
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["added"] == [newbie.username]
        assert env.consumer_member.username in body["skipped"]
        assert {e["username"] for e in body["errors"]} == {"no_such_user", "link_src_owner"}

    def test_batch_dedupes_and_skips_blank(self, client, db, env):
        auth = _login(client, env.consumer_owner.username)
        newbie = _make_user(db, "link_dedupe_newbie")
        r = client.post(
            f"{WS}/{env.consumer.id}/members/batch",
            json={
                "items": [
                    {"username": newbie.username, "role": "viewer"},
                    {"username": newbie.username, "role": "viewer"},  # 重复 → skipped
                    {"username": "   "},  # 空白 → 忽略
                ]
            },
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["added"] == [newbie.username]
        assert newbie.username in body["skipped"]

    def test_batch_requires_manage_members(self, client, db, env):
        r = client.post(
            f"{WS}/{env.consumer.id}/members/batch",
            json={"items": [{"username": "x", "role": "viewer"}]},
            headers=_login(client, env.consumer_member.username),
        )
        assert r.status_code == 403

    def test_batch_caps_at_200(self, client, db, env):
        auth = _login(client, env.consumer_owner.username)
        items = [{"username": f"bulk_{i}", "role": "viewer"} for i in range(201)]
        r = client.post(f"{WS}/{env.consumer.id}/members/batch", json={"items": items}, headers=auth)
        assert r.status_code == 400
