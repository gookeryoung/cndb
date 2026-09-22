"""综合覆盖率补全 — 覆盖 access / public / tables / transfer 零散缺口."""

from __future__ import annotations

import subprocess

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.services.core import access as access_mod
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables import transfer as transfer_mod
from cndb.plugins.tables.models import (
    DataField,
    DataTable,
    TableMember,
    TablePermission,
)
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

# ── access.py 单元测试 ───────────────────────────────


@pytest.fixture
def _ws_table_user(db):
    ws = Workspace(name="PatchWS")
    db.add(ws)
    db.flush()
    owner = User(username="p_owner", nickname="O")
    owner.set_password("p1")
    db.add(owner)
    viewer = User(username="p_viewer", nickname="V")
    viewer.set_password("p1")
    db.add(viewer)
    writerm = User(username="p_writer", nickname="W")
    writerm.set_password("p1")
    db.add(writerm)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=writerm.id, role=WorkspaceRole.EDITOR))

    dt = DataTable(workspace_id=ws.id, name="T", owner_id=owner.id)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    df = DataField(table_id=dt.id, name="name", field_type="text", order=0)
    df.ensure_db_name()
    db.add(df)
    db.commit()
    db.refresh(dt)
    return ws, dt, owner, viewer, writerm


@pytest.fixture
def outsider_user(db):
    u = User(username="p_out", nickname="Out")
    u.set_password("p1")
    db.add(u)
    db.commit()
    return u


class TestAccessModule:
    def test_check_action_member_write(self, db, _ws_table_user):
        _ws, dt, _owner, viewer, _writerm = _ws_table_user
        db.add(TableMember(table_id=dt.id, user_id=viewer.id, role="write"))
        db.commit()
        assert access_mod.check_action(db, dt, viewer, access_mod.TableAction.EDIT_RECORDS) is True
        assert access_mod.check_action(db, dt, viewer, access_mod.TableAction.EDIT_SCHEMA) is False

    def test_check_action_member_read(self, db, _ws_table_user):
        _ws, dt, _owner, _viewer, writerm = _ws_table_user
        db.add(TableMember(table_id=dt.id, user_id=writerm.id, role="read"))
        db.commit()
        assert access_mod.check_action(db, dt, writerm, access_mod.TableAction.READ) is True
        assert access_mod.check_action(db, dt, writerm, access_mod.TableAction.EDIT_RECORDS) is False

    def test_check_action_unknown_member_role(self, db, _ws_table_user):
        _ws, dt, _owner, viewer, _writerm = _ws_table_user
        db.add(TableMember(table_id=dt.id, user_id=viewer.id, role="super"))
        db.commit()
        assert access_mod.check_action(db, dt, viewer, access_mod.TableAction.READ) is True
        assert access_mod.check_action(db, dt, viewer, access_mod.TableAction.EDIT_SCHEMA) is False

    def test_row_filter_conjunction_default_and(self, db, _ws_table_user):
        _ws, dt, _owner, _viewer, _writerm = _ws_table_user
        assert access_mod.row_filter_conjunction(db, dt) == "AND"

    def test_row_filter_conjunction_or(self, db, _ws_table_user):
        _ws, dt, _owner, _viewer, _writerm = _ws_table_user
        db.add(TablePermission(table_id=dt.id, row_filters=[{"field": "x"}], row_filter_type="OR"))
        db.commit()
        assert access_mod.row_filter_conjunction(db, dt) == "OR"

    def test_row_filter_conjunction_invalid(self, db, _ws_table_user):
        _ws, dt, _owner, _viewer, _writerm = _ws_table_user
        db.add(TablePermission(table_id=dt.id, row_filters=[{"field": "x"}], row_filter_type="FUNNY"))
        db.commit()
        assert access_mod.row_filter_conjunction(db, dt) == "AND"

    def test_get_hidden_field_names_no_perm(self, db, _ws_table_user):
        _ws, dt, _owner, viewer, _writerm = _ws_table_user
        assert access_mod.get_hidden_field_names(db, dt, viewer) == set()

    def test_get_hidden_field_names_none_role(self, db, _ws_table_user, outsider_user):
        _ws, dt, _owner, _viewer, _writerm = _ws_table_user
        db.add(TablePermission(table_id=dt.id, hidden_fields={"viewer": ["secret"]}))
        db.commit()
        assert access_mod.get_hidden_field_names(db, dt, outsider_user) == set()

    def test_apply_field_hiding(self):
        row = {"a": 1, "b": 2, "c": 3}
        result = access_mod.apply_field_hiding(row.copy(), {"b"})
        assert result == {"a": 1, "c": 3}

    def test_apply_field_hiding_rows(self):
        rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        result = access_mod.apply_field_hiding_rows(rows, ["b"])
        assert result == [{"a": 1}, {"a": 3}]


