"""workspaces 插件集成测试."""

from __future__ import annotations

from pathlib import Path

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
def _db_engine(tmp_path: Path):
    settings.AUTH_ENABLED = True
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    # 先导入所有插件 models，确保 Base.metadata 包含全部表
    import cndb.plugins.accounts.models
    import cndb.plugins.workspaces.models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine


@pytest.fixture
def db(_db_engine):
    SessionLocal = sessionmaker(bind=_db_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    from cndb.app import app

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def owner_user(db):
    """创建一个 owner 用户."""
    u = User(username="owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def member_user(db):
    """创建一个普通成员用户."""
    u = User(username="member", nickname="Member")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def admin_user(db):
    """创建一个 admin 用户."""
    u = User(username="admin", nickname="Admin")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _login_token(client, username: str, password: str) -> str:
    """登录获取 JWT."""
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": password})
    assert r.status_code == 200
    return r.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── 模型测试 ──────────────────────────────────────────


class TestWorkspaceModel:
    def test_create_workspace_auto_owner(self, db, owner_user):
        ws = Workspace(name="我的工作区", description="desc", created_by_id=owner_user.id)
        db.add(ws)
        db.flush()
        member = WorkspaceMember(workspace_id=ws.id, user_id=owner_user.id, role=WorkspaceRole.OWNER)
        db.add(member)
        db.commit()
        db.refresh(ws)
        db.refresh(member)
        assert ws.id is not None
        assert ws.name == "我的工作区"
        assert member.role == WorkspaceRole.OWNER
        assert member.pinned is False

    def test_workspace_member_unique_constraint(self, db, owner_user):
        ws = Workspace(name="WS")
        db.add(ws)
        db.flush()
        m1 = WorkspaceMember(workspace_id=ws.id, user_id=owner_user.id, role=WorkspaceRole.OWNER)
        m2 = WorkspaceMember(workspace_id=ws.id, user_id=owner_user.id, role=WorkspaceRole.VIEWER)
        db.add_all([m1, m2])
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


# ── API 测试 ──────────────────────────────────────────


class TestWorkspaceAPI:
    def test_create_workspace_registers_creator_as_owner(self, client, owner_user):
        token = _login_token(client, "owner", "passw0rd")
        r = client.post(
            "/api/v1/workspaces",
            json={"name": "Test WS", "description": "desc"},
            headers=_headers(token),
        )
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "Test WS"
        assert data["created_by_id"] == owner_user.id

    def test_list_workspaces_only_memberships(self, client, owner_user, member_user, db):
        # owner 创建两个工作区
        token_o = _login_token(client, "owner", "passw0rd")
        r1 = client.post("/api/v1/workspaces", json={"name": "WS1"}, headers=_headers(token_o))
        r2 = client.post("/api/v1/workspaces", json={"name": "WS2"}, headers=_headers(token_o))
        assert r1.status_code == 201 and r2.status_code == 201
        # member 登录后列表应是空的
        token_m = _login_token(client, "member", "passw0rd")
        r3 = client.get("/api/v1/workspaces", headers=_headers(token_m))
        assert r3.status_code == 200
        assert len(r3.json()) == 0

    def test_get_workspace_not_member_404(self, client, owner_user, member_user):
        token_o = _login_token(client, "owner", "passw0rd")
        r = client.post("/api/v1/workspaces", json={"name": "WS1"}, headers=_headers(token_o))
        ws_id = r.json()["id"]
        token_m = _login_token(client, "member", "passw0rd")
        r2 = client.get(f"/api/v1/workspaces/{ws_id}", headers=_headers(token_m))
        assert r2.status_code == 404

    def test_update_workspace_requires_admin_or_above(self, client, owner_user, member_user):
        token_o = _login_token(client, "owner", "passw0rd")
        r = client.post("/api/v1/workspaces", json={"name": "WS1"}, headers=_headers(token_o))
        ws_id = r.json()["id"]
        # member 加进去（owner 先添加）
        token_o = _login_token(client, "owner", "passw0rd")
        r2 = client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "member", "role": "viewer"},
            headers=_headers(token_o),
        )
        assert r2.status_code == 201
        # member 尝试修改 → 403
        token_m = _login_token(client, "member", "passw0rd")
        r3 = client.patch(
            f"/api/v1/workspaces/{ws_id}",
            json={"name": "Hacked"},
            headers=_headers(token_m),
        )
        assert r3.status_code == 403
        # owner 修改 → 200
        r4 = client.patch(
            f"/api/v1/workspaces/{ws_id}",
            json={"name": "Renamed"},
            headers=_headers(token_o),
        )
        assert r4.status_code == 200
        assert r4.json()["name"] == "Renamed"

    def test_delete_workspace_only_owner(self, client, owner_user, admin_user):
        # owner 创建工作区
        token_o = _login_token(client, "owner", "passw0rd")
        r = client.post("/api/v1/workspaces", json={"name": "WS1"}, headers=_headers(token_o))
        ws_id = r.json()["id"]
        # 把 admin 加进去
        r2 = client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "admin", "role": "admin"},
            headers=_headers(token_o),
        )
        assert r2.status_code == 201
        # admin 尝试删除 → 403
        token_a = _login_token(client, "admin", "passw0rd")
        r3 = client.delete(f"/api/v1/workspaces/{ws_id}", headers=_headers(token_a))
        assert r3.status_code == 403
        # owner 删除 → 204
        r4 = client.delete(f"/api/v1/workspaces/{ws_id}", headers=_headers(token_o))
        assert r4.status_code == 204


