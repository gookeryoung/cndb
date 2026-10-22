"""用户偏好 API 测试 —— 每张表激活视图 + 主页收藏视图 / 自定义顺序（ADR 0021）."""

from __future__ import annotations

from cndb.plugins.accounts.models import User
from cndb.plugins.accounts.services.preferences import MAX_FAVORITE_VIEWS, normalize_ids
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
        """新注册用户 preferences 字段应含空 active_views 与主页排序 / 收藏键."""
        user = User(username="pref_user", email="p@example.com", nickname="P")
        user.set_password("passw0rd")
        db.add(user)
        db.commit()
        db.refresh(user)
        assert user.preferences == {"active_views": {}, "workspace_order": [], "favorite_views": []}


# ── Preferences API ──


class TestPreferencesAPI:
    def test_get_preferences_empty(self, client, auth_headers):
        """首次查询应返回空映射与空的主页排序 / 收藏."""
        r = client.get("/api/v1/accounts/preferences", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"active_views": {}, "workspace_order": [], "favorite_view_ids": []}

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

        # A 自己读回偏好（可读表 → 200）
        r_a = client.get(
            f"/api/v1/accounts/preferences/tables/{dt_a.id}/active-view",
            headers=ha,
        )
        assert r_a.status_code == 200
        assert r_a.json()["active_view_id"] == dv_a.id

        # B 读不到 A 的表 → 403（此前返回 200 + null，只靠"无偏好"实现隔离；
        # 现按 TableAction.READ 判定，连"该表存在"这一点也不回显）
        r = client.get(
            f"/api/v1/accounts/preferences/tables/{dt_a.id}/active-view",
            headers=hb,
        )
        assert r.status_code == 403


# ── 主页收藏视图 / 工作区顺序（ADR 0021） ────────────────


def _add_workspace_viewer(db, ws: Workspace, username: str) -> User:
    """在指定工作区建一个 VIEWER 账号并返回用户对象."""
    user = User(username=username, email=f"{username}@example.com")
    user.set_password("pw")
    db.add(user)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.VIEWER))
    db.commit()
    db.refresh(user)
    return user


def _login(client, username: str, password: str = "pw") -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": password})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_table_view(
    db,
    dt: DataTable,
    owner: User,
    name: str,
    *,
    visibility: str = "table",
) -> DataView:
    """在已有表上建一个带筛选 / 排序的视图（默认表内可见）."""
    dv = DataView(
        table_id=dt.id,
        owner_id=owner.id,
        name=name,
        view_type="grid",
        visibility=visibility,
        scope_key=0 if visibility != "private" else owner.id,
        filters=[{"field_name": "状态", "op": "=", "value": "待办"}],
        sortings=[{"field_name": "截止日期", "direction": "asc"}],
        view_options={"row_height": "medium"},
    )
    db.add(dv)
    db.commit()
    db.refresh(dv)
    return dv


class TestNormalizeIds:
    def test_dedupe_and_drop_invalid(self):
        """去重保序，丢弃非正整数 / 非数字."""
        assert normalize_ids([3, "3", 1, 0, -2, "x", None, 2]) == [3, 1, 2]
        assert normalize_ids(None) == []


