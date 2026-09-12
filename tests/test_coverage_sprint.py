"""coverage 冲刺 —— 精准覆盖剩余分支缺口."""

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
def db_engine_cov(tmp_path):
    settings.AUTH_ENABLED = True
    db_path = tmp_path / "sprint.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    import cndb.plugins.accounts.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine


@pytest.fixture
def db_cov(db_engine_cov):
    SessionLocal = sessionmaker(bind=db_engine_cov, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client_cov(db_cov):
    from cndb.app import app

    def _override_get_db():
        try:
            yield db_cov
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def owner_cov(db_cov):
    u = User(username="sprint_owner", nickname="Owner")
    u.set_password("passw0rd")
    db_cov.add(u)
    db_cov.commit()
    db_cov.refresh(u)
    return u


@pytest.fixture
def editor_cov(db_cov):
    u = User(username="sprint_editor", nickname="Editor")
    u.set_password("passw0rd")
    db_cov.add(u)
    db_cov.commit()
    db_cov.refresh(u)
    return u


@pytest.fixture
def ws_cov(db_cov, owner_cov, editor_cov):
    from cndb.plugins.workspaces.models import WorkspaceMember

    ws = Workspace(name="SprintWS", created_by_id=owner_cov.id)
    db_cov.add(ws)
    db_cov.flush()
    db_cov.add(WorkspaceMember(workspace_id=ws.id, user_id=owner_cov.id, role=WorkspaceRole.OWNER))
    db_cov.add(WorkspaceMember(workspace_id=ws.id, user_id=editor_cov.id, role=WorkspaceRole.EDITOR))
    db_cov.commit()
    db_cov.refresh(ws)
    return ws


@pytest.fixture
def auth_owner_cov(client_cov, owner_cov):
    r = client_cov.post("/api/v1/accounts/auth/login", json={"login": owner_cov.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth_editor_cov(client_cov, editor_cov):
    r = client_cov.post("/api/v1/accounts/auth/login", json={"login": editor_cov.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def table_cov(db_cov, db_engine_cov, ws_cov):
    dt = DataTable(workspace_id=ws_cov.id, name="SprintTable")
    dt.ensure_db_name()
    db_cov.add(dt)
    db_cov.flush()
    df = DataField(table_id=dt.id, name="姓名", field_type="text", order=0)
    df.ensure_db_name()
    db_cov.add(df)
    db_cov.commit()
    db_cov.refresh(dt)
    ddl.create_table(db_engine_cov, dt)
    return dt, df


# ── deps.py 分支覆盖 ──────────────────────────────────


class TestDepsAuthBranches:
    def test_auth_disabled_returns_none(self, db_cov):
        from cndb.api.deps import get_current_user

        old = settings.AUTH_ENABLED
        settings.AUTH_ENABLED = False
        try:
            from unittest.mock import MagicMock

            req = MagicMock()
            req.headers = {}
            result = get_current_user(req, db_cov)
            assert result is None
        finally:
            settings.AUTH_ENABLED = old

    def test_bearer_missing_returns_none(self, db_cov):
        from unittest.mock import MagicMock

        from cndb.api.deps import get_current_user

        req = MagicMock()
        req.headers = {"Authorization": "Basic xxx"}
        result = get_current_user(req, db_cov)
        assert result is None

    def test_bearer_empty_token_returns_none(self, db_cov):
        from unittest.mock import MagicMock

        from cndb.api.deps import get_current_user

        req = MagicMock()
        req.headers = {"Authorization": "Bearer "}
        result = get_current_user(req, db_cov)
        assert result is None

    def test_get_optional_user_handles_401(self, db_cov):
        from unittest.mock import MagicMock

        from cndb.api.deps import get_optional_user

        req = MagicMock()
        req.headers = {"Authorization": "Bearer invalid_token_that_is_not_jwt"}
        result = get_optional_user(req, db_cov)
        assert result is None


# ── workspaces/routers 分支覆盖 ────────────────────────


class TestWorkspacesSprint:
    def test_search_members_by_keyword(self, client_cov, auth_owner_cov, ws_cov):
        r = client_cov.get(
            f"/api/v1/workspaces/{ws_cov.id}/members?search=editor",
            headers=auth_owner_cov,
        )
        assert r.status_code == 200

    def test_remove_member(self, client_cov, auth_owner_cov, ws_cov, editor_cov):
        r = client_cov.delete(
            f"/api/v1/workspaces/{ws_cov.id}/members/{editor_cov.id}",
            headers=auth_owner_cov,
        )
        assert r.status_code == 204

    def test_remove_nonexistent_member(self, client_cov, auth_owner_cov, ws_cov):
        r = client_cov.delete(
            f"/api/v1/workspaces/{ws_cov.id}/members/99999",
            headers=auth_owner_cov,
        )
        assert r.status_code == 404

    def test_editor_cannot_promote(self, client_cov, auth_editor_cov, ws_cov, owner_cov):
        # editor 不能修改工作区元数据
        r = client_cov.patch(
            f"/api/v1/workspaces/{ws_cov.id}",
            json={"name": "Hacked"},
            headers=auth_editor_cov,
        )
        assert r.status_code in (403, 404)

    def test_editor_cannot_invite(self, client_cov, auth_editor_cov, ws_cov):
        r = client_cov.post(
            f"/api/v1/workspaces/{ws_cov.id}/invite",
            json={"user_ids": [99999]},
            headers=auth_editor_cov,
        )
        assert r.status_code in (403, 404)


# ── router/fields.py & router/records.py 分支覆盖 ──────


class TestTablesSprint:
    def test_list_fields_with_trashed(self, client_cov, auth_owner_cov, ws_cov, table_cov):
        dt, _ = table_cov
        r = client_cov.get(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}/fields?include_trashed=true",
            headers=auth_owner_cov,
        )
        assert r.status_code == 200

    def test_delete_field_via_router(self, client_cov, auth_owner_cov, ws_cov, table_cov):
        dt, df = table_cov
        r = client_cov.delete(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}/fields/{df.id}",
            headers=auth_owner_cov,
        )
        assert r.status_code == 204

    def test_update_field_name(self, client_cov, auth_owner_cov, ws_cov, table_cov):
        dt, df = table_cov
        r = client_cov.patch(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}/fields/{df.id}",
            json={"name": "新名字"},
            headers=auth_owner_cov,
        )
        assert r.status_code == 200
        assert r.json()["name"] == "新名字"

    def test_update_field_not_found(self, client_cov, auth_owner_cov, ws_cov, table_cov):
        dt, _ = table_cov
        r = client_cov.patch(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}/fields/99999",
            json={"name": "x"},
            headers=auth_owner_cov,
        )
        assert r.status_code == 404

    def test_delete_field_not_found(self, client_cov, auth_owner_cov, ws_cov, table_cov):
        dt, _ = table_cov
        r = client_cov.delete(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}/fields/99999",
            headers=auth_owner_cov,
        )
        assert r.status_code == 404

    def test_create_record_invalid(self, client_cov, auth_owner_cov, ws_cov, table_cov):
        dt, _ = table_cov
        # 空 values 字典（不是必填的应该允许）
        r = client_cov.post(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}/records",
            json={"values": {}},
            headers=auth_owner_cov,
        )
        # 201 或 400 取决于字段配置，但不应该 500
        assert r.status_code in (201, 400)

    def test_list_records_invalid_filter_logic(self, client_cov, auth_owner_cov, ws_cov, table_cov):
        dt, _ = table_cov
        r = client_cov.post(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}/records/list",
            json={"filter_logic": "BROKEN_LOGIC", "filters": []},
            headers=auth_owner_cov,
        )
        assert r.status_code == 200  # 不会报错

    def test_table_delete_soft(self, client_cov, auth_owner_cov, ws_cov, table_cov):
        dt, _ = table_cov
        r = client_cov.delete(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}",
            headers=auth_owner_cov,
        )
        assert r.status_code == 204

    def test_list_tables_include_trashed(self, client_cov, auth_owner_cov, ws_cov, table_cov):
        r = client_cov.get(
            f"/api/v1/workspaces/{ws_cov.id}/tables?include_trashed=true",
            headers=auth_owner_cov,
        )
        assert r.status_code == 200


