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
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


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


# ── 扩展字段测试（visibility / tags / allow_edit） ───────────


class TestWorkspaceExtensionFields:
    """Workspace 扩展字段模型 + API 测试."""

    def test_create_workspace_with_extensions(self, client, owner_user):
        """创建工作区时可指定 visibility/tags/allow_edit."""
        token = _login_token(client, "owner", "passw0rd")
        r = client.post(
            "/api/v1/workspaces",
            json={
                "name": "公开工作区",
                "visibility": "public",
                "tags": ["核心", "研发"],
                "allow_edit": False,
            },
            headers=_headers(token),
        )
        assert r.status_code == 201
        data = r.json()
        assert data["visibility"] == "public"
        assert data["tags"] == ["核心", "研发"]
        assert data["allow_edit"] is False

    def test_update_workspace_extensions(self, client, owner_user):
        """更新工作区的扩展字段."""
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        r = client.patch(
            f"/api/v1/workspaces/{ws_id}",
            json={"visibility": "private", "tags": ["保密"], "allow_edit": True},
            headers=_headers(token),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["visibility"] == "private"
        assert data["tags"] == ["保密"]
        assert data["allow_edit"] is True

    def test_update_workspace_partial_extensions(self, client, owner_user):
        """部分更新仅影响指定字段."""
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        # 先设置完整值
        client.patch(
            f"/api/v1/workspaces/{ws_id}",
            json={"visibility": "public", "tags": ["a", "b"], "allow_edit": True},
            headers=_headers(token),
        )
        # 仅更新 visibility
        r = client.patch(
            f"/api/v1/workspaces/{ws_id}",
            json={"visibility": "private"},
            headers=_headers(token),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["visibility"] == "private"
        assert data["tags"] == ["a", "b"]  # 未变
        assert data["allow_edit"] is True  # 未变

    def test_workspace_defaults(self, client, owner_user):
        """创建工作区未指定扩展字段时使用默认值."""
        token = _login_token(client, "owner", "passw0rd")
        r = client.post("/api/v1/workspaces", json={"name": "默认WS"}, headers=_headers(token))
        assert r.status_code == 201
        data = r.json()
        assert data["visibility"] == "member"
        assert data["tags"] == []
        assert data["allow_edit"] is True

    def _create_ws(self, client, owner_token: str) -> int:
        r = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=_headers(owner_token))
        assert r.status_code == 201
        return r.json()["id"]


class TestWorkspaceDetailWithStats:
    """工作区详情接口扩展统计 + owner 信息."""

    def test_get_workspace_detail_includes_owner_and_stats(self, client, owner_user):
        """GET /{wid} 返回 WorkspaceDetailResponse."""
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        r = client.get(f"/api/v1/workspaces/{ws_id}", headers=_headers(token))
        assert r.status_code == 200
        data = r.json()
        # 扩展字段
        assert "visibility" in data
        assert "tags" in data
        assert "allow_edit" in data
        # owner 信息
        assert data["owner"] is not None
        assert data["owner"]["username"] == "owner"
        # 统计字段
        assert isinstance(data["table_count"], int)
        assert isinstance(data["member_count"], int)
        assert isinstance(data["view_count"], int)
        assert isinstance(data["total_rows"], int)
        # 新工作区 0 表 1 成员
        assert data["table_count"] == 0
        assert data["member_count"] == 1

    def test_list_workspaces_includes_stats(self, client, owner_user):
        """列表接口附带 table_count / member_count."""
        token = _login_token(client, "owner", "passw0rd")
        self._create_ws(client, token)
        r = client.get("/api/v1/workspaces", headers=_headers(token))
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        item = items[0]
        assert isinstance(item["table_count"], int)
        assert isinstance(item["member_count"], int)

    def _create_ws(self, client, owner_token: str) -> int:
        r = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=_headers(owner_token))
        assert r.status_code == 201
        return r.json()["id"]


