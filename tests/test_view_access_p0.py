"""P0 视图权限安全回归（ADR 0003）.

对照 ADR「测试清单 · 接口层（P0 回归）」与不变量 I1/I6/I7，逐条给出反向断言：

- 他人个人视图 ``GET`` / ``rows`` / ``kanban`` / ``calendar`` / ``export`` 一律 **404**
- ``PATCH`` / ``DELETE`` 他人个人视图 → **404**（表 owner / 工作区 OWNER / 超管同样如此，D2）
- ``reorder`` 响应不含他人视图，且不篡改他人视图的 ``order``
- 表详情 ``views`` 与 ``view_count`` 不含他人个人视图
- 公共视图对仅 READ 用户可**读**（GET 200），但改/删仍 **403**（I7 权级单调）
- 个人视图不得持有 ``is_default``（否则等价于仅 READ 用户抢走全表落地页）
"""

from __future__ import annotations

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable, DataView
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def owner(db):
    u = User(username="p0_owner", nickname="P0 Owner")
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
    w = Workspace(name="P0WS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="P0Table", owner_id=None)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    df = DataField(table_id=dt.id, name="姓名", field_type="text", order=0)
    df.ensure_db_name()
    db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    return dt


def _make_member(db, ws, username: str, role: WorkspaceRole = WorkspaceRole.VIEWER, **kwargs):
    u = User(username=username, email=f"{username}@example.com", **kwargs)
    u.set_password("pw")
    u.role = "user"
    db.add(u)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=role))
    db.commit()
    db.refresh(u)
    return u


def _login(client, username: str, password: str = "pw") -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": password})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _views_url(ws, table) -> str:
    return f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views"


