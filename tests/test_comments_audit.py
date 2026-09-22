"""审计 API 测试."""

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole


@pytest.fixture
def owner(db):
    u = User(username="a_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth_owner(client, owner):
    r = client.post("/api/v1/accounts/auth/login", json={"login": owner.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def ws(db, owner):
    from cndb.plugins.workspaces.models import WorkspaceMember

    w = Workspace(name="AWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="ATable")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    df = DataField(table_id=dt.id, name="姓名", field_type="text", order=0)
    df.ensure_db_name()
    db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    return dt


class TestAuditAPI:
    def test_list_audit_empty(self, client, ws, table, auth_owner):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/audit",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json() == []

    def test_list_audit_with_filter(self, client, ws, table, auth_owner):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/audit?action=delete",
            headers=auth_owner,
        )
        assert r.status_code == 200

    def test_list_audit_by_row_id(self, client, ws, table, auth_owner):
        """覆盖 audit row_id 查询参数 — 按行过滤审计日志."""
        # 先建一条记录产生 audit log
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields",
            headers=auth_owner,
            json={"name": "name", "field_type": "single_text"},
        )
        cr = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records",
            headers=auth_owner,
            json={"values": {"name": "hello"}},
        )
        row_id = cr.json()["id"]
        # 按 row_id 过滤
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/audit?row_id={row_id}",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert len(r.json()) >= 1


__all__ = []
