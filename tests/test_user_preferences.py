"""用户偏好 API 测试 —— 每张表激活视图的 per-user 持久化."""

from __future__ import annotations

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, DataView
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

# ── helpers ──


def _make_table_with_view(db, owner: User) -> tuple[Workspace, DataTable, DataView]:
    """创建 workspace + table + 默认 view，返回三元组."""
    ws = Workspace(name="PWS", created_by_id=owner.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER))

    dt = DataTable(workspace_id=ws.id, name="偏好测试表")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()

    dv = DataView(table_id=dt.id, owner_id=owner.id, name="默认视图", view_type="grid")
    db.add(dv)
    db.commit()
    db.refresh(ws)
    db.refresh(dt)
    db.refresh(dv)
    return ws, dt, dv


# ── User 模型默认值 ──


class TestUserPreferencesDefault:
    def test_new_user_has_default_preferences(self, db):
        """新注册用户 preferences 字段应含空 active_views dict."""
        user = User(username="pref_user", email="p@u.com", nickname="P")
        user.set_password("passw0rd")
        db.add(user)
        db.commit()
        db.refresh(user)
        assert user.preferences == {"active_views": {}}


# ── Preferences API ──


class TestPreferencesAPI:
    def test_get_preferences_empty(self, client, auth_headers):
        """首次查询应返回空映射."""
        r = client.get("/api/v1/accounts/preferences", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"active_views": {}}

    def test_get_preferences_no_auth(self, client):
        """未认证应返回 401."""
        r = client.get("/api/v1/accounts/preferences")
        assert r.status_code == 401

    def test_get_table_active_view_404(self, client, auth_headers):
        """查询不存在的表偏好应返回 404."""
        r = client.get("/api/v1/accounts/preferences/tables/99999/active-view", headers=auth_headers)
        assert r.status_code == 404

    def test_set_active_view_success(self, client, db, auth_headers):
        """设置激活视图成功."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        _ws, dt, dv = _make_table_with_view(db, user)

        r = client.put(
            f"/api/v1/accounts/preferences/tables/{dt.id}/active-view",
            json={"active_view_id": dv.id},
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["table_id"] == dt.id
        assert body["active_view_id"] == dv.id

    def test_set_active_view_invalid_view(self, client, db, auth_headers):
        """设置不存在的视图应返回 400."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        _ws, dt, _dv = _make_table_with_view(db, user)

        r = client.put(
            f"/api/v1/accounts/preferences/tables/{dt.id}/active-view",
            json={"active_view_id": 99999},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_set_active_view_wrong_table(self, client, db, auth_headers):
        """视图不属于该表时应返回 400."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        _ws1, dt1, _dv1 = _make_table_with_view(db, user)
        _ws2, _dt2, dv2 = _make_table_with_view(db, user)

        # dv2 属于 dt2，尝试设置到 dt1
        r = client.put(
            f"/api/v1/accounts/preferences/tables/{dt1.id}/active-view",
            json={"active_view_id": dv2.id},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_set_active_view_null_clears(self, client, db, auth_headers):
        """设置 null 应清除偏好."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        _ws, dt, dv = _make_table_with_view(db, user)

        # 先设置
        client.put(
            f"/api/v1/accounts/preferences/tables/{dt.id}/active-view",
            json={"active_view_id": dv.id},
            headers=auth_headers,
        )
        # 再清除
        r = client.put(
            f"/api/v1/accounts/preferences/tables/{dt.id}/active-view",
            json={"active_view_id": None},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["active_view_id"] is None

        # 查询应返回 null
        r = client.get(
            f"/api/v1/accounts/preferences/tables/{dt.id}/active-view",
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["active_view_id"] is None

    def test_get_table_active_view_after_set(self, client, db, auth_headers):
        """设置后查询应返回该视图."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        _ws, dt, dv = _make_table_with_view(db, user)

        client.put(
            f"/api/v1/accounts/preferences/tables/{dt.id}/active-view",
            json={"active_view_id": dv.id},
            headers=auth_headers,
        )
        r = client.get(
            f"/api/v1/accounts/preferences/tables/{dt.id}/active-view",
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["active_view_id"] == dv.id

    def test_get_preferences_after_set(self, client, db, auth_headers):
        """设置后 get_preferences 应包含映射."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        _ws, dt, dv = _make_table_with_view(db, user)

        client.put(
            f"/api/v1/accounts/preferences/tables/{dt.id}/active-view",
            json={"active_view_id": dv.id},
            headers=auth_headers,
        )
        r = client.get("/api/v1/accounts/preferences", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["active_views"][str(dt.id)] == dv.id

    def test_deleted_view_cleans_preference(self, client, db, auth_headers):
        """偏好的视图被删后，再次查询应自动清理并返回 null."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        _ws, dt, dv = _make_table_with_view(db, user)

        # 设置偏好
        client.put(
            f"/api/v1/accounts/preferences/tables/{dt.id}/active-view",
            json={"active_view_id": dv.id},
            headers=auth_headers,
        )
        # 删除视图
        db.delete(dv)
        db.commit()

        # 查询应返回 null（自动清理孤立引用）
        r = client.get(
            f"/api/v1/accounts/preferences/tables/{dt.id}/active-view",
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["active_view_id"] is None

        # 且 preferences dict 中也应被清理
        r = client.get("/api/v1/accounts/preferences", headers=auth_headers)
        assert str(dt.id) not in (r.json()["active_views"] or {})

    def test_set_active_view_404(self, client, auth_headers):
        """设置不存在表的偏好应返回 404."""
        r = client.put(
            "/api/v1/accounts/preferences/tables/99999/active-view",
            json={"active_view_id": 1},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_preferences_isolated_per_user(self, client, db):
        """不同用户的偏好应相互隔离."""
        # 用户 A
        client.post("/api/v1/accounts/auth/register", json={"username": "userA", "password": "passw0rd"})
        token_a = client.post("/api/v1/accounts/auth/login", json={"login": "userA", "password": "passw0rd"}).json()[
            "access_token"
        ]
        ha = {"Authorization": f"Bearer {token_a}"}

        # 用户 B
        client.post("/api/v1/accounts/auth/register", json={"username": "userB", "password": "passw0rd"})
        token_b = client.post("/api/v1/accounts/auth/login", json={"login": "userB", "password": "passw0rd"}).json()[
            "access_token"
        ]
        hb = {"Authorization": f"Bearer {token_b}"}

        user_a: User = db.query(User).filter(User.username == "userA").first()
        db.query(User).filter(User.username == "userB").first()
        _ws_a, dt_a, dv_a = _make_table_with_view(db, user_a)

        # A 设置偏好
        client.put(
            f"/api/v1/accounts/preferences/tables/{dt_a.id}/active-view",
            json={"active_view_id": dv_a.id},
            headers=ha,
        )

        # B 查询同表偏好应是 null（B 无此偏好）
        r = client.get(
            f"/api/v1/accounts/preferences/tables/{dt_a.id}/active-view",
            headers=hb,
        )
        assert r.status_code == 200
        assert r.json()["active_view_id"] is None