class TestMemberAPI:
    def _create_ws(self, client, owner_token: str) -> int:
        r = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=_headers(owner_token))
        assert r.status_code == 201
        return r.json()["id"]

    def test_add_member_as_viewer_by_admin(self, client, owner_user, member_user, admin_user):
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        # 添加 admin
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "admin", "role": "admin"},
            headers=_headers(token_o),
        )
        assert r.status_code == 201
        # admin 添加 member 为 viewer
        token_a = _login_token(client, "admin", "passw0rd")
        r2 = client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "member", "role": "viewer"},
            headers=_headers(token_a),
        )
        assert r2.status_code == 201
        assert r2.json()["role"] == "viewer"

    def test_add_member_reject_owner_role(self, client, owner_user, member_user):
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "member", "role": "owner"},
            headers=_headers(token_o),
        )
        assert r.status_code in (400, 422)

    def test_add_member_requires_admin(self, client, owner_user, member_user):
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        # member 自己加进去（owner 先加为 viewer）
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "member", "role": "viewer"},
            headers=_headers(token_o),
        )
        assert r.status_code == 201
        # member 再加其他人 → 403
        token_m = _login_token(client, "member", "passw0rd")
        r2 = client.post(
            f"/api/v1/workspaces/{ws_id}/members/candidates",
            headers=_headers(token_m),
        )
        assert r2.status_code in (403, 405)

    def test_add_member_duplicate_400(self, client, owner_user, member_user):
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "member", "role": "viewer"},
            headers=_headers(token_o),
        )
        assert r.status_code == 201
        r2 = client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "member", "role": "viewer"},
            headers=_headers(token_o),
        )
        assert r2.status_code == 400

    def test_list_candidates_excludes_members(self, client, owner_user, member_user, admin_user):
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        # owner 自己已是成员，admin/member 不是
        r = client.get(
            f"/api/v1/workspaces/{ws_id}/members/candidates",
            headers=_headers(token_o),
        )
        assert r.status_code == 200
        candidates = [u["username"] for u in r.json()["results"]]
        assert "admin" in candidates
        assert "member" in candidates
        assert "owner" not in candidates
        # 添加 member 后，candidates 应不再包含 member
        client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "member", "role": "viewer"},
            headers=_headers(token_o),
        )
        r2 = client.get(
            f"/api/v1/workspaces/{ws_id}/members/candidates",
            headers=_headers(token_o),
        )
        candidates2 = [u["username"] for u in r2.json()["results"]]
        assert "member" not in candidates2

    def test_update_member_role_last_owner_protected(self, client, owner_user, admin_user):
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        owner_member = client.get(
            f"/api/v1/workspaces/{ws_id}/members",
            headers=_headers(token_o),
        ).json()[0]
        # owner 降级自己 → 400（最后一个 owner）
        r = client.patch(
            f"/api/v1/workspaces/{ws_id}/members/{owner_member['id']}",
            json={"role": "admin"},
            headers=_headers(token_o),
        )
        assert r.status_code in (400, 422)
        # 添加第二个 owner
        client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "admin", "role": "admin"},
            headers=_headers(token_o),
        )
        # 先把 admin 升到 owner
        admin_member = client.get(
            f"/api/v1/workspaces/{ws_id}/members",
            headers=_headers(token_o),
        ).json()[1]
        r2 = client.patch(
            f"/api/v1/workspaces/{ws_id}/members/{admin_member['id']}",
            json={"role": "owner"},
            headers=_headers(token_o),
        )
        assert r2.status_code == 200
        # 现在可以安全降级第一个 owner
        r3 = client.patch(
            f"/api/v1/workspaces/{ws_id}/members/{owner_member['id']}",
            json={"role": "admin"},
            headers=_headers(token_o),
        )
        assert r3.status_code == 200
        assert r3.json()["role"] == "admin"

    def test_remove_member_last_owner_protected(self, client, owner_user, admin_user):
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        owner_member = client.get(
            f"/api/v1/workspaces/{ws_id}/members",
            headers=_headers(token_o),
        ).json()[0]
        # 移除最后一个 owner → 400
        r = client.delete(
            f"/api/v1/workspaces/{ws_id}/members/{owner_member['id']}",
            headers=_headers(token_o),
        )
        assert r.status_code in (400, 422)

    def test_non_owner_cannot_modify_owner(self, client, owner_user, admin_user):
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        # admin 加进去
        client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "admin", "role": "admin"},
            headers=_headers(token_o),
        )
        owner_member = client.get(
            f"/api/v1/workspaces/{ws_id}/members",
            headers=_headers(token_o),
        ).json()[0]
        # admin 尝试降级 owner → 403
        token_a = _login_token(client, "admin", "passw0rd")
        r = client.patch(
            f"/api/v1/workspaces/{ws_id}/members/{owner_member['id']}",
            json={"role": "admin"},
            headers=_headers(token_a),
        )
        assert r.status_code == 403


