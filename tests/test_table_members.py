"""表成员与所有权管理路由测试 — 覆盖率补全."""

from __future__ import annotations

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable, TableMember
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def owner_user(db):
    u = User(username="mb_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def admin_user(db):
    u = User(username="mb_admin", nickname="Admin")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def editor_user(db):
    u = User(username="mb_editor", nickname="Editor")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def viewer_user(db):
    u = User(username="mb_viewer", nickname="Viewer")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def outsider_user(db):
    """不在工作区中的用户."""
    u = User(username="mb_outsider", nickname="Outsider")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def mb_ws(db, owner_user, admin_user, editor_user, viewer_user):
    ws = Workspace(name="MemberWS", created_by_id=owner_user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner_user.id, role=WorkspaceRole.OWNER))
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=admin_user.id, role=WorkspaceRole.ADMIN))
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=editor_user.id, role=WorkspaceRole.EDITOR))
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=viewer_user.id, role=WorkspaceRole.VIEWER))
    db.commit()
    db.refresh(ws)
    return ws


@pytest.fixture
def mb_table(db, mb_ws, owner_user, db_engine):
    dt = DataTable(workspace_id=mb_ws.id, name="MT", owner_id=owner_user.id)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    df = DataField(table_id=dt.id, name="name", field_type="text", order=0)
    df.ensure_db_name()
    db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(db_engine, dt)
    return dt


@pytest.fixture
def auth_for(client):
    def _do(username: str) -> dict:
        r = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": username, "password": "passw0rd"},
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _do


# ── GET /members ──────────────────────────────────────


