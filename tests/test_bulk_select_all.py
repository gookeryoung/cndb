"""跨页全选批量删除（需求 0149 C8）.

覆盖：select_all + filters 在服务端展开（行级权限同源）、上限拒绝、
未给 row_ids 且未开 select_all → 400、跨页删除只删命中行。
"""

from __future__ import annotations

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable, TablePermission
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def owner(db):
    u = User(username="selectall_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth(client, owner):
    r = client.post("/api/v1/accounts/auth/login", json={"login": "selectall_owner", "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="SelectAllWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="跨页表")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    f = DataField(table_id=dt.id, name="分组", field_type="text", order=0)
    f.ensure_db_name()
    db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    for group in ("A", "A", "B", "C"):
        rec.create_row(engine, dt, {"分组": group}, db=db)
    return dt


def _url(ws, table) -> str:
    return f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/bulk-delete"


def _groups(db, table) -> list[str]:
    """当前**未被软删**的行（绕过行级权限，直接读物理表；权限口径由接口测试单独覆盖）."""
    from sqlalchemy import select

    sa = ddl.get_reflected_table(db.get_bind(), table.db_table_name)
    stmt = select(sa.c.id, sa.c._trashed)
    with db.get_bind().connect() as conn:
        raw = conn.execute(stmt).all()
    alive = {int(r[0]) for r in raw if not bool(r[1])}
    # 读一遍分组值（同样绕过权限）
    field = next(f for f in table.fields if f.name == "分组")
    with db.get_bind().connect() as conn:
        values = {
            int(r[0]): str(r[1])
            for r in conn.execute(select(sa.c.id, sa.c[field.db_column_name])).all()
            if int(r[0]) in alive
        }
    return sorted(values.values())


class TestSelectAllDelete:
    def test_select_all_with_filters_deletes_only_matching(self, client, db, ws, table, auth):
        r = client.post(
            _url(ws, table),
            json={
                "select_all": True,
                "filters": [{"field_name": "分组", "op": "eq", "value": "A"}],
                "filter_logic": "AND",
            },
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert r.json()["deleted"] == 2
        assert _groups(db, table) == ["B", "C"]

    def test_select_all_without_filters_deletes_all(self, client, db, ws, table, auth):
        r = client.post(_url(ws, table), json={"select_all": True}, headers=auth)
        assert r.status_code == 200
        assert r.json()["deleted"] == 4
        assert _groups(db, table) == []

    def test_missing_ids_and_no_select_all_400(self, client, ws, table, auth):
        r = client.post(_url(ws, table), json={"row_ids": []}, headers=auth)
        assert r.status_code == 400

    def test_select_all_respects_row_scope(self, client, db, ws, table, auth):
        db.add(
            TablePermission(
                table_id=table.id,
                row_filters=[{"field_name": "分组", "op": "eq", "value": "A"}],
                row_filter_type="AND",
            )
        )
        db.commit()
        viewer = User(username="selectall_viewer", nickname="V")
        viewer.set_password("passw0rd")
        db.add(viewer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=viewer.id, role=WorkspaceRole.EDITOR))
        db.commit()
        login = client.post("/api/v1/accounts/auth/login", json={"login": "selectall_viewer", "password": "passw0rd"})
        viewer_auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

        r = client.post(_url(ws, table), json={"select_all": True}, headers=viewer_auth)
        assert r.status_code == 200, r.text
        # 行级权限限制下只能删到 A 组两行
        assert r.json()["deleted"] == 2
        assert _groups(db, table) == ["B", "C"]

    def test_select_all_over_cap_rejected(self, client, ws, table, auth, monkeypatch):
        from cndb.plugins.tables.routers import bulk_crud

        monkeypatch.setattr(bulk_crud, "SELECT_ALL_MAX_ROWS", 2)
        r = client.post(_url(ws, table), json={"select_all": True}, headers=auth)
        assert r.status_code == 400
        assert "上限" in r.text

    def test_row_ids_still_work(
        self,
        client,
        db,
        ws,
        table,
        auth,
    ):
        rows, _ = rec.list_rows(db.get_bind(), table, limit=3, db=db)
        ids = [int(row["id"]) for row in rows[:1]]
        r = client.post(_url(ws, table), json={"row_ids": ids}, headers=auth)
        assert r.status_code == 200
        assert r.json()["deleted"] == 1


class TestSelectAllUpdate:
    def _update(self, client, ws, table, auth, body):
        return client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/bulk-update",
            json=body,
            headers=auth,
        )

    def test_select_all_with_filters_updates_only_matching(self, client, db, ws, table, auth):
        r = self._update(
            client,
            ws,
            table,
            auth,
            {
                "select_all": True,
                "filters": [{"field_name": "分组", "op": "eq", "value": "A"}],
                "values": {"分组": "A2"},
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["updated"] == 2
        assert _groups(db, table) == ["A2", "A2", "B", "C"]

    def test_select_all_without_filters_updates_all(self, client, db, ws, table, auth):
        r = self._update(client, ws, table, auth, {"select_all": True, "values": {"分组": "X"}})
        assert r.status_code == 200
        assert _groups(db, table) == ["X", "X", "X", "X"]

    def test_missing_ids_and_values_400(self, client, ws, table, auth):
        assert self._update(client, ws, table, auth, {"row_ids": [], "values": {"分组": "X"}}).status_code == 400
        assert self._update(client, ws, table, auth, {"row_ids": [1], "values": {}}).status_code == 400

    def test_select_all_over_cap_rejected(self, client, ws, table, auth, monkeypatch):
        from cndb.plugins.tables.routers import bulk_crud

        monkeypatch.setattr(bulk_crud, "SELECT_ALL_MAX_ROWS", 2)
        r = self._update(client, ws, table, auth, {"select_all": True, "values": {"分组": "X"}})
        assert r.status_code == 400
        assert "上限" in r.text

    def test_row_ids_still_work(self, client, db, ws, table, auth):
        rows, _ = rec.list_rows(db.get_bind(), table, limit=1, db=db)
        rid = int(rows[0]["id"])
        r = self._update(client, ws, table, auth, {"row_ids": [rid], "values": {"分组": "Z"}})
        assert r.status_code == 200
        assert _groups(db, table).count("Z") == 1