# ── transfer.py 零散函数 ───────────────────────────────


class TestTransferPatch:
    def test_python_type_to_field_type(self):
        assert transfer_mod._python_type_to_field_type(42) == "number"
        assert transfer_mod._python_type_to_field_type(3.14) == "float"
        assert transfer_mod._python_type_to_field_type(True) == "boolean"
        assert transfer_mod._python_type_to_field_type("hi") == "text"
        assert transfer_mod._python_type_to_field_type(None) == "empty"

    def test_guess_format_from_filename(self):
        assert transfer_mod.guess_format_from_filename("a.csv") == "csv"
        assert transfer_mod.guess_format_from_filename("a.xlsx") == "xlsx"
        assert transfer_mod.guess_format_from_filename("a.json") == "json"
        with pytest.raises(ValueError):
            transfer_mod.guess_format_from_filename("a.unknown")

    def test_infer_single_value(self):
        assert transfer_mod._infer_single_value("123") == "number"
        assert transfer_mod._infer_single_value("3.14") == "float"

    def test_export_rows_to_json_and_csv(self):
        rows = [{"a": 1, "b": "hi"}]
        assert transfer_mod.export_rows_to_json(rows) is not None
        assert transfer_mod.export_rows_to_json(rows).startswith("[")
        csv_text = transfer_mod.export_rows_to_csv(rows)
        assert "a" in csv_text.lower() or "a" in csv_text

    def test_check_phone(self):
        assert transfer_mod._check_phone("13812345678")
        assert not transfer_mod._check_phone("notaphone")

    def test_serialize_link_value_none(self):
        assert transfer_mod._serialize_link_value(None) is None

    def test_promote_select(self):
        cols, _ = transfer_mod.analyze_csv_columns("status\na\na\nb\n")
        assert any(c["name"] == "status" for c in cols)

    def test_csv_empty(self):
        cols, n = transfer_mod.analyze_csv_columns("")
        assert cols == []
        assert n == 0


# ── DDL 零散 ───────────────────────────────────────────