class TestListMembers:
    def test_list_empty(self, client, mb_ws, mb_table, auth_for):
        r = client.get(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members",
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 200
        assert r.json() == []

    def test_list_after_add(self, client, db, mb_ws, mb_table, editor_user, auth_for):
        tm = TableMember(table_id=mb_table.id, user_id=editor_user.id, role="write")
        db.add(tm)
        db.commit()
        r = client.get(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members",
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["user_id"] == editor_user.id
        assert data[0]["username"] == editor_user.username
        assert data[0]["role"] == "write"

    def test_list_unauthorized(self, client, mb_ws, mb_table):
        r = client.get(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members",
        )
        assert r.status_code in (401, 403)

    def test_list_by_viewer(self, client, mb_ws, mb_table, auth_for):
        r = client.get(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members",
            headers=auth_for("mb_viewer"),
        )
        assert r.status_code == 200

    def test_list_not_workspace_member(self, client, mb_ws, mb_table, outsider_user, auth_for):
        r = client.get(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members",
            headers=auth_for("mb_outsider"),
        )
        assert r.status_code == 403

    def test_list_table_not_found(self, client, mb_ws, auth_for):
        r = client.get(
            f"/api/v1/workspaces/{mb_ws.id}/tables/99999/members",
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 404


# ── POST /members ─────────────────────────────────────


class TestAddMember:
    def test_add_editor_ok(self, client, db, mb_ws, mb_table, editor_user, auth_for):
        r = client.post(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members",
            json={"user_id": editor_user.id, "role": "write"},
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 201
        data = r.json()
        assert data["user_id"] == editor_user.id
        assert data["role"] == "write"
        # 审计日志写入
        from cndb.plugins.tables.models import AuditLog

        logs = db.query(AuditLog).filter(AuditLog.table_id == mb_table.id).all()
        assert len(logs) >= 1
        assert logs[-1].action == "add_member"

    def test_add_admin_can_add(self, client, db, mb_ws, mb_table, editor_user, auth_for):
        r = client.post(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members",
            json={"user_id": editor_user.id, "role": "read"},
            headers=auth_for("mb_admin"),
        )
        assert r.status_code == 201

    def test_add_invalid_role(self, client, mb_ws, mb_table, editor_user, auth_for):
        r = client.post(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members",
            json={"user_id": editor_user.id, "role": "super"},
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 400

    def test_add_target_not_workspace_member(self, client, mb_ws, mb_table, outsider_user, auth_for):
        r = client.post(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members",
            json={"user_id": outsider_user.id, "role": "read"},
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 400

    def test_add_self_already_owner(self, client, mb_ws, mb_table, owner_user, auth_for):
        r = client.post(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members",
            json={"user_id": owner_user.id, "role": "read"},
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 400

    def test_add_already_member(self, client, db, mb_ws, mb_table, editor_user, auth_for):
        tm = TableMember(table_id=mb_table.id, user_id=editor_user.id, role="read")
        db.add(tm)
        db.commit()
        r = client.post(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members",
            json={"user_id": editor_user.id, "role": "write"},
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 409

    def test_add_not_authorized_editor(self, client, mb_ws, mb_table, viewer_user, auth_for):
        r = client.post(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members",
            json={"user_id": viewer_user.id, "role": "read"},
            headers=auth_for("mb_editor"),
        )
        assert r.status_code == 403

    def test_add_not_authorized_viewer(self, client, mb_ws, mb_table, editor_user, auth_for):
        r = client.post(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members",
            json={"user_id": editor_user.id, "role": "read"},
            headers=auth_for("mb_viewer"),
        )
        assert r.status_code == 403


# ── PATCH /members/{user_id} ──────────────────────────


class TestUpdateMember:
    def test_update_role_ok(self, client, db, mb_ws, mb_table, editor_user, auth_for):
        tm = TableMember(table_id=mb_table.id, user_id=editor_user.id, role="read")
        db.add(tm)
        db.commit()
        r = client.patch(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members/{editor_user.id}",
            json={"role": "write"},
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 200
        assert r.json()["role"] == "write"

    def test_update_invalid_role(self, client, db, mb_ws, mb_table, editor_user, auth_for):
        tm = TableMember(table_id=mb_table.id, user_id=editor_user.id, role="read")
        db.add(tm)
        db.commit()
        r = client.patch(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members/{editor_user.id}",
            json={"role": "super"},
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 400

    def test_update_member_not_found(self, client, mb_ws, mb_table, editor_user, auth_for):
        r = client.patch(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members/{editor_user.id}",
            json={"role": "write"},
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 404

    def test_update_not_admin(self, client, db, mb_ws, mb_table, editor_user, viewer_user, auth_for):
        tm = TableMember(table_id=mb_table.id, user_id=editor_user.id, role="read")
        db.add(tm)
        db.commit()
        r = client.patch(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members/{editor_user.id}",
            json={"role": "write"},
            headers=auth_for("mb_viewer"),
        )
        assert r.status_code == 403


# ── DELETE /members/{user_id} ─────────────────────────


class TestRemoveMember:
    def test_remove_ok(self, client, db, mb_ws, mb_table, editor_user, auth_for):
        tm = TableMember(table_id=mb_table.id, user_id=editor_user.id, role="write")
        db.add(tm)
        db.commit()
        r = client.delete(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members/{editor_user.id}",
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 204
        # 确认已删除
        remaining = (
            db.query(TableMember)
            .filter(TableMember.table_id == mb_table.id, TableMember.user_id == editor_user.id)
            .first()
        )
        assert remaining is None

    def test_remove_not_found(self, client, mb_ws, mb_table, editor_user, auth_for):
        r = client.delete(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members/{editor_user.id}",
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 404

    def test_remove_not_admin(self, client, db, mb_ws, mb_table, editor_user, viewer_user, auth_for):
        tm = TableMember(table_id=mb_table.id, user_id=editor_user.id, role="write")
        db.add(tm)
        db.commit()
        r = client.delete(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/members/{editor_user.id}",
            headers=auth_for("mb_viewer"),
        )
        assert r.status_code == 403


# ── POST /owner ───────────────────────────────────────


class TestTransferOwner:
    def test_transfer_ok(self, client, db, mb_ws, mb_table, admin_user, auth_for):
        r = client.post(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/owner",
            json={"user_id": admin_user.id},
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["user_id"] == admin_user.id
        assert data["role"] == "owner"
        db.refresh(mb_table)
        assert mb_table.owner_id == admin_user.id

    def test_transfer_admin_can_do_it(self, client, db, mb_ws, mb_table, admin_user, editor_user, auth_for):
        # 先把所有权给 admin，再由 admin 转给 editor
        mb_table.owner_id = admin_user.id
        db.commit()
        r = client.post(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/owner",
            json={"user_id": editor_user.id},
            headers=auth_for("mb_admin"),
        )
        assert r.status_code == 200

    def test_transfer_self_idempotent(self, client, db, mb_ws, mb_table, owner_user, auth_for):
        r = client.post(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/owner",
            json={"user_id": owner_user.id},
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 200
        assert r.json()["user_id"] == owner_user.id

    def test_transfer_non_admin_denied(self, client, mb_ws, mb_table, editor_user, auth_for):
        r = client.post(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/owner",
            json={"user_id": editor_user.id},
            headers=auth_for("mb_editor"),
        )
        assert r.status_code == 403

    def test_transfer_target_not_workspace_member(self, client, mb_ws, mb_table, outsider_user, auth_for):
        r = client.post(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/owner",
            json={"user_id": outsider_user.id},
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 400

    def test_transfer_remove_existing_member_record(self, client, db, mb_ws, mb_table, admin_user, auth_for):
        # admin 已在 TableMember 里时，转让后应移除成员记录
        tm = TableMember(table_id=mb_table.id, user_id=admin_user.id, role="write")
        db.add(tm)
        db.commit()
        r = client.post(
            f"/api/v1/workspaces/{mb_ws.id}/tables/{mb_table.id}/owner",
            json={"user_id": admin_user.id},
            headers=auth_for("mb_owner"),
        )
        assert r.status_code == 200
        # TableMember 应该被删除
        assert (
            db.query(TableMember)
            .filter(TableMember.table_id == mb_table.id, TableMember.user_id == admin_user.id)
            .first()
            is None
        )


__all__ = []
