"""补充 API 边界测试 —— 错误路径、权限校验等."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.models.base import Base
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def api_session(tmp_path):
    settings.AUTH_ENABLED = True
    db_path = tmp_path / "test_edge.db"
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
def workspaces(api_session, api_client):
    session, _engine = api_session
    from cndb.plugins.accounts.models import User

    owner = User(username="edge_owner", nickname="Owner")
    owner.set_password("passw0rd")
    session.add(owner)
    session.flush()
    ws1 = Workspace(name="WS1", created_by_id=owner.id)
    session.add(ws1)
    session.flush()
    session.add(WorkspaceMember(workspace_id=ws1.id, user_id=owner.id, role=WorkspaceRole.OWNER))

    viewer = User(username="edge_viewer", nickname="Viewer")
    viewer.set_password("passw0rd")
    session.add(viewer)
    session.flush()
    ws2 = Workspace(name="WS2", created_by_id=viewer.id)
    session.add(ws2)
    session.flush()
    session.add(WorkspaceMember(workspace_id=ws2.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))

    session.commit()

    r1 = api_client.post("/api/v1/accounts/auth/login", json={"login": "edge_owner", "password": "passw0rd"})
    r2 = api_client.post("/api/v1/accounts/auth/login", json={"login": "edge_viewer", "password": "passw0rd"})
    return {
        "owner": (ws1.id, {"Authorization": f"Bearer {r1.json()['access_token']}"}),
        "viewer": (ws2.id, {"Authorization": f"Bearer {r2.json()['access_token']}"}),
    }


class TestImportCsvEdgeCases:
    def test_create_csv_nonexistent_workspace(self, api_client, workspaces):
        _ws_id, auth = workspaces["owner"]
        r = api_client.post(
            "/api/v1/workspaces/99999/import-csv",
            json={"table_name": "X", "csv_text": "a\n1\n"},
            headers=auth,
        )
        assert r.status_code == 404

    def test_analyze_nonexistent_workspace(self, api_client, workspaces):
        _ws_id, auth = workspaces["owner"]
        r = api_client.post(
            "/api/v1/workspaces/99999/import-csv/analyze",
            json={"csv_text": "a\n1\n"},
            headers=auth,
        )
        assert r.status_code == 404

    def test_create_csv_all_empty_columns(self, api_client, workspaces):
        ws_id, auth = workspaces["owner"]
        r = api_client.post(
            f"/api/v1/workspaces/{ws_id}/import-csv",
            json={"table_name": "X", "csv_text": " , \n , \n"},
            headers=auth,
        )
        assert r.status_code == 400

    def test_analyze_all_empty_columns(self, api_client, workspaces):
        ws_id, auth = workspaces["owner"]
        r = api_client.post(
            f"/api/v1/workspaces/{ws_id}/import-csv/analyze",
            json={"csv_text": " , \n"},
            headers=auth,
        )
        assert r.status_code == 400

    def test_graph_nonexistent_workspace(self, api_client, workspaces):
        _ws_id, auth = workspaces["owner"]
        r = api_client.get("/api/v1/workspaces/99999/graph", headers=auth)
        assert r.status_code == 404

    def test_deps_nonexistent_workspace(self, api_client, workspaces):
        _ws_id, auth = workspaces["owner"]
        r = api_client.get("/api/v1/workspaces/99999/dependencies", headers=auth)
        assert r.status_code == 404

    def test_graph_unauthorized(self, api_client):
        r = api_client.get("/api/v1/workspaces/1/graph")
        assert r.status_code in (401, 403, 404)

    def test_deps_unauthorized(self, api_client):
        r = api_client.get("/api/v1/workspaces/1/dependencies")
        assert r.status_code in (401, 403, 404)

    def test_create_csv_permission_denied(self, api_client, workspaces):
        """Viewer 权限不能建表（需要 EDITOR）."""
        ws2_id, viewer_auth = workspaces["viewer"]
        r = api_client.post(
            f"/api/v1/workspaces/{ws2_id}/import-csv",
            json={"table_name": "X", "csv_text": "a\n1\n"},
            headers=viewer_auth,
        )
        assert r.status_code == 403


__all__ = []