__all__ = []


# ── 额外 deps 分支 ────────────────────────────────────


class TestDepsMore:
    def test_jwt_missing_sub(self, db_cov):
        """JWT payload 没有 sub 字段时返回 None."""
        from jose import jwt as jose_jwt

        from cndb.api.deps import _authenticate_jwt
        from cndb.core.config import settings

        secret = settings.JWT_SECRET
        bad_token = jose_jwt.encode({"iat": 123}, secret, algorithm="HS256")
        result = _authenticate_jwt(bad_token, db_cov)
        assert result is None


class TestTablesRecordsMore:
    """router/records.py 剩余分支."""

    def test_delete_record_not_found_hard(self, client_cov, auth_owner_cov, ws_cov, table_cov):
        dt, _ = table_cov
        r = client_cov.delete(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}/records/99999?soft=false",
            headers=auth_owner_cov,
        )
        assert r.status_code == 404

    def test_update_record_not_found(self, client_cov, auth_owner_cov, ws_cov, table_cov):
        dt, _ = table_cov
        r = client_cov.patch(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}/records/99999",
            json={"values": {"姓名": "x"}},
            headers=auth_owner_cov,
        )
        assert r.status_code == 404

    def test_editor_cannot_delete_table(self, client_cov, auth_editor_cov, ws_cov, table_cov):
        dt, _ = table_cov
        r = client_cov.delete(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}",
            headers=auth_editor_cov,
        )
        assert r.status_code == 403


