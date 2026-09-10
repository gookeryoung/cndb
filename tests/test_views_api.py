"""DataView 视图端点测试."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.models.base import Base
from cndb.plugins.accounts.models import User
from cndb.plugins.tables import ddl
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole


@pytest.fixture
def db(tmp_path):
    settings.AUTH_ENABLED = True
    db_path = tmp_path / "views.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    import cndb.plugins.accounts.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    from cndb.app import app

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def owner(db):
    u = User(username="v_owner", nickname="Owner")
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

    w = Workspace(name="VWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws, tmp_path):
    db_path = tmp_path / "vws.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    dt = DataTable(workspace_id=ws.id, name="VTable")
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


class TestViewsAPI:
    def test_create_view(self, client, ws, table, auth_owner):
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "默认表格", "view_type": "grid", "is_default": True},
            headers=auth_owner,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "默认表格"
        assert data["view_type"] == "grid"
        assert data["is_default"] is True

    def test_list_views(self, client, ws, table, auth_owner):
        # 先创建两个
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "Grid1", "view_type": "grid"},
            headers=auth_owner,
        )
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "Kanban1", "view_type": "kanban"},
            headers=auth_owner,
        )
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_get_view_detail(self, client, ws, table, auth_owner):
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "DetailView", "view_type": "grid"},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["name"] == "DetailView"

    def test_update_view(self, client, ws, table, auth_owner):
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "OldName", "view_type": "grid"},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        r = client.patch(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}",
            json={"name": "NewName", "is_default": True},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["name"] == "NewName"
        assert r.json()["is_default"] is True

    def test_delete_view(self, client, ws, table, auth_owner):
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "ToDelete", "view_type": "grid"},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        r = client.delete(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}",
            headers=auth_owner,
        )
        assert r.status_code == 204

    def test_create_view_duplicate_name(self, client, ws, table, auth_owner):
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "Dup", "view_type": "grid"},
            headers=auth_owner,
        )
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "Dup", "view_type": "kanban"},
            headers=auth_owner,
        )
        assert r.status_code == 400

    def test_get_view_not_found(self, client, ws, table, auth_owner):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/99999",
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_update_view_not_found(self, client, ws, table, auth_owner):
        r = client.patch(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/99999",
            json={"name": "x"},
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_delete_view_not_found(self, client, ws, table, auth_owner):
        r = client.delete(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/99999",
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_create_view_set_default_replaces_others(self, client, ws, table, auth_owner):
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "V1", "is_default": True},
            headers=auth_owner,
        )
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "V2", "is_default": True},
            headers=auth_owner,
        )
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            headers=auth_owner,
        )
        views = r.json()
        defaults = [v for v in views if v["is_default"]]
        assert len(defaults) == 1
        assert defaults[0]["name"] == "V2"


__all__ = []
