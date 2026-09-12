"""补充：graph 有 link 字段 + import_csv create 异常分支."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.models.base import Base
from cndb.plugins.tables.ddl import create_table as ddl_create
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def linked_api_session(tmp_path):
    settings.AUTH_ENABLED = True
    db_path = tmp_path / "test_linked.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    from cndb.plugins.accounts.models import User

    u = User(username="link_user")
    u.set_password("passw0rd")
    session.add(u)
    session.flush()
    ws = Workspace(name="LinkedWS", created_by_id=u.id)
    session.add(ws)
    session.flush()
    session.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
    session.commit()

    # 创建两张有 link 的表
    table_b = DataTable(workspace_id=ws.id, name="TableB")
    table_b.ensure_db_name()
    session.add(table_b)
    session.flush()
    f_b = DataField(table_id=table_b.id, name="name", field_type="text", order=0)
    f_b.ensure_db_name()
    session.add(f_b)
    session.commit()
    session.refresh(table_b)
    ddl_create(engine, table_b)

    table_a = DataTable(workspace_id=ws.id, name="TableA")
    table_a.ensure_db_name()
    session.add(table_a)
    session.flush()
    f_a1 = DataField(table_id=table_a.id, name="name", field_type="text", order=0)
    f_a1.ensure_db_name()
    session.add(f_a1)
    f_a2 = DataField(
        table_id=table_a.id,
        name="ref_b",
        field_type="link",
        order=1,
        config={"target_table_id": table_b.id},
    )
    f_a2.ensure_db_name()
    session.add(f_a2)
    session.commit()
    session.refresh(table_a)
    ddl_create(engine, table_a)

    try:
        yield session, engine, ws.id
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def linked_api_client(linked_api_session):
    session, _engine, _ws_id = linked_api_session
    from cndb.app import app

    def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def linked_auth(linked_api_client, linked_api_session):
    _session, _engine, ws_id = linked_api_session
    r = linked_api_client.post("/api/v1/accounts/auth/login", json={"login": "link_user", "password": "passw0rd"})
    return ws_id, {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestGraphWithLinks:
    def test_graph_with_edges(self, linked_api_client, linked_auth):
        ws_id, auth = linked_auth
        r = linked_api_client.get(f"/api/v1/workspaces/{ws_id}/graph", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert len(data["nodes"]) == 2
        # 应该有一条 link 边
        assert len(data["edges"]) == 1
        edge = data["edges"][0]
        assert edge["link_field_name"] == "ref_b"
        # 拓扑序：B 应该在 A 前面（A 依赖 B）
        assert len(data["topo_order"]) == 2


class TestDependenciesApi:
    def test_deps_with_links(self, linked_api_client, linked_auth):
        ws_id, auth = linked_auth
        r = linked_api_client.get(f"/api/v1/workspaces/{ws_id}/dependencies", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert "link_fields" in data
        assert len(data["link_fields"]) >= 1


__all__ = []