# ── router/records.py 异常分支 ─────────────────────────


class TestRecordsExceptionBranches:
    def test_create_record_value_error(self, client_cov, auth_owner_cov, ws_cov, db_engine_cov, db_cov):
        """触发 create_record 里的 ValueError 分支 —— 给必填字段缺失."""
        from cndb.plugins.tables import ddl
        from cndb.plugins.tables.models import DataField, DataTable

        # 建一个带 required 字段的表
        dt = DataTable(workspace_id=ws_cov.id, name="ReqTable")
        dt.ensure_db_name()
        db_cov.add(dt)
        db_cov.flush()
        df = DataField(table_id=dt.id, name="必填名", field_type="text", required=True, order=0)
        df.ensure_db_name()
        db_cov.add(df)
        db_cov.commit()
        db_cov.refresh(dt)
        ddl.create_table(db_engine_cov, dt)

        # 空 values 应该触发 ValueError（必填校验）
        r = client_cov.post(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}/records",
            json={"values": {}},
            headers=auth_owner_cov,
        )
        assert r.status_code == 400

    def test_number_field_min_max_validation(self, client_cov, auth_owner_cov, ws_cov, db_engine_cov, db_cov):
        """NumberFieldType 的 min/max 校验分支."""
        from cndb.plugins.tables import ddl
        from cndb.plugins.tables.models import DataField, DataTable

        dt = DataTable(workspace_id=ws_cov.id, name="NumberTable")
        dt.ensure_db_name()
        db_cov.add(dt)
        db_cov.flush()
        df = DataField(
            table_id=dt.id,
            name="分数",
            field_type="number",
            config={"min": 0, "max": 100},
            order=0,
        )
        df.ensure_db_name()
        db_cov.add(df)
        db_cov.commit()
        db_cov.refresh(dt)
        ddl.create_table(db_engine_cov, dt)

        # 超出 max
        r = client_cov.post(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}/records",
            json={"values": {"分数": 200}},
            headers=auth_owner_cov,
        )
        assert r.status_code == 400

    def test_float_field_validation(self, client_cov, auth_owner_cov, ws_cov, db_engine_cov, db_cov):
        """FloatFieldType 的 validate 分支."""
        from cndb.plugins.tables import ddl
        from cndb.plugins.tables.models import DataField, DataTable

        dt = DataTable(workspace_id=ws_cov.id, name="FloatTable")
        dt.ensure_db_name()
        db_cov.add(dt)
        db_cov.flush()
        df = DataField(
            table_id=dt.id,
            name="小数",
            field_type="float",
            config={"min": 0.0, "max": 1.0, "decimals": 2},
            order=0,
        )
        df.ensure_db_name()
        db_cov.add(df)
        db_cov.commit()
        db_cov.refresh(dt)
        ddl.create_table(db_engine_cov, dt)

        r = client_cov.post(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}/records",
            json={"values": {"小数": 1.5}},
            headers=auth_owner_cov,
        )
        assert r.status_code == 400

    def test_select_field_validation(self, client_cov, auth_owner_cov, ws_cov, db_engine_cov, db_cov):
        """SelectFieldType 的 validate 分支."""
        from cndb.plugins.tables import ddl
        from cndb.plugins.tables.models import DataField, DataTable

        dt = DataTable(workspace_id=ws_cov.id, name="SelTable")
        dt.ensure_db_name()
        db_cov.add(dt)
        db_cov.flush()
        df = DataField(
            table_id=dt.id,
            name="类型",
            field_type="select",
            config={"options": ["A", "B"]},
            order=0,
        )
        df.ensure_db_name()
        db_cov.add(df)
        db_cov.commit()
        db_cov.refresh(dt)
        ddl.create_table(db_engine_cov, dt)

        r = client_cov.post(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}/records",
            json={"values": {"类型": "C"}},
            headers=auth_owner_cov,
        )
        assert r.status_code == 400

    def test_multiselect_field_validation(self, client_cov, auth_owner_cov, ws_cov, db_engine_cov, db_cov):
        """MultiSelectFieldType 的 validate 分支."""
        from cndb.plugins.tables import ddl
        from cndb.plugins.tables.models import DataField, DataTable

        dt = DataTable(workspace_id=ws_cov.id, name="MSelTable")
        dt.ensure_db_name()
        db_cov.add(dt)
        db_cov.flush()
        df = DataField(
            table_id=dt.id,
            name="多选",
            field_type="multiselect",
            config={"options": ["X", "Y"]},
            order=0,
        )
        df.ensure_db_name()
        db_cov.add(df)
        db_cov.commit()
        db_cov.refresh(dt)
        ddl.create_table(db_engine_cov, dt)

        r = client_cov.post(
            f"/api/v1/workspaces/{ws_cov.id}/tables/{dt.id}/records",
            json={"values": {"多选": ["X", "Z"]}},
            headers=auth_owner_cov,
        )
        assert r.status_code == 400
