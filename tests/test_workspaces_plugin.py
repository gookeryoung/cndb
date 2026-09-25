"""workspaces 插件集成测试."""

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


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
        assert data["version"] == "4"
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

    def test_full_backup_roundtrip_restores_ws_tables_and_views(self, client, owner_user, db, db_engine):
        """全流程备份验证：工作区配置、字段定义、数据行、视图配置经导出→导入后逐项一致."""
        from cndb.plugins.tables.models import DataField, DataTable, DataView
        from cndb.plugins.tables.services.core import ddl
        from cndb.plugins.tables.services.core import records as rec

        token = _login_token(client, "owner", "passw0rd")
        headers = _headers(token)

        # ── 源工作区：非默认配置，确保恢复时逐项可比 ──
        r_ws = client.post(
            "/api/v1/workspaces",
            json={
                "name": "备份源工作区",
                "description": "全流程验证",
                "visibility": "private",
                "tags": ["备份", "回归"],
                "allow_edit": False,
            },
            headers=headers,
        )
        assert r_ws.status_code == 201, r_ws.text
        ws_id = r_ws.json()["id"]

        # ── 源表：字段定义覆盖 config/required/is_unique/default_value/hidden/order ──
        dt = DataTable(workspace_id=ws_id, owner_id=owner_user.id, name="员工表", description="人员信息")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        f_name = DataField(table_id=dt.id, name="姓名", field_type="text", order=0)
        f_name.ensure_db_name()
        f_age = DataField(table_id=dt.id, name="年龄", field_type="number", order=1, required=True)
        f_age.ensure_db_name()
        f_level = DataField(
            table_id=dt.id,
            name="职级",
            field_type="text",
            order=2,
            config={"options": ["P4", "P5"]},
            is_unique=True,
            default_value="P4",
        )
        f_level.ensure_db_name()
        f_note = DataField(table_id=dt.id, name="备注", field_type="text", order=3, hidden=True)
        f_note.ensure_db_name()
        db.add_all([f_name, f_age, f_level, f_note])
        db.commit()
        db.refresh(dt)
        ddl.create_table(db_engine, dt)
        rec.create_row(db_engine, dt, {"姓名": "张三", "年龄": 28, "职级": "P5", "备注": "无"})
        rec.create_row(db_engine, dt, {"姓名": "李四", "年龄": 35, "职级": "P4", "备注": "有"})

        # ── 源视图：默认视图 + 带筛选排序的自定义视图（含「全部」可跳过自动默认视图） ──
        db.add_all(
            [
                DataView(
                    table_id=dt.id,
                    name="全部",
                    view_type="grid",
                    is_default=True,
                    field_options={"姓名": {"width": 120}},
                    view_options={"row_height": "tall"},
                    field_order=["姓名", "年龄", "职级", "备注"],
                ),
                DataView(
                    table_id=dt.id,
                    name="重点行",
                    view_type="grid",
                    is_default=False,
                    filter_type="AND",
                    filters=[{"field_name": "年龄", "op": ">", "value": 30}],
                    sortings=[{"field_name": "年龄", "direction": "desc"}],
                ),
            ]
        )
        db.commit()

        # ── 导出备份 ──
        r_export = client.get(f"/api/v1/workspaces/{ws_id}/export", headers=headers)
        assert r_export.status_code == 200
        backup = r_export.json()
        assert backup["version"] == "4"

        # ── 从备份创建全新工作区（不传 name，应取备份中的 workspace.name） ──
        r_restore = client.post("/api/v1/workspaces/import", json={"json_data": backup}, headers=headers)
        assert r_restore.status_code == 201, r_restore.text
        body = r_restore.json()
        assert body["imported_tables"] == 1
        assert body["imported_rows"] == 2
        assert body["imported_views"] == 2

        # 工作区配置逐项还原
        restored_ws = body["workspace"]
        assert restored_ws["name"] == "备份源工作区"
        assert restored_ws["description"] == "全流程验证"
        assert restored_ws["visibility"] == "private"
        assert restored_ws["tags"] == ["备份", "回归"]
        assert restored_ws["allow_edit"] is False

        # ── 恢复后的工作区再导出，逐项对比 ──
        r_verify = client.get(f"/api/v1/workspaces/{restored_ws['id']}/export", headers=headers)
        assert r_verify.status_code == 200
        src_table, dst_table = backup["tables"][0], r_verify.json()["tables"][0]

        # 表定义
        assert dst_table["name"] == "员工表"
        assert dst_table["description"] == "人员信息"

        # 字段定义一致（含 config/required/is_unique/default_value/hidden/order；id 为新工作区重新生成，不比对）
        src_fields = {f["name"]: f for f in src_table["fields"]}
        dst_fields = {f["name"]: f for f in dst_table["fields"]}
        strip_id = lambda f: {k: v for k, v in f.items() if k != "id"}
        assert {n: strip_id(f) for n, f in dst_fields.items()} == {n: strip_id(f) for n, f in src_fields.items()}
        assert src_fields["职级"]["config"] == {"options": ["P4", "P5"]}
        assert src_fields["职级"]["is_unique"] is True
        assert src_fields["职级"]["default_value"] == "P4"
        assert src_fields["年龄"]["required"] is True
        assert src_fields["备注"]["hidden"] is True

        # 数据行一致（键为业务字段名，值逐行还原）
        dst_rows = {row["姓名"]: row for row in dst_table["rows"]}
        assert dst_rows == {
            "张三": {"姓名": "张三", "年龄": 28, "职级": "P5", "备注": "无"},
            "李四": {"姓名": "李四", "年龄": 35, "职级": "P4", "备注": "有"},
        }

        # 视图一致（按 name 对齐，顺序不敏感）
        src_views = {v["name"]: v for v in src_table["views"]}
        dst_views = {v["name"]: v for v in dst_table["views"]}
        assert dst_views == src_views
        assert src_views["全部"]["is_default"] is True
        assert src_views["全部"]["field_options"] == {"姓名": {"width": 120}}
        assert src_views["全部"]["view_options"] == {"row_height": "tall"}
        assert src_views["全部"]["field_order"] == ["姓名", "年龄", "职级", "备注"]
        assert src_views["重点行"]["is_default"] is False
        assert src_views["重点行"]["filters"] == [{"field_name": "年龄", "op": ">", "value": 30}]
        assert src_views["重点行"]["sortings"] == [{"field_name": "年龄", "direction": "desc"}]

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
        monkeypatch.setattr("cndb.plugins.tables.services.core.ddl.create_table", lambda engine, table: None)
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

    def test_import_workspace_all_view_name_collision(self, client, owner_user, db, monkeypatch):
        """真实导出文件必含默认视图「全部」：导入时不应与自动生成的默认视图重名冲突."""
        from cndb.plugins.tables.models import DataTable, DataView

        monkeypatch.setattr("cndb.plugins.tables.services.core.ddl.create_table", lambda engine, table: None)
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        payload = {
            "json_data": {
                "version": "2",
                "tables": [
                    {
                        "name": "房价表",
                        "fields": [
                            {"name": "标题", "field_type": "text", "order": 0},
                            {"name": "房价_万元", "field_type": "number", "order": 1},
                        ],
                        "views": [
                            {
                                "name": "全部",
                                "view_type": "grid",
                                "is_default": True,
                                "sortings": [{"field_name": "房价_万元", "direction": "desc"}],
                            },
                        ],
                        "rows": [],
                    }
                ],
            }
        }
        r = client.post(f"/api/v1/workspaces/{ws_id}/import", json=payload, headers=_headers(token))
        assert r.status_code == 200, r.json()
        data = r.json()
        assert data["imported_tables"] == 1
        assert data["imported_views"] == 1
        table = db.query(DataTable).filter(DataTable.name == "房价表").first()
        views = db.query(DataView).filter(DataView.table_id == table.id).all()
        assert len(views) == 1
        assert views[0].name == "全部"
        assert views[0].is_default is True
        assert views[0].sortings == [{"field_name": "房价_万元", "direction": "desc"}]

    def test_import_workspace_legacy_no_version(self, client, owner_user):
        """v1 旧文件可能缺 version 字段，导入应按 v1 接受."""
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import",
            json={"json_data": {"tables": []}},
            headers=_headers(token),
        )
        assert r.status_code == 200

    def test_import_workspace_unknown_version_400(self, client, owner_user):
        """未知版本的导出文件返回 400 并提示支持版本."""
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import",
            json={"json_data": {"version": "9", "tables": []}},
            headers=_headers(token),
        )
        assert r.status_code == 400
        assert "9" in r.json()["detail"]
        assert "1" in r.json()["detail"]

    def test_import_workspace_legacy_default_key(self, client, owner_user, db, monkeypatch):
        """v1 旧文件的视图 default 键导入后正确映射 is_default."""
        from cndb.plugins.tables.models import DataView

        monkeypatch.setattr("cndb.plugins.tables.services.core.ddl.create_table", lambda engine, table: None)
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        payload = {
            "json_data": {
                "version": "1",
                "tables": [
                    {
                        "name": "旧键视图表",
                        "fields": [{"name": "标题", "field_type": "text", "order": 0}],
                        "views": [{"name": "默认", "view_type": "grid", "default": True}],
                        "rows": [],
                    }
                ],
            }
        }
        r = client.post(f"/api/v1/workspaces/{ws_id}/import", json=payload, headers=_headers(token))
        assert r.status_code == 200
        view = db.query(DataView).filter(DataView.name == "默认").first()
        assert view is not None
        assert view.is_default is True

    def test_import_workspace_is_default_key(self, client, owner_user, db, monkeypatch):
        """v2 文件的视图 is_default 键导入后正确生效."""
        from cndb.plugins.tables.models import DataView

        monkeypatch.setattr("cndb.plugins.tables.services.core.ddl.create_table", lambda engine, table: None)
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        payload = {
            "json_data": {
                "version": "2",
                "tables": [
                    {
                        "name": "新键视图表",
                        "fields": [{"name": "标题", "field_type": "text", "order": 0}],
                        "views": [{"name": "默认", "view_type": "grid", "is_default": True}],
                        "rows": [],
                    }
                ],
            }
        }
        r = client.post(f"/api/v1/workspaces/{ws_id}/import", json=payload, headers=_headers(token))
        assert r.status_code == 200
        view = db.query(DataView).filter(DataView.name == "默认").first()
        assert view is not None
        assert view.is_default is True

    def test_import_multi_table_backup_with_same_name_skip(self, client, owner_user, db, db_engine):
        """多表备份导入：同名表跳过，其余表连同字段/数据行/视图全量还原."""
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core import ddl
        from cndb.plugins.tables.services.core import records as rec

        token = _login_token(client, "owner", "passw0rd")
        headers = _headers(token)
        ws_id = self._create_ws(client, token)

        # 现存表「员工表」（与备份同名，应被跳过且数据不受影响）
        dt = DataTable(workspace_id=ws_id, owner_id=owner_user.id, name="员工表")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        f = DataField(table_id=dt.id, name="姓名", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(dt)
        ddl.create_table(db_engine, dt)
        rec.create_row(db_engine, dt, {"姓名": "原有行"})

        backup = {
            "version": "3",
            "tables": [
                {
                    "name": "员工表",  # 同名 → 跳过
                    "fields": [{"name": "姓名", "field_type": "text", "order": 0}],
                    "rows": [],
                    "views": [],
                },
                {
                    "name": "项目表",
                    "fields": [
                        {"name": "项目名", "field_type": "text", "order": 0},
                        {"name": "预算", "field_type": "number", "order": 1},
                    ],
                    "rows": [
                        {"项目名": "Alpha", "预算": 100},
                        {"项目名": "Beta", "预算": 200},
                    ],
                    "views": [{"name": "全部", "view_type": "grid", "is_default": True}],
                },
            ],
        }
        r = client.post(f"/api/v1/workspaces/{ws_id}/import", json={"json_data": backup}, headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["imported_tables"] == 1
        assert data["imported_rows"] == 2
        assert data["imported_views"] == 1

        # 再导出验证：员工表原数据未被破坏，项目表全量还原
        r_verify = client.get(f"/api/v1/workspaces/{ws_id}/export", headers=headers)
        assert r_verify.status_code == 200
        tables = {t["name"]: t for t in r_verify.json()["tables"]}
        assert set(tables) == {"员工表", "项目表"}
        assert tables["员工表"]["rows"] == [{"姓名": "原有行"}]
        assert tables["项目表"]["rows"] == [
            {"项目名": "Alpha", "预算": 100},
            {"项目名": "Beta", "预算": 200},
        ]
        assert {v["name"] for v in tables["项目表"]["views"]} == {"全部"}

    def test_import_backup_without_all_view_auto_creates_default(self, client, owner_user, db, monkeypatch):
        """备份视图不含「全部」时，导入自动补建默认视图「全部」，且不打乱原视图的默认标志."""
        from cndb.plugins.tables.models import DataView

        monkeypatch.setattr("cndb.plugins.tables.services.core.ddl.create_table", lambda engine, table: None)
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        payload = {
            "json_data": {
                "version": "3",
                "tables": [
                    {
                        "name": "无默认视图表",
                        "fields": [{"name": "标题", "field_type": "text", "order": 0}],
                        "rows": [],
                        "views": [{"name": "重点", "view_type": "kanban", "is_default": False}],
                    }
                ],
            }
        }
        r = client.post(f"/api/v1/workspaces/{ws_id}/import", json=payload, headers=_headers(token))
        assert r.status_code == 200, r.text
        assert r.json()["imported_views"] == 1

        focus = db.query(DataView).filter(DataView.name == "重点").first()
        assert focus is not None
        views = db.query(DataView).filter(DataView.table_id == focus.table_id).all()
        by_name = {v.name: v for v in views}
        assert set(by_name) == {"重点", "全部"}  # 自动补建默认视图
        assert by_name["全部"].is_default is True
        assert by_name["全部"].view_type == "grid"
        assert by_name["重点"].is_default is False
        assert by_name["重点"].view_type == "kanban"

    def test_full_backup_roundtrip_multi_table_with_link_field(self, client, owner_user, db, db_engine):
        """多表真实备份还原：含 link 字段（无主表物理列）的表不应拖垮数据行导入."""
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core import ddl
        from cndb.plugins.tables.services.core import records as rec

        token = _login_token(client, "owner", "passw0rd")
        headers = _headers(token)
        ws_id = self._create_ws(client, token)

        # 表A：常规字段
        dt_a = DataTable(workspace_id=ws_id, owner_id=owner_user.id, name="普通表")
        dt_a.ensure_db_name()
        db.add(dt_a)
        db.flush()
        fa = DataField(table_id=dt_a.id, name="名称", field_type="text", order=0)
        fa.ensure_db_name()
        db.add(fa)
        db.commit()
        db.refresh(dt_a)
        ddl.create_table(db_engine, dt_a)
        rec.create_row(db_engine, dt_a, {"名称": "甲"})

        # 表B：含 link 字段（主表无对应物理列，值存关联表）
        dt_b = DataTable(workspace_id=ws_id, owner_id=owner_user.id, name="关联表")
        dt_b.ensure_db_name()
        db.add(dt_b)
        db.flush()
        fb1 = DataField(table_id=dt_b.id, name="标题", field_type="text", order=0)
        fb1.ensure_db_name()
        fb2 = DataField(table_id=dt_b.id, name="关联项", field_type="link", order=1)
        fb2.ensure_db_name()
        db.add_all([fb1, fb2])
        db.commit()
        db.refresh(dt_b)
        ddl.create_table(db_engine, dt_b)
        rec.create_row(db_engine, dt_b, {"标题": "任务一"})
        rec.create_row(db_engine, dt_b, {"标题": "任务二"})

        r_export = client.get(f"/api/v1/workspaces/{ws_id}/export", headers=headers)
        assert r_export.status_code == 200
        backup = r_export.json()

        r_restore = client.post("/api/v1/workspaces/import", json={"json_data": backup}, headers=headers)
        assert r_restore.status_code == 201, r_restore.text
        body = r_restore.json()
        assert body["imported_tables"] == 2
        assert body["imported_rows"] == 3
        assert body["errors"] == []

        r_verify = client.get(f"/api/v1/workspaces/{body['workspace']['id']}/export", headers=headers)
        assert r_verify.status_code == 200
        tables = {t["name"]: t for t in r_verify.json()["tables"]}
        assert tables["普通表"]["rows"] == [{"名称": "甲"}]
        assert tables["关联表"]["rows"] == [{"标题": "任务一"}, {"标题": "任务二"}]

    def test_import_legacy_backup_reports_unmatched_rows(self, client, owner_user, db, monkeypatch):
        """旧版备份行键为随机物理列名且无法映射 → 不静默丢数据，errors 明确上报."""
        monkeypatch.setattr("cndb.plugins.tables.services.core.ddl.create_table", lambda engine, table: None)
        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        payload = {
            "json_data": {
                "version": "2",
                "tables": [
                    {
                        "name": "旧表",
                        "fields": [{"name": "姓名", "field_type": "text", "order": 0}],
                        "rows": [{"field_abc123def456": "张三"}],  # 旧版导出的物理列名键
                        "views": [],
                    }
                ],
            }
        }
        r = client.post(f"/api/v1/workspaces/{ws_id}/import", json=payload, headers=_headers(token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["imported_rows"] == 0
        assert len(data["errors"]) == 1
        assert "旧表" in data["errors"][0]
        assert "1" in data["errors"][0]  # 提示丢失行数

    def test_import_reports_row_insert_failure(self, client, owner_user, db, db_engine):
        """行插入失败（required 字段 NOT NULL 违反）→ errors 上报表名，导入不中断，表结构/视图仍还原."""
        from cndb.plugins.tables.models import DataView

        token = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token)
        payload = {
            "json_data": {
                "version": "3",
                "tables": [
                    {
                        "name": "冲突表",
                        "fields": [
                            {"name": "必填列", "field_type": "text", "order": 0, "required": True},
                        ],
                        "rows": [{"必填列": None}],  # NOT NULL 列插入 None
                        "views": [{"name": "全部", "view_type": "grid", "is_default": True}],
                    }
                ],
            }
        }
        r = client.post(f"/api/v1/workspaces/{ws_id}/import", json=payload, headers=_headers(token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["imported_rows"] == 0
        assert data["imported_tables"] == 1
        assert data["imported_views"] == 1
        assert len(data["errors"]) == 1
        assert "冲突表" in data["errors"][0]
        # 表结构与视图仍正常还原
        view = db.query(DataView).filter(DataView.name == "全部").first()
        assert view is not None


class TestWorkspaceOwnerTransfer:
    """工作区所有权转让接口 POST /{wid}/owner."""

    def _create_ws(self, client, owner_token: str) -> int:
        r = client.post("/api/v1/workspaces", json={"name": "WS"}, headers=_headers(owner_token))
        assert r.status_code == 201
        return r.json()["id"]

    def _member_user_id(self, client, ws_id: int, token: str, username: str) -> int:
        r = client.get(f"/api/v1/workspaces/{ws_id}/members", headers=_headers(token))
        return next(m["user"]["id"] for m in r.json() if m["user"]["username"] == username)

    def test_owner_can_transfer_to_member(self, client, owner_user, admin_user):
        """OWNER 可将所有权转让给工作区成员，自身降级为 ADMIN."""
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        # 把 admin 加为成员
        client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "admin", "role": "admin"},
            headers=_headers(token_o),
        )
        target_uid = self._member_user_id(client, ws_id, token_o, "admin")
        # 转让所有权
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/owner",
            json={"user_id": target_uid},
            headers=_headers(token_o),
        )
        assert r.status_code == 200
        assert r.json()["role"] == "owner"
        assert r.json()["user"]["username"] == "admin"
        # 验证原 owner 已降级为 admin
        members = client.get(f"/api/v1/workspaces/{ws_id}/members", headers=_headers(token_o)).json()
        roles = {m["user"]["username"]: m["role"] for m in members}
        assert roles["admin"] == "owner"
        assert roles["owner"] == "admin"

    def test_non_owner_cannot_transfer(self, client, owner_user, admin_user, member_user):
        """非 OWNER（如 admin/viewer）转让所有权返回 403."""
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "admin", "role": "admin"},
            headers=_headers(token_o),
        )
        client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"username": "member", "role": "viewer"},
            headers=_headers(token_o),
        )
        target_uid = self._member_user_id(client, ws_id, token_o, "member")
        # admin 尝试转让 → 403
        token_a = _login_token(client, "admin", "passw0rd")
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/owner",
            json={"user_id": target_uid},
            headers=_headers(token_a),
        )
        assert r.status_code == 403

    def test_transfer_to_non_member_returns_400(self, client, owner_user, admin_user, member_user):
        """转让目标不是工作区成员时返回 400."""
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        # member_user 没有被加入工作区
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/owner",
            json={"user_id": member_user.id},
            headers=_headers(token_o),
        )
        assert r.status_code == 400

    def test_transfer_to_self_is_idempotent(self, client, owner_user):
        """把所有权转让给自己（已是 OWNER）幂等返回."""
        token_o = _login_token(client, "owner", "passw0rd")
        ws_id = self._create_ws(client, token_o)
        self_uid = self._member_user_id(client, ws_id, token_o, "owner")
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/owner",
            json={"user_id": self_uid},
            headers=_headers(token_o),
        )
        assert r.status_code == 200
        assert r.json()["role"] == "owner"
