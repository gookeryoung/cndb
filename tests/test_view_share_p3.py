"""P3 视图共享（``shared`` 档）与孤儿视图回归（ADR 0003 §4 / §6 / §7-2）.

覆盖三组：

1. **共享层**：名单校验（工作区范围内 + 表 READ + editor 需表 EDIT_VIEWS）、
   名单内 viewer 只读、editor 实时降级、非 shared 档不可改名单、
   ``visibility`` 端点一次开档 + 授权、``shareable-members`` 对普通 viewer 可用。
2. **能力位**：列表/详情响应带 ``can_edit`` / ``can_manage`` / ``grantee_count``，
   前端不再自行用 ``visibility`` + ``owner_id`` 推断。
3. **D3 孤儿**：创建者注销 / 离开工作区 → 视图保留且对**一切**身份不可见；
   重新加入即恢复。CLI 清理出口见 ``tests/test_cli_views.py``。

框架约定：外键 ``ON DELETE SET NULL`` 的实际行为由
``test_migration_missing_model_columns`` 在真实 SQLite 上验证；本文件的测试库
（StaticPool 内存 SQLite）默认不开 ``PRAGMA foreign_keys``，因此"账号已删除"的
落库状态用 ``owner_id = None`` 直接构造。
"""

from __future__ import annotations

from typing import Any

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import (
    DataField,
    DataTable,
    DataView,
    DataViewPermission,
    TablePermission,
    ViewVisibility,
)
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

# ── 夹具 ──────────────────────────────────────────────


@pytest.fixture
def owner(db):
    u = User(username="p3_owner", nickname="P3 Owner")
    u.set_password("pw")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth_owner(client, owner):
    return _login(client, owner.username)


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="P3WS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws, owner):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="P3Table", owner_id=owner.id)
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


def _make_member(db, ws, username: str, role: WorkspaceRole = WorkspaceRole.VIEWER, **kwargs: Any) -> User:
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
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _views_url(ws, table) -> str:
    return f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views"


def _view_url(ws, table, view_id: int) -> str:
    return f"{_views_url(ws, table)}/{view_id}"


