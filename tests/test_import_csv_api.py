"""CSV 导入 + 关系图 API 路由测试."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.models.base import Base
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def api_session(tmp_path):
    settings.AUTH_ENABLED = True
    db_path = tmp_path / "test_api.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session, engine
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def api_client(api_session):
    session, _engine = api_session
    from cndb.app import app

    def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def workspace_with_auth(api_session, api_client):
    session, _engine = api_session

    u = User(username="api_user", nickname="API User")
    u.set_password("passw0rd")
    session.add(u)
    session.flush()

    ws = Workspace(name="APIWS", created_by_id=u.id)
    session.add(ws)
    session.flush()
    session.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
    session.commit()

    # Login
    r = api_client.post(
        "/api/v1/accounts/auth/login",
        json={"login": "api_user", "password": "passw0rd"},
    )
    token = r.json()["access_token"]
    return ws.id, {"Authorization": f"Bearer {token}"}


# ── POST /import-csv/analyze ──────────────────────────


class TestImportCsvAnalyzeApi:
    def test_analyze_ok(self, api_client, workspace_with_auth):
        ws_id, auth = workspace_with_auth
        csv_text = "name,age,email\nAlice,30,a@b.com\n"
        r = api_client.post(
            f"/api/v1/workspaces/{ws_id}/import-csv/analyze",
            json={"csv_text": csv_text},
            headers=auth,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total_rows"] == 1
        assert len(data["columns"]) == 3
        types = {c["name"]: c["field_type"] for c in data["columns"]}
        assert types["name"] == "text"
        assert types["age"] == "number"
        assert types["email"] == "email"

    def test_analyze_empty_csv(self, api_client, workspace_with_auth):
        ws_id, auth = workspace_with_auth
        r = api_client.post(
            f"/api/v1/workspaces/{ws_id}/import-csv/analyze",
            json={"csv_text": ""},
            headers=auth,
        )
        assert r.status_code == 400

    def test_analyze_unauthorized(self, api_client, workspace_with_auth):
        ws_id, _auth = workspace_with_auth
        r = api_client.post(
            f"/api/v1/workspaces/{ws_id}/import-csv/analyze",
            json={"csv_text": "a\n1\n"},
        )
        assert r.status_code in (401, 403)


# ── POST /import-csv (create table + import) ──────────


class TestImportCsvCreateTableApi:
    def test_create_ok(self, api_client, workspace_with_auth):
        ws_id, auth = workspace_with_auth
        csv_text = "name,age\nAlice,30\nBob,25\n"
        r = api_client.post(
            f"/api/v1/workspaces/{ws_id}/import-csv",
            json={"table_name": "测试表", "csv_text": csv_text},
            headers=auth,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["table_name"] == "测试表"
        assert data["imported_rows"] == 2
        assert data["field_count"] == 2
        assert data["table_id"] is not None

    def test_create_empty_csv(self, api_client, workspace_with_auth):
        ws_id, auth = workspace_with_auth
        r = api_client.post(
            f"/api/v1/workspaces/{ws_id}/import-csv",
            json={"table_name": "空表", "csv_text": ""},
            headers=auth,
        )
        assert r.status_code == 400


__all__ = []
