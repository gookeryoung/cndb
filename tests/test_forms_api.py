"""forms API 端点测试：CRUD / 角色矩阵 / 表级下限不变量 / 隐藏字段 / 字段漂移."""

from __future__ import annotations

from typing import Any

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

BASE = "/api/v1/workspaces/{wid}"


@pytest.fixture
def owner(db):
    u = User(username="f_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="FormsWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


def _make_member(db, ws, username: str, role: WorkspaceRole) -> User:
    """创建带工作区角色的成员用户."""
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=role))
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def viewer(db, ws):
    return _make_member(db, ws, "f_viewer", WorkspaceRole.VIEWER)


@pytest.fixture
def editor(db, ws):
    return _make_member(db, ws, "f_editor", WorkspaceRole.EDITOR)


@pytest.fixture
def admin(db, ws):
    return _make_member(db, ws, "f_admin", WorkspaceRole.ADMIN)


def _auth(client, user) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": user.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth_owner(client, owner):
    return _auth(client, owner)


@pytest.fixture
def auth_viewer(client, viewer):
    return _auth(client, viewer)


@pytest.fixture
def auth_editor(client, editor):
    return _auth(client, editor)


@pytest.fixture
def auth_admin(client, admin):
    return _auth(client, admin)


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="FormsTable", owner_id=None)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for i, (name, ftype) in enumerate([("姓名", "text"), ("年龄", "number"), ("邮箱", "text")]):
        df = DataField(table_id=dt.id, name=name, field_type=ftype, order=i)
        df.ensure_db_name()
        db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    return dt