@pytest.fixture
def _u_ws(db):
    """在 db 里创建一个用户 + 工作区."""
    u = User(username="ddl_p", nickname="D")
    u.set_password("p1")
    db.add(u)
    db.flush()
    ws = Workspace(name="DDLWS", created_by_id=u.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(ws)
    return u, ws


class TestDDLPatch2:
    def test_recreate_table(self, db_engine, db, _u_ws):
        _u, ws = _u_ws
        dt = DataTable(workspace_id=ws.id, name="R1")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        df = DataField(table_id=dt.id, name="v", field_type="number", order=0)
        df.ensure_db_name()
        db.add(df)
        db.commit()
        db.refresh(dt)
        ddl.create_table(db_engine, dt)
        ddl.drop_table(db_engine, dt.db_table_name)
        ddl.create_table(db_engine, dt)
        assert True

    def test_drop_column(self, db_engine, db, _u_ws):
        _u, ws = _u_ws
        dt = DataTable(workspace_id=ws.id, name="DC1")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        df = DataField(table_id=dt.id, name="v", field_type="text", order=0)
        df.ensure_db_name()
        db.add(df)
        db.commit()
        db.refresh(dt)
        ddl.create_table(db_engine, dt)
        ddl.drop_column(db_engine, dt, df)
        assert True


# ── runner.py 零散 ────────────────────────────────────


class TestRunnerPatch:
    def test_runner_info(self):
        r = subprocess.run(
            ["uv", "run", "cndb", "info"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert r.returncode == 0


# ── public 分享路由 ───────────────────────────────────


class TestPublicPatch:
    def test_get_public_view_slug_missing(self, client):
        r = client.get("/api/v1/public/share/nonexistent-slug-xxx")
        assert r.status_code == 404


# ── preferences ───────────────────────────────────────


class TestPreferencesPatch:
    def test_preferences_defaults(self, client, auth_headers):
        r = client.get("/api/v1/accounts/preferences", headers=auth_headers)
        assert r.status_code == 200


# ── router/records 边缘 ───────────────────────────────


class TestRouterRecordsPatch:
    def test_record_not_found(self, client, db_engine, db, auth_headers):
        u = db.query(User).first()
        ws = Workspace(name="RecWS", created_by_id=u.id)
        db.add(ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
        dt = DataTable(workspace_id=ws.id, name="RT")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        df = DataField(table_id=dt.id, name="x", field_type="text", order=0)
        df.ensure_db_name()
        db.add(df)
        db.commit()
        db.refresh(dt)
        ddl.create_table(db_engine, dt)

        r = client.patch(
            f"/api/v1/workspaces/{ws.id}/tables/{dt.id}/records/99999",
            json={"values": {"x": "hi"}},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_delete_record_not_found(self, client, db_engine, db, auth_headers):
        u = db.query(User).first()
        ws = Workspace(name="DelWS", created_by_id=u.id)
        db.add(ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
        dt = DataTable(workspace_id=ws.id, name="DT")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        df = DataField(table_id=dt.id, name="x", field_type="text", order=0)
        df.ensure_db_name()
        db.add(df)
        db.commit()
        db.refresh(dt)
        ddl.create_table(db_engine, dt)

        r = client.delete(
            f"/api/v1/workspaces/{ws.id}/tables/{dt.id}/records/99999",
            headers=auth_headers,
        )
        assert r.status_code == 404


# ── tables router 边缘 ─────────────────────────────────


class TestTablesRouterPatch:
    def test_table_detail_not_found(self, client, db, auth_headers):
        u = db.query(User).first()
        ws = Workspace(name="TDWS", created_by_id=u.id)
        db.add(ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
        db.commit()
        r = client.get(f"/api/v1/workspaces/{ws.id}/tables/99999", headers=auth_headers)
        assert r.status_code == 404

    def test_copy_table_not_found(self, client, db, auth_headers):
        u = db.query(User).first()
        ws = Workspace(name="CTWS", created_by_id=u.id)
        db.add(ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
        db.commit()
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/99999/copy",
            json={"new_name": "XYZ"},
            headers=auth_headers,
        )
        assert r.status_code == 404


# ── field_types ────────────────────────────────────────


class TestFieldTypesPatch:
    def test_link_field_validate_none(self):
        from cndb.plugins.tables.field_types import LinkFieldType

        ft = LinkFieldType()
        # LinkFieldType validate_value 对 None 返回空列表
        assert ft.validate_value(None, {}) == []


# ── views router 边缘 ──────────────────────────────────


class TestViewsPatch:
    def test_list_views(self, client, db_engine, db, auth_headers):
        u = db.query(User).first()
        ws = Workspace(name="VWS", created_by_id=u.id)
        db.add(ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
        dt = DataTable(workspace_id=ws.id, name="VT")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        df = DataField(table_id=dt.id, name="v", field_type="text", order=0)
        df.ensure_db_name()
        db.add(df)
        db.commit()
        db.refresh(dt)
        ddl.create_table(db_engine, dt)

        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{dt.id}/views",
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)


__all__ = []