class TestPinAPI:
    def test_toggle_pin(self, client, owner_user):
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        r = client.post(
            "/api/v1/workspaces/pin",
            json={"workspace_id": ws_id},
            headers=_headers(token_o),
        )
        assert r.status_code == 200
        assert r.json()["pinned"] is True
        # 再切一次
        r2 = client.post(
            "/api/v1/workspaces/pin",
            json={"workspace_id": ws_id},
            headers=_headers(token_o),
        )
        assert r2.json()["pinned"] is False

    def test_pin_missing_workspace_id(self, client, owner_user):
        token_o = _login_token(client, "owner", "passw0rd")
        r = client.post("/api/v1/workspaces/pin", json={}, headers=_headers(token_o))
        assert r.status_code in (400, 422)

    def test_pin_list_pinned_first(self, client, owner_user, member_user):
        token_o = _login_token(client, "owner", "passw0rd")
        # 创建两个工作区
        r1 = client.post("/api/v1/workspaces", json={"name": "WS1"}, headers=_headers(token_o))
        r2 = client.post("/api/v1/workspaces", json={"name": "WS2"}, headers=_headers(token_o))
        id1 = r1.json()["id"]
        id2 = r2.json()["id"]
        # pin 第二个
        client.post("/api/v1/workspaces/pin", json={"workspace_id": id2}, headers=_headers(token_o))
        # 列表应先出现 pinned 的
        r3 = client.get("/api/v1/workspaces", headers=_headers(token_o))
        items = r3.json()
        assert items[0]["id"] == id2
        assert items[0]["pinned"] is True
        assert items[1]["id"] == id1
        assert items[1]["pinned"] is False

    def _create_ws(self, client, owner_token: str) -> int:
        r = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=_headers(owner_token))
        assert r.status_code == 201
        return r.json()["id"]