def _create_form(client, ws, table, headers, **overrides: Any) -> dict:
    """经 API 创建表单（默认字段配置：姓名+年龄）."""
    payload: dict[str, Any] = {
        "table_id": table.id,
        "name": "录入表单",
        "field_config": [
            {"field_name": "姓名", "editable": True},
            {"field_name": "年龄", "editable": True},
        ],
    }
    payload.update(overrides)
    r = client.post(f"{BASE.format(wid=ws.id)}/forms", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ── 定义 CRUD ────────────────────────────────────────


class TestFormCRUD:
    def test_create_get_roundtrip(self, client, ws, table, auth_owner):
        created = _create_form(
            client,
            ws,
            table,
            auth_owner,
            description="描述",
            use_role="viewer",
            edit_role="editor",
            delete_role="admin",
        )
        r = client.get(f"{BASE.format(wid=ws.id)}/forms/{created['id']}", headers=auth_owner)
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "录入表单"
        assert data["description"] == "描述"
        assert [f["field_name"] for f in data["field_config"]] == ["姓名", "年龄"]
        assert data["use_role"] == "viewer"
        assert data["edit_role"] == "editor"
        assert data["delete_role"] == "admin"

    def test_meta_fields_enriched_with_field_type(self, client, ws, table, auth_owner):
        """meta 字段附带 field_type/required（前端控件选择依据）."""
        form = _create_form(
            client,
            ws,
            table,
            auth_owner,
            field_config=[{"field_name": "姓名"}, {"field_name": "年龄", "required": True}],
        )
        meta = client.get(f"{BASE.format(wid=ws.id)}/forms/{form['id']}/meta", headers=auth_owner).json()
        by_name = {f["field_name"]: f for f in meta["fields"]}
        assert by_name["姓名"]["field_type"] == "text"
        assert by_name["姓名"]["required"] is False  # 跟随字段定义
        assert by_name["年龄"]["required"] is True  # 表单显式覆盖

    def test_create_unknown_field_400(self, client, ws, table, auth_owner):
        r = client.post(
            f"{BASE.format(wid=ws.id)}/forms",
            json={"table_id": table.id, "name": "坏表单", "field_config": [{"field_name": "不存在"}]},
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "不存在" in r.json()["detail"]

    def test_create_duplicate_field_400(self, client, ws, table, auth_owner):
        r = client.post(
            f"{BASE.format(wid=ws.id)}/forms",
            json={
                "table_id": table.id,
                "name": "重字段表单",
                "field_config": [{"field_name": "姓名"}, {"field_name": "姓名"}],
            },
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "重复" in r.json()["detail"]

    def test_create_duplicate_name_400(self, client, ws, table, auth_owner):
        _create_form(client, ws, table, auth_owner)
        r = client.post(
            f"{BASE.format(wid=ws.id)}/forms",
            json={"table_id": table.id, "name": "录入表单"},
            headers=auth_owner,
        )
        assert r.status_code == 400

    def test_invalid_role_threshold_400(self, client, ws, table, auth_owner):
        r = client.post(
            f"{BASE.format(wid=ws.id)}/forms",
            json={"table_id": table.id, "name": "坏阈值", "use_role": "bogus"},
            headers=auth_owner,
        )
        assert r.status_code == 422  # Pydantic field_validator 拒绝非法角色

    def test_list_with_table_name(self, client, ws, table, auth_owner):
        _create_form(client, ws, table, auth_owner)
        r = client.get(f"{BASE.format(wid=ws.id)}/forms", headers=auth_owner)
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["table_name"] == "FormsTable"

    def test_update_roundtrip_and_rename_dup(self, client, ws, table, auth_owner):
        _create_form(client, ws, table, auth_owner)  # 占位表单：重命名撞名用
        f2 = _create_form(client, ws, table, auth_owner, name="第二个")
        r = client.patch(
            f"{BASE.format(wid=ws.id)}/forms/{f2['id']}",
            json={"name": "录入表单"},
            headers=auth_owner,
        )
        assert r.status_code == 400  # 重命名撞 f1
        r = client.patch(
            f"{BASE.format(wid=ws.id)}/forms/{f2['id']}",
            json={"description": "改了", "delete_role": "admin"},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["description"] == "改了"
        assert r.json()["delete_role"] == "admin"

    def test_delete_soft_and_hidden_from_list(self, client, ws, table, auth_owner):
        f = _create_form(client, ws, table, auth_owner)
        r = client.delete(f"{BASE.format(wid=ws.id)}/forms/{f['id']}", headers=auth_owner)
        assert r.status_code == 204
        assert client.get(f"{BASE.format(wid=ws.id)}/forms", headers=auth_owner).json() == []
        assert client.get(f"{BASE.format(wid=ws.id)}/forms/{f['id']}", headers=auth_owner).status_code == 404


# ── 行操作 ────────────────────────────────────────────


class TestFormRows:
    def test_row_crud_via_form(self, client, ws, table, auth_owner):
        form = _create_form(client, ws, table, auth_owner)
        base = f"{BASE.format(wid=ws.id)}/forms/{form['id']}/rows"
        # 建行
        r = client.post(base, json={"values": {"姓名": "张三", "年龄": 30}}, headers=auth_owner)
        assert r.status_code == 201, r.text
        row = r.json()
        assert row["姓名"] == "张三"
        # 查列表
        r = client.get(base, headers=auth_owner)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["rows"][0]["姓名"] == "张三"
        # 改行
        r = client.patch(f"{base}/{row['id']}", json={"values": {"年龄": 31}}, headers=auth_owner)
        assert r.status_code == 200, r.text
        assert r.json()["年龄"] == 31
        # 删行（软删）
        r = client.delete(f"{base}/{row['id']}", headers=auth_owner)
        assert r.status_code == 204
        assert client.get(base, headers=auth_owner).json()["total"] == 0

    def test_create_row_applies_form_defaults(self, client, ws, table, auth_owner):
        form = _create_form(
            client,
            ws,
            table,
            auth_owner,
            field_config=[{"field_name": "姓名", "default_value": "默认名"}],
        )
        base = f"{BASE.format(wid=ws.id)}/forms/{form['id']}/rows"
        r = client.post(base, json={"values": {}}, headers=auth_owner)
        assert r.status_code == 201
        assert r.json()["姓名"] == "默认名"

    def test_update_row_strips_non_editable(self, client, ws, table, auth_owner):
        form = _create_form(
            client,
            ws,
            table,
            auth_owner,
            field_config=[{"field_name": "姓名", "editable": True}, {"field_name": "年龄", "editable": False}],
        )
        base = f"{BASE.format(wid=ws.id)}/forms/{form['id']}/rows"
        row = client.post(base, json={"values": {"姓名": "李四", "年龄": 20}}, headers=auth_owner).json()
        r = client.patch(f"{base}/{row['id']}", json={"values": {"姓名": "王五", "年龄": 99}}, headers=auth_owner)
        assert r.status_code == 200
        assert r.json()["姓名"] == "王五"
        assert r.json()["年龄"] == 20  # editable=False 字段被剔除

    def test_create_row_restricts_keys_to_visible_config(self, client, ws, table, auth_owner):
        """field_config 只含姓名 → 邮箱（表内存在但不在配置）被剔除."""
        form = _create_form(
            client,
            ws,
            table,
            auth_owner,
            field_config=[{"field_name": "姓名"}],
        )
        base = f"{BASE.format(wid=ws.id)}/forms/{form['id']}/rows"
        r = client.post(base, json={"values": {"姓名": "赵六", "邮箱": "x@x.com"}}, headers=auth_owner)
        assert r.status_code == 201
        assert r.json()["邮箱"] is None


# ── 权限：角色矩阵与不变量 ────────────────────────────


class TestFormPermissions:
    def test_meta_operation_bits_default(self, client, ws, table, auth_owner, auth_viewer, auth_editor):
        """空阈值：操作位由表级默认（EDIT_RECORDS→editor）决定."""
        form = _create_form(client, ws, table, auth_owner)
        base = f"{BASE.format(wid=ws.id)}/forms/{form['id']}/meta"
        vm = client.get(base, headers=auth_viewer).json()
        assert (vm["can_submit"], vm["can_edit"], vm["can_delete"]) == (False, False, False)
        em = client.get(base, headers=auth_editor).json()
        assert (em["can_submit"], em["can_edit"], em["can_delete"]) == (True, True, True)

    def test_use_threshold(self, client, ws, table, auth_owner, auth_editor, auth_admin):
        form = _create_form(client, ws, table, auth_owner, use_role="admin")
        url = f"{BASE.format(wid=ws.id)}/forms/{form['id']}/meta"
        assert client.get(url, headers=auth_editor).status_code == 403
        assert client.get(url, headers=auth_admin).status_code == 200

    def test_edit_threshold(self, client, ws, table, auth_owner, auth_editor, auth_admin):
        form = _create_form(client, ws, table, auth_owner, edit_role="admin")
        base = f"{BASE.format(wid=ws.id)}/forms/{form['id']}/rows"
        row = client.post(base, json={"values": {"姓名": "甲"}}, headers=auth_admin).json()
        assert (
            client.patch(f"{base}/{row['id']}", json={"values": {"姓名": "乙"}}, headers=auth_editor).status_code == 403
        )
        assert (
            client.patch(f"{base}/{row['id']}", json={"values": {"姓名": "乙"}}, headers=auth_admin).status_code == 200
        )

    def test_delete_threshold(self, client, ws, table, auth_owner, auth_editor, auth_admin):
        form = _create_form(client, ws, table, auth_owner, delete_role="admin")
        base = f"{BASE.format(wid=ws.id)}/forms/{form['id']}/rows"
        row = client.post(base, json={"values": {"姓名": "甲"}}, headers=auth_admin).json()
        assert client.delete(f"{base}/{row['id']}", headers=auth_editor).status_code == 403
        assert client.delete(f"{base}/{row['id']}", headers=auth_admin).status_code == 204

    def test_table_permission_is_floor(self, client, ws, table, auth_viewer, auth_owner):
        """表级权限是下限：表 read_role=editor 时 viewer 即使表单无阈值也被 403."""
        client.put(
            f"{BASE.format(wid=ws.id)}/tables/{table.id}/permissions",
            json={"read_role": "editor"},
            headers=auth_owner,
        )
        form = _create_form(client, ws, table, auth_owner)
        url = f"{BASE.format(wid=ws.id)}/forms/{form['id']}/meta"
        assert client.get(url, headers=auth_viewer).status_code == 403
        # 旁路不变量：records API 行为同步收紧，未被表单放宽
        assert client.get(f"{BASE.format(wid=ws.id)}/tables/{table.id}/records", headers=auth_viewer).status_code == 403

    def test_list_filters_tables_without_read(self, client, ws, table, auth_editor, auth_owner):
        """用户无 READ 的表，其表单不出现在列表."""
        client.put(
            f"{BASE.format(wid=ws.id)}/tables/{table.id}/permissions",
            json={"read_role": "admin"},
            headers=auth_owner,
        )
        _create_form(client, ws, table, auth_owner)
        assert client.get(f"{BASE.format(wid=ws.id)}/forms", headers=auth_editor).json() == []

    def test_form_management_needs_edit_views(self, client, ws, table, auth_viewer):
        """表单定义管理需 EDIT_VIEWS：viewer 建表单被拒."""
        r = client.post(
            f"{BASE.format(wid=ws.id)}/forms",
            json={"table_id": table.id, "name": "越权表单"},
            headers=auth_viewer,
        )
        assert r.status_code == 403


# ── 隐藏字段与字段漂移 ────────────────────────────────


class TestFieldVisibility:
    def test_hidden_field_excluded_everywhere(self, client, ws, table, auth_editor, auth_owner):
        """表级隐藏字段：meta 字段、行数据、写入载荷三处全部过滤."""
        client.put(
            f"{BASE.format(wid=ws.id)}/tables/{table.id}/permissions",
            json={"hidden_fields": {"editor": ["邮箱"]}},
            headers=auth_owner,
        )
        form = _create_form(
            client,
            ws,
            table,
            auth_owner,
            field_config=[{"field_name": "姓名"}, {"field_name": "邮箱"}],
        )
        meta = client.get(f"{BASE.format(wid=ws.id)}/forms/{form['id']}/meta", headers=auth_editor).json()
        names = [f["field_name"] for f in meta["fields"]]
        assert "邮箱" not in names
        assert meta["invalid_fields"] == ["邮箱"]
        # 写路径剔除隐藏字段
        base = f"{BASE.format(wid=ws.id)}/forms/{form['id']}/rows"
        r = client.post(base, json={"values": {"姓名": "钱七", "邮箱": "h@x.com"}}, headers=auth_editor)
        assert r.status_code == 201
        assert r.json()["邮箱"] is None
        # 读路径行数据不含隐藏字段
        rows = client.get(base, headers=auth_editor).json()["rows"]
        assert "邮箱" not in rows[0]

    def test_trashed_field_drift(self, client, ws, table, db, auth_owner):
        """引用字段被软删后 meta 过滤并附失效清单，不 500."""
        form = _create_form(
            client,
            ws,
            table,
            auth_owner,
            field_config=[{"field_name": "姓名"}, {"field_name": "年龄"}],
        )
        df = db.query(DataField).filter(DataField.table_id == table.id, DataField.name == "年龄").first()
        df.trashed = True
        db.commit()
        r = client.get(f"{BASE.format(wid=ws.id)}/forms/{form['id']}/meta", headers=auth_owner)
        assert r.status_code == 200
        meta = r.json()
        assert [f["field_name"] for f in meta["fields"]] == ["姓名"]
        assert meta["invalid_fields"] == ["年龄"]


__all__ = []
