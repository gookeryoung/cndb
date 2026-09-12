"""TablePermission 端点测试."""

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
    db_path = tmp_path / "perm.db"
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
        engine.dispose()


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
    u = User(username="p_owner", nickname="Owner")
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

    w = Workspace(name="PWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws, tmp_path):
    db_path = tmp_path / "ptable.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    dt = DataTable(workspace_id=ws.id, name="PTable")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    df = DataField(table_id=dt.id, name="姓名", field_type="text", order=0)
    df.ensure_db_name()
    db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    engine.dispose()
    return dt


class TestPermissionsAPI:
    def test_get_permission_auto_create(self, client, ws, table, auth_owner):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/permissions",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["table_id"] == table.id

    def test_upsert_permission(self, client, ws, table, auth_owner):
        r = client.put(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/permissions",
            json={"read_role": "viewer", "edit_records_role": "editor"},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["read_role"] == "viewer"
        assert r.json()["edit_records_role"] == "editor"

    def test_patch_permission(self, client, ws, table, auth_owner):
        client.put(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/permissions",
            json={"read_role": "viewer"},
            headers=auth_owner,
        )
        r = client.patch(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/permissions",
            json={"hidden_fields": {"姓名": True}},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["hidden_fields"] == {"姓名": True}


__all__ = []