class TestFavoriteViewsAPI:
    def test_preferences_include_new_keys(self, client, auth_headers):
        """GET /preferences 返回 favorite_view_ids / workspace_order."""
        r = client.get("/api/v1/accounts/preferences", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["favorite_view_ids"] == []
        assert r.json()["workspace_order"] == []

    def test_favorite_roundtrip_and_order(self, client, db, auth_headers):
        """收藏后按写入顺序返回摘要，字段含视图 / 表 / 工作区信息."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        ws, dt, dv1 = _make_table_with_view(db, user)
        dv2 = _make_table_view(db, dt, user, "高优先级")

        r = client.put(
            "/api/v1/accounts/preferences/favorite-views",
            json={"view_ids": [dv2.id, dv1.id, dv2.id]},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["view_ids"] == [dv2.id, dv1.id]

        r = client.get("/api/v1/accounts/preferences/favorite-views", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert [item["view_id"] for item in body] == [dv2.id, dv1.id]
        first = body[0]
        assert first["name"] == "高优先级"
        assert first["view_type"] == "grid"
        assert first["table_id"] == dt.id
        assert first["table_name"] == dt.name
        assert first["workspace_id"] == ws.id
        assert first["workspace_name"] == ws.name
        assert first["filter_count"] == 1
        assert first["sort_count"] == 1
        assert first["visibility"] == "table"

        # GET /preferences 同步收藏 id 顺序
        r = client.get("/api/v1/accounts/preferences", headers=auth_headers)
        assert r.json()["favorite_view_ids"] == [dv2.id, dv1.id]

    def test_favorite_unknown_and_unreadable_ids_dropped(self, client, db, auth_headers):
        """不存在 / 他人私有视图静默丢弃，只保留可读视图."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        _ws, dt, dv = _make_table_with_view(db, user)

        # 同工作区 viewer 建的 private 视图：owner 也不可见（ADR 0003 D2）
        viewer = _add_workspace_viewer(db, _ws, "fav_viewer")
        private_view = _make_table_view(db, dt, viewer, "viewer 私有", visibility="private")

        r = client.put(
            "/api/v1/accounts/preferences/favorite-views",
            json={"view_ids": [999999, private_view.id, dv.id]},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["view_ids"] == [dv.id]

    def test_favorite_limited_to_max(self, client, auth_headers):
        """超过上限直接 400（在校验 id 之前拦截）."""
        ids = list(range(1, MAX_FAVORITE_VIEWS + 2))
        r = client.put(
            "/api/v1/accounts/preferences/favorite-views",
            json={"view_ids": ids},
            headers=auth_headers,
        )
        assert r.status_code == 400
        assert "最多收藏" in r.json()["detail"]

    def test_deleted_view_pruned_on_read(self, client, db, auth_headers):
        """视图删除后读取收藏自动剪枝并回写 preferences."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        _ws, dt, dv1 = _make_table_with_view(db, user)
        dv2 = _make_table_view(db, dt, user, "保留视图")
        client.put(
            "/api/v1/accounts/preferences/favorite-views",
            json={"view_ids": [dv1.id, dv2.id]},
            headers=auth_headers,
        )

        db.delete(dv1)
        db.commit()

        r = client.get("/api/v1/accounts/preferences/favorite-views", headers=auth_headers)
        assert [item["view_id"] for item in r.json()] == [dv2.id]
        r = client.get("/api/v1/accounts/preferences", headers=auth_headers)
        assert r.json()["favorite_view_ids"] == [dv2.id]

    def test_trashed_table_pruned_on_read(self, client, db, auth_headers):
        """所在表软删后收藏不再返回."""
        import datetime as dt_mod

        user: User = db.query(User).filter(User.username == "testuser").first()
        _ws, dt, dv = _make_table_with_view(db, user)
        client.put(
            "/api/v1/accounts/preferences/favorite-views",
            json={"view_ids": [dv.id]},
            headers=auth_headers,
        )

        dt.trashed_at = dt_mod.datetime.now(dt_mod.UTC)
        db.commit()

        r = client.get("/api/v1/accounts/preferences/favorite-views", headers=auth_headers)
        assert r.json() == []

    def test_lost_table_read_pruned_on_read(self, client, db, auth_headers):
        """被移出工作区后收藏不再返回."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        ws, _dt, dv = _make_table_with_view(db, user)
        client.put(
            "/api/v1/accounts/preferences/favorite-views",
            json={"view_ids": [dv.id]},
            headers=auth_headers,
        )

        db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == user.id
        ).delete()
        db.commit()

        r = client.get("/api/v1/accounts/preferences/favorite-views", headers=auth_headers)
        assert r.json() == []

    def test_favorite_has_no_view_side_effects(self, client, db, auth_headers):
        """收藏不修改视图配置 / 可见性 / 默认标记."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        _ws, _dt, dv = _make_table_with_view(db, user)
        before = (dv.visibility, dv.is_default, dv.view_options, dv.filters)

        client.put(
            "/api/v1/accounts/preferences/favorite-views",
            json={"view_ids": [dv.id]},
            headers=auth_headers,
        )
        db.refresh(dv)
        assert (dv.visibility, dv.is_default, dv.view_options, dv.filters) == before

    def test_favorites_isolated_per_user(self, client, db, auth_headers):
        """A / B 收藏互不影响."""
        user_a: User = db.query(User).filter(User.username == "testuser").first()
        _ws_a, _dt_a, dv_a = _make_table_with_view(db, user_a)

        user_b = User(username="fav_user_b", email="fav_b@example.com")
        user_b.set_password("pw")
        db.add(user_b)
        db.commit()
        hb = _login(client, "fav_user_b")

        client.put(
            "/api/v1/accounts/preferences/favorite-views",
            json={"view_ids": [dv_a.id]},
            headers=auth_headers,
        )
        assert client.get("/api/v1/accounts/preferences", headers=hb).json()["favorite_view_ids"] == []

    def test_favorite_endpoints_require_auth(self, client):
        assert client.get("/api/v1/accounts/preferences/favorite-views").status_code == 401
        assert client.put("/api/v1/accounts/preferences/favorite-views", json={"view_ids": []}).status_code == 401
        assert client.put("/api/v1/accounts/preferences/workspace-order", json={"workspace_ids": []}).status_code == 401


class TestWorkspaceOrderAPI:
    def test_workspace_order_filters_non_members_and_dedupes(self, client, db, auth_headers):
        """只保留当前用户为成员的工作区，去重保序."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        ws1, _dt1, _dv1 = _make_table_with_view(db, user)
        ws2, _dt2, _dv2 = _make_table_with_view(db, user)

        other = User(username="order_other", email="order_other@example.com")
        other.set_password("pw")
        db.add(other)
        db.commit()
        ws_other, _dt3, _dv3 = _make_table_with_view(db, other)

        r = client.put(
            "/api/v1/accounts/preferences/workspace-order",
            json={"workspace_ids": [ws2.id, ws_other.id, ws1.id, ws2.id]},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["workspace_ids"] == [ws2.id, ws1.id]

        r = client.get("/api/v1/accounts/preferences", headers=auth_headers)
        assert r.json()["workspace_order"] == [ws2.id, ws1.id]

    def test_workspace_order_isolated_per_user(self, client, db, auth_headers):
        """B 读取不到 A 的顺序."""
        user_a: User = db.query(User).filter(User.username == "testuser").first()
        ws, _dt, _dv = _make_table_with_view(db, user_a)

        user_b = User(username="order_b", email="order_b@example.com")
        user_b.set_password("pw")
        db.add(user_b)
        db.commit()
        hb = _login(client, "order_b")

        client.put(
            "/api/v1/accounts/preferences/workspace-order",
            json={"workspace_ids": [ws.id]},
            headers=auth_headers,
        )
        assert client.get("/api/v1/accounts/preferences", headers=hb).json()["workspace_order"] == []