def _create_public_view(client, ws, table, headers, name: str, **extra) -> int:
    r = client.post(_views_url(ws, table), json={"name": name, "view_type": "grid", **extra}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_personal_view(client, ws, table, headers, name: str, **extra) -> int:
    r = client.post(_views_url(ws, table), json={"name": name, "view_type": "grid", **extra}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["owner_id"] is not None, "仅 READ 用户创建的视图应为个人视图"
    return body["id"]


# ── 缺陷 ①：视图驱动端点补 VIEW_READ 校验 ──────────────


class TestViewDrivenReadIsolation:
    """他人个人视图不得通过 rows / kanban / calendar 取数."""

    # 同一个人视图同时配置分组字段与日期字段，便于一次覆盖三个端点（端点不校验 view_type）
    _OPTS = {"group_field": "姓名", "start_field": "姓名"}

    @pytest.fixture
    def personal_view(self, client, db, ws, table, owner):
        _make_member(db, ws, "p0_ra")
        a_h = _login(client, "p0_ra")
        vid = _create_personal_view(client, ws, table, a_h, "A的私有视角", view_options=self._OPTS)
        return vid

    @pytest.mark.parametrize("suffix", ["rows", "kanban", "calendar"])
    def test_other_viewer_gets_404(self, client, db, ws, table, personal_view, suffix):
        _make_member(db, ws, "p0_rb")
        b_h = _login(client, "p0_rb")
        r = client.get(f"{_views_url(ws, table)}/{personal_view}/{suffix}", headers=b_h)
        assert r.status_code == 404, f"{suffix} 泄露了他人个人视图（缺陷 ①）"

    @pytest.mark.parametrize("suffix", ["rows", "kanban", "calendar"])
    def test_table_owner_gets_404(self, client, ws, table, personal_view, auth_owner, suffix):
        """表 owner（有全部表权限）同样不可见他人个人视图（D2）."""
        r = client.get(f"{_views_url(ws, table)}/{personal_view}/{suffix}", headers=auth_owner)
        assert r.status_code == 404

    @pytest.mark.parametrize("suffix", ["rows", "kanban", "calendar"])
    def test_superuser_gets_404(self, client, db, ws, table, personal_view, suffix):
        """超管亦不可见——个人视图对**一切**非创建者 404（D2）."""
        _make_member(db, ws, "p0_su", is_superuser=True)
        su_h = _login(client, "p0_su")
        r = client.get(f"{_views_url(ws, table)}/{personal_view}/{suffix}", headers=su_h)
        assert r.status_code == 404

    def test_creator_still_allowed(self, client, ws, table, personal_view):
        a_h = _login(client, "p0_ra")
        r = client.get(f"{_views_url(ws, table)}/{personal_view}/rows", headers=a_h)
        assert r.status_code == 200


# ── 缺陷 ⑤：有 EDIT_VIEWS 者不得改删他人个人视图 ──────


class TestPrivateViewWriteIsolation:
    @pytest.fixture
    def personal_view(self, client, db, ws, table):
        _make_member(db, ws, "p0_wa")
        a_h = _login(client, "p0_wa")
        return _create_personal_view(client, ws, table, a_h, "A的私有写入保护区")

    def test_table_owner_patch_404(self, client, ws, table, personal_view, auth_owner):
        r = client.patch(
            f"{_views_url(ws, table)}/{personal_view}",
            json={"name": "被管理员篡改"},
            headers=auth_owner,
        )
        assert r.status_code == 404, "有 EDIT_VIEWS 者可改他人个人视图（缺陷 ⑤）"

    def test_table_owner_delete_404(self, client, ws, table, personal_view, auth_owner, db):
        r = client.delete(f"{_views_url(ws, table)}/{personal_view}", headers=auth_owner)
        assert r.status_code == 404, "有 EDIT_VIEWS 者可删他人个人视图（缺陷 ⑤）"
        assert db.get(DataView, personal_view) is not None, "视图不应被删除"

    def test_table_owner_get_404(self, client, ws, table, personal_view, auth_owner):
        r = client.get(f"{_views_url(ws, table)}/{personal_view}", headers=auth_owner)
        assert r.status_code == 404

    def test_superuser_patch_404(self, client, db, ws, table, personal_view):
        _make_member(db, ws, "p0_wsu", is_superuser=True)
        su_h = _login(client, "p0_wsu")
        r = client.patch(
            f"{_views_url(ws, table)}/{personal_view}",
            json={"name": "超管篡改"},
            headers=su_h,
        )
        assert r.status_code == 404

    def test_creator_can_patch_own(self, client, ws, table, personal_view):
        a_h = _login(client, "p0_wa")
        r = client.patch(
            f"{_views_url(ws, table)}/{personal_view}",
            json={"name": "A自己改名"},
            headers=a_h,
        )
        assert r.status_code == 200


# ── 缺陷 ②：reorder 不得返回/改写他人视图 ─────────────


class TestReorderIsolation:
    def test_response_excludes_and_does_not_touch_others_view(self, client, db, ws, table, auth_owner):
        _make_member(db, ws, "p0_ra2")
        a_h = _login(client, "p0_ra2")
        personal_id = _create_personal_view(client, ws, table, a_h, "A的私有顺序保护")

        pub1 = _create_public_view(client, ws, table, auth_owner, "公共1")
        pub2 = _create_public_view(client, ws, table, auth_owner, "公共2")

        before = db.get(DataView, personal_id).order

        # owner 主动把他人个人视图排到最前 —— 不应生效，也不应出现在响应里
        r = client.post(
            f"{_views_url(ws, table)}/reorder",
            json=[personal_id, pub2, pub1],
            headers=auth_owner,
        )
        assert r.status_code == 200
        ids = [v["id"] for v in r.json()]
        assert personal_id not in ids, "reorder 响应泄露了他人个人视图（缺陷 ②）"
        assert ids == [pub2, pub1]

        db.expire_all()
        assert db.get(DataView, personal_id).order == before, "他人个人视图的顺序不应被改写"


# ── 缺陷 ③：表详情不得返回他人个人视图 ────────────────


class TestTableDetailIsolation:
    def test_detail_views_and_count_scoped_to_visibility(self, client, db, ws, table, auth_owner):
        _make_member(db, ws, "p0_da")
        a_h = _login(client, "p0_da")
        personal_id = _create_personal_view(client, ws, table, a_h, "A的私有摘要")

        pub1 = _create_public_view(client, ws, table, auth_owner, "公共摘要1")
        pub2 = _create_public_view(client, ws, table, auth_owner, "公共摘要2")

        # owner（EDIT_VIEWS）：只看得到两条公共视图
        r = client.get(f"/api/v1/workspaces/{ws.id}/tables/{table.id}", headers=auth_owner)
        assert r.status_code == 200
        body = r.json()
        assert {v["id"] for v in body["views"]} == {pub1, pub2}, "表详情泄露了他人个人视图（缺陷 ③）"
        assert body["view_count"] == 2, "view_count 应只统计可见视图"

        # 创建者本人：两条公共 + 自己的一条
        r = client.get(f"/api/v1/workspaces/{ws.id}/tables/{table.id}", headers=a_h)
        assert r.status_code == 200
        body = r.json()
        assert {v["id"] for v in body["views"]} == {pub1, pub2, personal_id}
        assert body["view_count"] == 3

        # 无关 viewer：只有两条公共视图
        _make_member(db, ws, "p0_db")
        b_h = _login(client, "p0_db")
        r = client.get(f"/api/v1/workspaces/{ws.id}/tables/{table.id}", headers=b_h)
        assert r.status_code == 200
        assert {v["id"] for v in r.json()["views"]} == {pub1, pub2}


# ── 缺陷 ④：公共视图"列表可见但点开 403"口径统一 ──────


class TestPublicViewReadConsistency:
    def test_read_only_user_can_get_public_view(self, client, db, ws, table, auth_owner):
        vid = _create_public_view(client, ws, table, auth_owner, "公共口径")
        _make_member(db, ws, "p0_ca")
        v_h = _login(client, "p0_ca")

        names = {v["name"] for v in client.get(_views_url(ws, table), headers=v_h).json()}
        assert "公共口径" in names

        r = client.get(f"{_views_url(ws, table)}/{vid}", headers=v_h)
        assert r.status_code == 200, "列表可见的公共视图，详情不应 403（缺陷 ④）"

    def test_read_only_user_cannot_write_public_view(self, client, db, ws, table, auth_owner):
        vid = _create_public_view(client, ws, table, auth_owner, "公共只读")
        _make_member(db, ws, "p0_cb")
        v_h = _login(client, "p0_cb")

        assert client.patch(f"{_views_url(ws, table)}/{vid}", json={"name": "x"}, headers=v_h).status_code == 403
        assert client.delete(f"{_views_url(ws, table)}/{vid}", headers=v_h).status_code == 403


# ── is_default 守卫：个人视图不得占表级默认位 ─────────


class TestDefaultFlagGuard:
    def test_create_personal_view_with_is_default_400(self, client, db, ws, table):
        _make_member(db, ws, "p0_da2")
        a_h = _login(client, "p0_da2")
        r = client.post(
            _views_url(ws, table),
            json={"name": "想抢默认位", "view_type": "grid", "is_default": True},
            headers=a_h,
        )
        assert r.status_code == 400

    def test_patch_personal_view_to_default_400(self, client, db, ws, table):
        _make_member(db, ws, "p0_da3")
        a_h = _login(client, "p0_da3")
        vid = _create_personal_view(client, ws, table, a_h, "稍后想抢默认位")
        r = client.patch(f"{_views_url(ws, table)}/{vid}", json={"is_default": True}, headers=a_h)
        assert r.status_code == 400

    def test_import_downgrades_default_for_personal(self, client, db, ws, table):
        _make_member(db, ws, "p0_da4")
        a_h = _login(client, "p0_da4")
        r = client.post(
            f"{_views_url(ws, table)}/import",
            json=[{"name": "导入带默认", "view_type": "grid", "is_default": True}],
            headers=a_h,
        )
        assert r.status_code == 200
        created = r.json()
        assert len(created) == 1
        assert created[0]["is_default"] is False, "个人视图不应持有 is_default"

    def test_owner_can_still_patch_public_view_default(self, client, ws, table, auth_owner):
        vid = _create_public_view(client, ws, table, auth_owner, "公共可设默认")
        r = client.patch(f"{_views_url(ws, table)}/{vid}", json={"is_default": True}, headers=auth_owner)
        assert r.status_code == 200
        assert r.json()["is_default"] is True


# ── 导出与偏好：同样不得绕过视图可见性 ───────────────


class TestExportAndPreferenceIsolation:
    def test_export_with_others_personal_view_404(self, client, db, ws, table, auth_owner):
        _make_member(db, ws, "p0_ea")
        a_h = _login(client, "p0_ea")
        personal_id = _create_personal_view(
            client, ws, table, a_h, "A的导出私有", filters=[{"field_name": "姓名", "op": "=", "value": "张三"}]
        )

        # 另一个 viewer 借用他人视图的筛选条件导出 → 404
        _make_member(db, ws, "p0_eb")
        b_h = _login(client, "p0_eb")
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/export?format=json&view_id={personal_id}",
            headers=b_h,
        )
        assert r.status_code == 404

        # 表 owner 同样 404（D2）
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/export?format=json&view_id={personal_id}",
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_export_with_public_view_ok(self, client, db, ws, table, auth_owner):
        vid = _create_public_view(client, ws, table, auth_owner, "公共导出")
        _make_member(db, ws, "p0_ec")
        v_h = _login(client, "p0_ec")
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/export?format=json&view_id={vid}",
            headers=v_h,
        )
        assert r.status_code == 200

    def test_cannot_pin_others_personal_view_as_active_view(self, client, db, ws, table, auth_owner):
        _make_member(db, ws, "p0_pa")
        a_h = _login(client, "p0_pa")
        personal_id = _create_personal_view(client, ws, table, a_h, "A的私有偏好")

        _make_member(db, ws, "p0_pb")
        b_h = _login(client, "p0_pb")
        r = client.put(
            f"/api/v1/accounts/preferences/tables/{table.id}/active-view",
            json={"active_view_id": personal_id},
            headers=b_h,
        )
        assert r.status_code == 400

        # 设为自己可见的公共视图 → 正常
        pub = _create_public_view(client, ws, table, auth_owner, "公共偏好")
        r = client.put(
            f"/api/v1/accounts/preferences/tables/{table.id}/active-view",
            json={"active_view_id": pub},
            headers=b_h,
        )
        assert r.status_code == 200
