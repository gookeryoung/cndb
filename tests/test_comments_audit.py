"""评论 + 审计 API 测试."""

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
from cndb.plugins.tables.models import DataField, DataTable, RowComment
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole


@pytest.fixture
def db(tmp_path):
    settings.AUTH_ENABLED = True
    db_path = tmp_path / "comments.db"
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
    u = User(username="c_owner", nickname="Owner")
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

    w = Workspace(name="CWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="CTable")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    df = DataField(table_id=dt.id, name="姓名", field_type="text", order=0)
    df.ensure_db_name()
    db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    # 造一行数据
    from cndb.plugins.tables import records as rec

    rec.create_row(engine, dt, {"姓名": "张三"})
    return dt


@pytest.fixture
def record_id(db, table):
    from cndb.plugins.tables import records as rec

    rows, _ = rec.list_rows(db.get_bind(), table)
    return rows[0]["id"]


class TestCommentsAPI:
    def test_create_comment(self, client, ws, table, record_id, auth_owner):
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/{record_id}/comments",
            json={"content": "不错哦"},
            headers=auth_owner,
        )
        assert r.status_code == 201
        assert r.json()["content"] == "不错哦"

    def test_list_comments(self, client, ws, table, record_id, auth_owner):
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/{record_id}/comments",
            json={"content": "A"},
            headers=auth_owner,
        )
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/{record_id}/comments",
            json={"content": "B"},
            headers=auth_owner,
        )
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/{record_id}/comments",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_list_comments_empty(self, client, ws, table, record_id, auth_owner):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/{record_id}/comments",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json() == []

    def test_create_comment_row_not_found(self, client, ws, table, auth_owner):
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/9999/comments",
            json={"content": "x"},
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_update_comment(self, client, ws, table, record_id, auth_owner, db):
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/{record_id}/comments",
            json={"content": "old"},
            headers=auth_owner,
        )
        cid = db.query(RowComment).filter(RowComment.table_id == table.id).first().id
        r = client.patch(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/comments/{cid}",
            json={"content": "new"},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["content"] == "new"

    def test_update_comment_not_found(self, client, ws, table, auth_owner):
        r = client.patch(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/comments/9999",
            json={"content": "x"},
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_delete_comment(self, client, ws, table, record_id, auth_owner, db):
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/{record_id}/comments",
            json={"content": "bye"},
            headers=auth_owner,
        )
        cid = db.query(RowComment).filter(RowComment.table_id == table.id).first().id
        r = client.delete(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/comments/{cid}",
            headers=auth_owner,
        )
        assert r.status_code == 204

    def test_delete_comment_not_found(self, client, ws, table, auth_owner):
        r = client.delete(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/comments/9999",
            headers=auth_owner,
        )
        assert r.status_code == 404


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