def _create_view(client, ws, table, headers, name: str, **extra: Any) -> dict[str, Any]:
    r = client.post(_views_url(ws, table), json={"name": name, "view_type": "grid", **extra}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _set_visibility(client, ws, table, headers, view_id: int, visibility: str, **extra: Any):
    return client.post(
        f"{_view_url(ws, table, view_id)}/visibility",
        json={"visibility": visibility, **extra},
        headers=headers,
    )


def _set_table_permission(db, table, **fields: Any) -> TablePermission:
    """写入 / 更新该表的 TablePermission（未列出的字段保持原值）."""
    perm = db.query(TablePermission).filter(TablePermission.table_id == table.id).first()
    if perm is None:
        perm = TablePermission(table_id=table.id)
        db.add(perm)
    for key, value in fields.items():
        setattr(perm, key, value)
    db.commit()
    db.expire_all()
    return perm


def _orphan(db, view_id: int) -> None:
    """把视图落成"创建者已注销"的状态（外键 ``SET NULL`` 的结果状态）."""
    db.query(DataView).filter(DataView.id == view_id).update({"owner_id": None})
    db.commit()
    db.expire_all()


# ── §4 授权范围校验（「最大可放宽至数据表范围内」）─────


class TestGranteeScopeValidation:
    """名单只能落在数据表范围内：本工作区成员 ∧ 该表 READ（editor 另需 EDIT_VIEWS）."""

    @pytest.fixture
    def shared_view(self, client, ws, table, auth_owner) -> int:
        dv = _create_view(client, ws, table, auth_owner, "共享视角")
        r = _set_visibility(client, ws, table, auth_owner, dv["id"], "shared")
        assert r.status_code == 200, r.text
        return int(dv["id"])

    def test_grant_to_outsider_422(self, client, db, ws, table, auth_owner, shared_view):
        """非本工作区成员 → 422（视图授权永不放行表外的人，I1）."""
        outsider = User(username="p3_outsider", email="p3_outsider@example.com")
        outsider.set_password("pw")
        db.add(outsider)
        db.commit()
        db.refresh(outsider)

        r = client.put(
            f"{_view_url(ws, table, shared_view)}/members/{outsider.id}",
            json={"role": "viewer"},
            headers=auth_owner,
        )
        assert r.status_code == 422, r.text
        assert "本工作区成员" in r.json()["detail"]

    def test_grant_to_member_without_table_read_422(self, client, db, ws, table, auth_owner, shared_view):
        """对方是工作区成员，但表权限把它挡在外面 → 422（名单不得绕过表 READ 天花板）."""
        viewer = _make_member(db, ws, "p3_noread")
        _set_table_permission(db, table, read_role="editor")  # viewer 级成员失去表 READ

        r = client.put(
            f"{_view_url(ws, table, shared_view)}/members/{viewer.id}",
            json={"role": "viewer"},
            headers=auth_owner,
        )
        assert r.status_code == 422, r.text
        assert "查看权限" in r.json()["detail"]

    def test_grant_editor_without_table_edit_views_422(self, client, db, ws, table, auth_owner, shared_view):
        """给 viewer 级成员 editor 授权 → 422（否则名单成了提权旁路，I7）."""
        viewer = _make_member(db, ws, "p3_ed_denied")
        denied = client.put(
            f"{_view_url(ws, table, shared_view)}/members/{viewer.id}",
            json={"role": "editor"},
            headers=auth_owner,
        )
        assert denied.status_code == 422, denied.text
        assert "视图编辑权限" in denied.json()["detail"]

        ok = client.put(
            f"{_view_url(ws, table, shared_view)}/members/{viewer.id}",
            json={"role": "viewer"},
            headers=auth_owner,
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["role"] == "viewer"

    def test_grant_to_self_400(self, client, ws, table, owner, auth_owner, shared_view):
        """创建者天然全权，无需给自己授权 → 400."""
        r = client.put(
            f"{_view_url(ws, table, shared_view)}/members/{owner.id}",
            json={"role": "viewer"},
            headers=auth_owner,
        )
        assert r.status_code == 400, r.text

    def test_grant_unknown_user_404(self, client, ws, table, auth_owner, shared_view):
        r = client.put(
            f"{_view_url(ws, table, shared_view)}/members/999999",
            json={"role": "viewer"},
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_members_write_requires_shared_tier(self, client, db, ws, table, auth_owner):
        """``table`` 档的名单是惰性的，改它没有意义 → 400（先于任何用户查找）."""
        peer = _make_member(db, ws, "p3_tier_peer")
        dv = _create_view(client, ws, table, auth_owner, "表内可见", visibility="table")
        r = client.put(
            f"{_view_url(ws, table, dv['id'])}/members/{peer.id}",
            json={"role": "viewer"},
            headers=auth_owner,
        )
        assert r.status_code == 400, r.text
        assert "指定成员" in r.json()["detail"]
        assert (
            client.delete(f"{_view_url(ws, table, dv['id'])}/members/{peer.id}", headers=auth_owner).status_code == 400
        )

    def test_visibility_endpoint_rejects_members_on_non_shared(self, client, ws, table, auth_owner):
        dv = _create_view(client, ws, table, auth_owner, "私有视角")
        r = _set_visibility(client, ws, table, auth_owner, dv["id"], "table", members=[])
        assert r.status_code == 400, r.text

    def test_visibility_members_fail_atomically_on_bad_grantee(self, client, db, ws, table, auth_owner):
        """任一条名单不合法即 422 且**不部分写入**（全有或全无）."""
        good = _make_member(db, ws, "p3_atomic_ok")
        bad = _make_member(db, ws, "p3_atomic_bad")
        _set_table_permission(db, table, read_role="editor")  # bad 失去表 READ（good 也是 viewer → 也失去）

        dv = _create_view(client, ws, table, auth_owner, "视角")
        r = _set_visibility(
            client,
            ws,
            table,
            auth_owner,
            dv["id"],
            "shared",
            members=[{"user_id": good.id, "role": "viewer"}, {"user_id": bad.id, "role": "viewer"}],
        )
        assert r.status_code == 422, r.text
        assert db.query(DataViewPermission).filter(DataViewPermission.view_id == dv["id"]).count() == 0
        assert db.get(DataView, dv["id"]).visibility == ViewVisibility.PRIVATE


# ── 共享档的读写能力（I7 权级单调）─────────────────────


class TestSharedTierAccess:
    @pytest.fixture
    def granted(self, client, db, ws, table, auth_owner):
        """一个 ``shared`` 视图：viewer 级成员 ``p3_v`` 授 viewer、editor 级 ``p3_e`` 授 editor."""
        v = _make_member(db, ws, "p3_v")
        e = _make_member(db, ws, "p3_e", WorkspaceRole.EDITOR)
        dv = _create_view(client, ws, table, auth_owner, "指定成员视角")
        r = _set_visibility(
            client,
            ws,
            table,
            auth_owner,
            dv["id"],
            "shared",
            members=[{"user_id": v.id, "role": "viewer"}, {"user_id": e.id, "role": "editor"}],
        )
        assert r.status_code == 200, r.text
        return int(dv["id"]), v, e

    def test_grantee_count_reported(self, client, ws, table, auth_owner, granted):
        vid, _, _ = granted
        body = client.get(_view_url(ws, table, vid), headers=auth_owner).json()
        assert body["grantee_count"] == 2
        assert body["visibility"] == "shared"

    def test_roster_content(self, client, ws, table, auth_owner, granted):
        vid, v, e = granted
        roster = client.get(f"{_view_url(ws, table, vid)}/members", headers=auth_owner).json()
        assert [(r["user_id"], r["role"], r["available"]) for r in roster] == [
            (e.id, "editor", True),  # editor 排在前
            (v.id, "viewer", True),
        ]
        assert all(r["username"] for r in roster)

    def test_viewer_grantee_can_read_but_not_write(self, client, ws, table, granted):
        vid, v, _ = granted
        h = _login(client, v.username)
        assert client.get(_view_url(ws, table, vid), headers=h).status_code == 200
        assert vid in {x["id"] for x in client.get(_views_url(ws, table), headers=h).json()}
        assert client.patch(_view_url(ws, table, vid), json={"name": "越权改名"}, headers=h).status_code == 403
        assert client.delete(_view_url(ws, table, vid), headers=h).status_code == 403

    def test_viewer_grantee_cannot_read_roster(self, client, ws, table, granted):
        """名单本身不是公开信息（读名单需 VIEW_MANAGE，且视图可见才谈得上 403）."""
        vid, v, _ = granted
        h = _login(client, v.username)
        assert client.get(f"{_view_url(ws, table, vid)}/members", headers=h).status_code == 403
        assert client.get(f"{_view_url(ws, table, vid)}/shareable-members", headers=h).status_code == 403

    def test_editor_grantee_can_edit(self, client, ws, table, granted):
        vid, _, e = granted
        h = _login(client, e.username)
        r = client.patch(_view_url(ws, table, vid), json={"name": "编辑者改名"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "编辑者改名"

    def test_editor_grantee_loses_edit_when_table_permission_revoked(self, client, db, ws, table, auth_owner, granted):
        """生效权 = min(视图授权, 表权限)，且**实时求值** —— 表侧降级后编辑立刻失效."""
        vid, _, e = granted
        h = _login(client, e.username)
        assert client.patch(_view_url(ws, table, vid), json={"name": "改一次"}, headers=h).status_code == 200

        _set_table_permission(db, table, edit_views_role="owner")

        assert client.get(_view_url(ws, table, vid), headers=h).status_code == 200, "仍可看"
        assert client.patch(_view_url(ws, table, vid), json={"name": "再改一次"}, headers=h).status_code == 403
        roster = client.get(f"{_view_url(ws, table, vid)}/members", headers=auth_owner).json()
        assert next(r for r in roster if r["user_id"] == e.id)["available"] is False

    def test_non_grantee_member_gets_404(self, client, db, ws, table, granted):
        """不在名单里的普通成员：视图对其"不存在"（404，不泄露存在性，I6）."""
        vid, _, _ = granted
        _make_member(db, ws, "p3_other")
        h = _login(client, "p3_other")
        assert client.get(_view_url(ws, table, vid), headers=h).status_code == 404
        assert client.get(f"{_view_url(ws, table, vid)}/rows", headers=h).status_code == 404
        assert "指定成员视角" not in {x["name"] for x in client.get(_views_url(ws, table), headers=h).json()}

    def test_revoke_then_404(self, client, ws, table, auth_owner, granted):
        vid, v, _ = granted
        h = _login(client, v.username)
        assert client.get(_view_url(ws, table, vid), headers=h).status_code == 200

        assert client.delete(f"{_view_url(ws, table, vid)}/members/{v.id}", headers=auth_owner).status_code == 204
        assert client.get(_view_url(ws, table, vid), headers=h).status_code == 404
        # 重复收回：明确报"不在名单中"
        assert client.delete(f"{_view_url(ws, table, vid)}/members/{v.id}", headers=auth_owner).status_code == 404

    def test_change_role_viewer_to_editor(self, client, db, ws, table, auth_owner, granted):
        """改权：把 editor 级成员降为 viewer，其编辑入口立刻关闭."""
        vid, _, e = granted
        e_h = _login(client, e.username)
        assert client.patch(_view_url(ws, table, vid), json={"name": "改前"}, headers=e_h).status_code == 200

        r = client.put(f"{_view_url(ws, table, vid)}/members/{e.id}", json={"role": "viewer"}, headers=auth_owner)
        assert r.status_code == 200 and r.json()["role"] == "viewer"
        assert client.patch(_view_url(ws, table, vid), json={"name": "改后"}, headers=e_h).status_code == 403

    def test_switch_away_and_back_keeps_roster(self, client, db, ws, table, auth_owner, granted):
        """切到 ``private`` 后名单**保留但失效**，切回 ``shared`` 即恢复（不丢名单）."""
        vid, v, _ = granted
        h = _login(client, v.username)

        assert _set_visibility(client, ws, table, auth_owner, vid, "private").status_code == 200
        assert client.get(_view_url(ws, table, vid), headers=h).status_code == 404
        assert db.query(DataViewPermission).filter(DataViewPermission.view_id == vid).count() == 2

        assert _set_visibility(client, ws, table, auth_owner, vid, "shared").status_code == 200
        assert client.get(_view_url(ws, table, vid), headers=h).status_code == 200

    def test_private_to_table_without_edit_views_403(self, client, db, ws, table):
        """开放为 ``table`` 档需表 ``EDIT_VIEWS``（D4）."""
        v = _make_member(db, ws, "p3_pub")
        h = _login(client, v.username)
        dv = _create_view(client, ws, table, h, "我的私有视角")
        assert _set_visibility(client, ws, table, h, dv["id"], "table").status_code == 403

    def test_visibility_members_full_replace(self, client, ws, table, auth_owner, granted):
        """``members`` 是全量替换：未出现的既有授权被收回."""
        vid, v, e = granted
        r = _set_visibility(client, ws, table, auth_owner, vid, "shared", members=[{"user_id": e.id, "role": "viewer"}])
        assert r.status_code == 200, r.text
        assert r.json()["grantee_count"] == 1

        roster = client.get(f"{_view_url(ws, table, vid)}/members", headers=auth_owner).json()
        assert [(x["user_id"], x["role"]) for x in roster] == [(e.id, "viewer")]
        assert client.get(_view_url(ws, table, vid), headers=_login(client, v.username)).status_code == 404

    def test_visibility_without_members_keeps_roster(self, client, ws, table, auth_owner, granted):
        """``members`` 缺省（None）= 不动名单 —— 便于只改档位而不重选成员."""
        vid, _, _ = granted
        r = _set_visibility(client, ws, table, auth_owner, vid, "shared")
        assert r.status_code == 200
        assert r.json()["grantee_count"] == 2


# ── shareable-members（共享选择器数据源）───────────────


class TestShareableMembers:
    def test_viewer_selector_is_not_the_table_member_list(self, client, db, ws, table):
        """共享选择器的数据源是「工作区成员 ∧ 该表 ``READ``」，与
        ``GET /tables/{tid}/members``（``TableMember`` 授权表）不是一回事 ——
        后者在没有显式表成员授权时是空列表，拿它做选择器等于选不到人。
        另：后者要求工作区 VIEWER 起步，而 ``shareable-members`` 只要求视图 ``VIEW_MANAGE``。
        """
        v = _make_member(db, ws, "p3_sel_v")
        peer = _make_member(db, ws, "p3_sel_peer")
        h = _login(client, v.username)
        dv = _create_view(client, ws, table, h, "我的私有视角")

        r = client.get(f"{_view_url(ws, table, dv['id'])}/shareable-members", headers=h)
        assert r.status_code == 200, r.text
        ids = [x["user_id"] for x in r.json()]
        assert peer.id in ids and v.id not in ids, "不应把自己列为可授权对象"

        assert client.get(f"/api/v1/workspaces/{ws.id}/tables/{table.id}/members", headers=h).json() == []

    def test_excludes_members_without_table_read(self, client, db, ws, table, owner, auth_owner):
        """无表 READ 的成员不可被共享（表权限是硬天花板）；该表可见者才会出现."""
        low = _make_member(db, ws, "p3_sel_low")  # viewer 级
        mid = _make_member(db, ws, "p3_sel_mid", WorkspaceRole.EDITOR)
        _set_table_permission(db, table, read_role="editor")  # viewer 级失去 READ，editor 级保留
        dv = _create_view(client, ws, table, auth_owner, "视角")

        r = client.get(f"{_view_url(ws, table, dv['id'])}/shareable-members", headers=auth_owner)
        assert r.status_code == 200, r.text
        ids = {x["user_id"] for x in r.json()}
        assert low.id not in ids
        assert mid.id in ids
        assert owner.id not in ids, "操作者本人不是可授权对象"

    def test_editor_flag_reflects_table_edit_views(self, client, db, ws, table, auth_owner):
        editor = _make_member(db, ws, "p3_sel_ed", WorkspaceRole.EDITOR)
        viewer = _make_member(db, ws, "p3_sel_ro")
        dv = _create_view(client, ws, table, auth_owner, "视角")

        r = client.get(f"{_view_url(ws, table, dv['id'])}/shareable-members", headers=auth_owner)
        by_id = {x["user_id"]: x for x in r.json()}
        assert by_id[editor.id]["can_edit_views"] is True
        assert by_id[viewer.id]["can_edit_views"] is False

    def test_requires_view_manage(self, client, db, ws, table, auth_owner):
        """他人的私有视图 → 404（D2）；看不到自然也用不了选择器."""
        v = _make_member(db, ws, "p3_sel_hide")
        dv = _create_view(client, ws, table, _login(client, v.username), "私有视角")
        assert client.get(f"{_view_url(ws, table, dv['id'])}/shareable-members", headers=auth_owner).status_code == 404


# ── 能力位（列表/详情直接给出，前端不再自己推断）────────


class TestCapabilityFlags:
    def test_list_exposes_can_edit_can_manage_and_count(self, client, db, ws, table, auth_owner):
        v = _make_member(db, ws, "p3_cap_v")
        shared = _create_view(client, ws, table, auth_owner, "共享视角")
        assert (
            _set_visibility(
                client, ws, table, auth_owner, shared["id"], "shared", members=[{"user_id": v.id, "role": "viewer"}]
            ).status_code
            == 200
        )
        table_view = _create_view(client, ws, table, auth_owner, "表内可见", visibility="table")

        rows = {x["id"]: x for x in client.get(_views_url(ws, table), headers=auth_owner).json()}
        assert rows[shared["id"]]["can_edit"] is True and rows[shared["id"]]["can_manage"] is True
        assert rows[shared["id"]]["grantee_count"] == 1
        assert rows[table_view["id"]]["grantee_count"] == 0
        assert rows[table_view["id"]]["can_edit"] is True

        rows_v = {x["id"]: x for x in client.get(_views_url(ws, table), headers=_login(client, v.username)).json()}
        assert rows_v[shared["id"]]["can_edit"] is False
        assert rows_v[shared["id"]]["can_manage"] is False

    def test_table_tier_readonly_viewer_flags(self, client, db, ws, table, auth_owner):
        _make_member(db, ws, "p3_cap_ro")
        tv = _create_view(client, ws, table, auth_owner, "表内可见", visibility="table")
        body = client.get(_view_url(ws, table, tv["id"]), headers=_login(client, "p3_cap_ro")).json()
        assert body["can_edit"] is False and body["can_manage"] is False

    def test_create_response_carries_flags(self, client, ws, table, auth_owner):
        body = _create_view(client, ws, table, auth_owner, "新建")
        assert body["can_edit"] is True and body["can_manage"] is True and body["grantee_count"] == 0


# ── D1：每表至少一个 table 档视图 ──────────────────────


class TestLastTableTierGuard:
    def test_cannot_move_last_table_view_to_private(self, client, ws, table, auth_owner):
        dv = _create_view(client, ws, table, auth_owner, "全部", visibility="table", is_default=True)
        r = _set_visibility(client, ws, table, auth_owner, dv["id"], "private")
        assert r.status_code == 400, r.text
        assert "至少保留一个" in r.json()["detail"]

        _create_view(client, ws, table, auth_owner, "另一个公开视图", visibility="table")
        assert _set_visibility(client, ws, table, auth_owner, dv["id"], "private").status_code == 200


# ── D3：孤儿视图 ──────────────────────────────────────


class TestOrphanViews:
    def test_fk_is_set_null_in_metadata(self):
        """模型层钉住 D3：``owner_id`` 外键必须是 ``SET NULL``（否则"删账号 → 连带删视图"）."""
        fks = list(DataView.__table__.c.owner_id.foreign_keys)
        assert fks and fks[0].ondelete == "SET NULL"

    def test_orphan_kept_but_invisible_to_everyone(self, client, db, ws, table, auth_owner):
        v = _make_member(db, ws, "p3_orphan_a")
        h = _login(client, v.username)
        dv = _create_view(client, ws, table, h, "离职视角")
        _orphan(db, dv["id"])

        assert client.get(_view_url(ws, table, dv["id"]), headers=h).status_code == 404
        assert client.get(_view_url(ws, table, dv["id"]), headers=auth_owner).status_code == 404

        su = _make_member(db, ws, "p3_orphan_su", is_superuser=True)
        assert client.get(_view_url(ws, table, dv["id"]), headers=_login(client, su.username)).status_code == 404

        row = db.get(DataView, dv["id"])
        assert row is not None and row.owner_id is None, "D3：孤儿保留且归属置空（不删除、不转交）"

    def test_leaving_workspace_makes_orphan_and_rejoin_restores(self, client, db, ws, table):
        """创建者移出工作区 → 孤儿；重新加入 → 视图自动恢复可见（D3「保留优于删除」）."""
        from cndb.cli.views import find_orphan_views

        v = _make_member(db, ws, "p3_rejoin")
        h = _login(client, v.username)
        dv = _create_view(client, ws, table, h, "我的待办视角")
        assert find_orphan_views(db, ws.id) == []

        db.delete(
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == v.id)
            .first()
        )
        db.commit()
        db.expire_all()

        orphans = find_orphan_views(db, ws.id)
        assert [o["id"] for o in orphans] == [dv["id"]]
        assert orphans[0]["reason"] == "创建者已不在该工作区"
        assert orphans[0]["scope_key"] == v.id, "孤儿仍占原命名空间（同名重建需先清理）"
        # 离开工作区 → 连表 READ 都没有了（I1 天花板），表级入口先挡下 403；
        # 无论哪一层拦截，结果一致：视图对创建者不再可见
        assert client.get(_view_url(ws, table, dv["id"]), headers=h).status_code in (403, 404)

        db.add(WorkspaceMember(workspace_id=ws.id, user_id=v.id, role=WorkspaceRole.VIEWER))
        db.commit()
        db.expire_all()
        assert find_orphan_views(db, ws.id) == []
        assert client.get(_view_url(ws, table, dv["id"]), headers=h).status_code == 200

    def test_table_tier_with_null_owner_is_not_orphan(self, client, db, ws, table, owner):
        """``table`` 档即使创建者为空也仍对全表可见 —— 只有 ``private`` 档会成孤儿."""
        from cndb.cli.views import find_orphan_views

        dv = _create_view(client, ws, table, _login(client, owner.username), "全部", visibility="table")
        _orphan(db, dv["id"])
        assert find_orphan_views(db, ws.id) == []
        assert db.get(DataView, dv["id"]).visibility == ViewVisibility.TABLE