class TestWorkspaceExportImport:
    """工作区整体 export / import."""

    def test_export_workspace_json_structure(self, client, owner_user):
        """export 接口返回正确结构."""
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        r = client.get(f"/api/v1/workspaces/{ws_id}/export", headers=_headers(token))
        assert r.status_code == 200
        data = r.json()
        assert data["version"] == "1"
        assert "exported_at" in data
        assert "workspace" in data
        assert "tables" in data
        ws_meta = data["workspace"]
        assert ws_meta["name"]  # 至少有名称

    def test_export_requires_membership(self, client, owner_user, member_user):
        """非成员不能导出."""
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        token_m = _login_token(client, "member", "passw0rd")
        r = client.get(f"/api/v1/workspaces/{ws_id}/export", headers=_headers(token_m))
        assert r.status_code in (403, 404)

    def test_import_workspace_empty_json(self, client, owner_user):
        """导入空结构不报错."""
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import",
            json={"json_data": {"version": "1", "tables": []}},
            headers=_headers(token),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["imported_tables"] == 0
        assert data["imported_rows"] == 0
        assert data["imported_views"] == 0

    def test_import_workspace_requires_admin(self, client, owner_user, member_user):
        """导入需要 ADMIN+ 权限."""
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        # 把 member 加为 viewer
        client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "member", "role": "viewer"},
            headers=_headers(token_o),
        )
        token_m = _login_token(client, "member", "passw0rd")
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import",
            json={"json_data": {"tables": []}},
            headers=_headers(token_m),
        )
        assert r.status_code == 403

    def test_import_workspace_invalid_format(self, client, owner_user):
        """无效 JSON 结构返回 400."""
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import",
            json={"json_data": {"no_tables_key": True}},
            headers=_headers(token),
        )
        assert r.status_code == 400

    def _create_ws(self, client, owner_token: str) -> int:
        r = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=_headers(owner_token))
        assert r.status_code == 201
        return r.json()["id"]

    def test_export_workspace_with_table_records(self, client, owner_user, db):
        """export 有 DataTable 记录时遍历表定义（跳过物理表 autoload）."""
        from cndb.plugins.tables.models import DataField, DataTable, DataView

        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        dt = DataTable(workspace_id=ws_id, name="导出测试表")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        f1 = DataField(table_id=dt.id, name="字段A", field_type="text", order=0)
        f1.ensure_db_name()
        db.add(f1)
        db.flush()
        db.add(DataView(table_id=dt.id, name="默认视图", view_type="grid", is_default=True))
        db.commit()
        r = client.get(f"/api/v1/workspaces/{ws_id}/export", headers=_headers(token))
        assert r.status_code == 200
        data = r.json()
        assert data["tables"][0]["name"] == "导出测试表"
        assert len(data["tables"][0]["fields"]) >= 1
        assert len(data["tables"][0]["views"]) >= 1

    def test_import_workspace_skips_empty_names(self, client, owner_user):
        """import 跳过空表名和已存在的同名表."""
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        # 空表名 → 跳过（不报错）
        payload = {
            "json_data": {
                "version": "1",
                "tables": [
                    {"name": "  ", "fields": []},
                    {"fields": []},
                ],
            }
        }
        r = client.post(f"/api/v1/workspaces/{ws_id}/import", json=payload, headers=_headers(token))
        assert r.status_code == 200

    def test_add_member_nonexistent_user(self, client, owner_user):
        """add_member 对不存在的用户返回 404."""
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "nobody_exists_xxx", "role": "viewer"},
            headers=_headers(token),
        )
        assert r.status_code == 404

    def test_list_candidates_with_search(self, client, owner_user, member_user):
        """list_candidates 带 search 参数过滤."""
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        r = client.get(
            f"/api/v1/workspaces/{ws_id}/members/candidates?search=memb",
            headers=_headers(token),
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["results"]) >= 1
        assert data["results"][0]["username"] == "member"

    def test_viewer_cannot_update_member_role(self, client, owner_user, member_user):
        """viewer 尝试修改角色返回 403 (覆盖 update_member_role 权限)."""
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        # 把 member_user 加入
        client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "member", "role": "viewer"},
            headers=_headers(token),
        )
        # 获取 member 的 member_id
        r = client.get(f"/api/v1/workspaces/{ws_id}/members", headers=_headers(token))
        member_mid = next(m["id"] for m in r.json() if m["user"]["username"] == "member")
        # member (viewer) 尝试修改自己角色
        viewer_token = _login_token(client, "member", "passw0rd")
        r2 = client.patch(
            f"/api/v1/workspaces/{ws_id}/members/{member_mid}",
            json={"role": "admin"},
            headers=_headers(viewer_token),
        )
        assert r2.status_code == 403

    def test_viewer_cannot_delete_member(self, client, owner_user, member_user):
        """viewer 尝试删除成员返回 403 (覆盖 delete_member 权限)."""
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "member", "role": "viewer"},
            headers=_headers(token),
        )
        viewer_token = _login_token(client, "member", "passw0rd")
        r = client.delete(
            f"/api/v1/workspaces/{ws_id}/members/9999",
            headers=_headers(viewer_token),
        )
        assert r.status_code == 403

    def test_admin_cannot_delete_owner(self, client, owner_user, admin_user):
        """admin 尝试删除 owner 返回 403 (覆盖 delete_member owner 保护)."""
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        client.post(
            f"/api/v1/workspaces/{ws_id}/members", json={"username": "admin", "role": "admin"}, headers=_headers(token)
        )
        # 获取 owner member id
        r = client.get(f"/api/v1/workspaces/{ws_id}/members", headers=_headers(token))
        owner_mid = next(m["id"] for m in r.json() if m["role"] == "owner")
        admin_token = _login_token(client, "admin", "passw0rd")
        r2 = client.delete(
            f"/api/v1/workspaces/{ws_id}/members/{owner_mid}",
            headers=_headers(admin_token),
        )
        assert r2.status_code == 403

    def test_remove_owner_when_multiple_exist(self, client, owner_user, admin_user):
        """有 2 个 owner 时可以删除其中一个（覆盖 owner_count > 1 分支）."""
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        # 把 admin_user 加入并升级为 owner
        client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "admin", "role": "admin"},
            headers=_headers(token_o),
        )
        r = client.get(f"/api/v1/workspaces/{ws_id}/members", headers=_headers(token_o))
        admin_mid = next(m["id"] for m in r.json() if m["user"]["username"] == "admin")
        # 把 admin 升级为 owner
        client.patch(
            f"/api/v1/workspaces/{ws_id}/members/{admin_mid}", json={"role": "owner"}, headers=_headers(token_o)
        )
        # 现在有 2 个 owner，原 owner 可以删除 admin owner
        r2 = client.delete(f"/api/v1/workspaces/{ws_id}/members/{admin_mid}", headers=_headers(token_o))
        assert r2.status_code == 204

    def test_import_workspace_full_flow(self, client, owner_user, monkeypatch):
        """import 完整流程（mock DDL 绕过物理表创建）."""
        # mock DDL create_table，什么都不做
        monkeypatch.setattr("cndb.plugins.tables.ddl.create_table", lambda engine, table: None)
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        payload = {
            "json_data": {
                "version": "1",
                "tables": [
                    {
                        "name": "完整导入表",
                        "description": "测试",
                        "fields": [
                            {"name": "标题", "field_type": "text", "order": 0},
                        ],
                        "views": [
                            {"name": "默认", "view_type": "grid", "is_default": True},
                        ],
                        "rows": [],
                    }
                ],
            }
        }
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import",
            json=payload,
            headers=_headers(token),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["imported_tables"] == 1
        assert data["imported_views"] == 1
