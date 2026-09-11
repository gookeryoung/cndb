"""Coverage: access.py + query.py + transfer.py missing lines."""

from __future__ import annotations

import io

import pytest
from sqlalchemy import Column, Integer, MetaData, Table

from cndb.plugins.tables.access import (
    TableAction,
    _get_member_role,
    check_action,
    get_hidden_field_names,
)
from cndb.plugins.tables.models import DataTable, TablePermission


def _make_table(db, ws_id, name="t_x"):
    tbl = DataTable(workspace_id=ws_id, name=name)
    tbl.ensure_db_name()
    db.add(tbl)
    db.commit()
    db.refresh(tbl)
    return tbl


# ---------- access.py ----------


class TestGetHiddenFieldNamesMore:
    def test_no_member_role_returns_empty(self, db, client, auth_headers):
        from cndb.plugins.accounts.models import User

        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_hnone"})
        wid = ws.json()["id"]
        client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_hnone"})
        tbl = db.query(DataTable).filter_by(workspace_id=wid).first()
        perm = TablePermission(table_id=tbl.id, hidden_fields={"viewer": ["secret"]})
        db.add(perm)
        db.commit()
        user = db.query(User).first()
        assert get_hidden_field_names(db, tbl, user) == set()

    def test_hidden_for_role(self, db, client, auth_headers):
        from cndb.plugins.accounts.models import User
        from cndb.plugins.workspaces.models import WorkspaceRole

        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_hrole"})
        wid = ws.json()["id"]
        client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_hrole"})
        tbl = db.query(DataTable).filter_by(workspace_id=wid).first()
        perm = TablePermission(table_id=tbl.id, hidden_fields={WorkspaceRole.OWNER.value: ["x_field"]})
        db.add(perm)
        db.commit()
        user = db.query(User).first()
        hidden = get_hidden_field_names(db, tbl, user)
        assert "x_field" in hidden


class TestGetMemberRole:
    def test_returns_role_for_owner(self, db, client, auth_headers):
        from cndb.plugins.accounts.models import User
        from cndb.plugins.workspaces.models import WorkspaceRole

        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_gmr"})
        wid = ws.json()["id"]
        client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_gmr"})
        tbl = db.query(DataTable).filter_by(workspace_id=wid).first()
        user = db.query(User).first()
        role = _get_member_role(db, tbl, user)
        assert role is not None
        assert role == WorkspaceRole.OWNER


class TestCheckActionRealRoleFallback:
    def test_fallback_when_no_permission_record(self, db, client, auth_headers):
        from cndb.plugins.accounts.models import User

        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_fb2"})
        wid = ws.json()["id"]
        client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_fb2"})
        tbl = db.query(DataTable).filter_by(workspace_id=wid).first()
        user = db.query(User).first()
        assert check_action(db, tbl, user, TableAction.READ)
        assert check_action(db, tbl, user, TableAction.EDIT_RECORDS)
        assert check_action(db, tbl, user, TableAction.EDIT_SCHEMA)

    def test_user_not_in_workspace_returns_false(self, db, client, auth_headers):
        from cndb.plugins.accounts.models import User

        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_u"})
        wid = ws.json()["id"]
        client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_u"})
        tbl = db.query(DataTable).filter_by(workspace_id=wid).first()
        client.post(
            "/api/v1/accounts/auth/register",
            json={
                "username": "outsider",
                "email": "o@o.com",
                "password": "passw0rd",
            },
        )
        outsider = db.query(User).filter(User.username == "outsider").first()
        assert outsider is not None
        assert check_action(db, tbl, outsider, TableAction.READ) is False


# ---------- query.py ----------


class TestQueryCompile:
    def test_unknown_field_name_returns_none(self, db):
        from cndb.plugins.tables import query

        tbl = _make_table(db, 1, "t_q")
        result = query.compile_filters(
            tbl,
            Table("dummy", MetaData(), Column("id", Integer)),
            [{"field_name": "unknown", "op": "=", "value": "x"}],
        )
        assert result is None


# ---------- transfer.py ----------


class TestTransferLinkSerialization:
    def test_serialize_link_dict_list(self):
        from cndb.plugins.tables.transfer import _serialize_link_value

        val = [{"id": 1, "value": "a"}, {"id": 2, "value": "b"}]
        assert _serialize_link_value(val) == "1;2"

    def test_serialize_link_plain_value(self):
        from cndb.plugins.tables.transfer import _serialize_link_value

        assert _serialize_link_value("plain") == "plain"

    def test_export_csv_with_link_summary(self):
        from cndb.plugins.tables.transfer import export_rows_to_csv

        rows = [
            {"name": "row1", "links": [{"id": 1, "value": "a"}, {"id": 2, "value": "b"}]},
            {"name": "row2", "links": []},
        ]
        csv_text = export_rows_to_csv(rows)
        assert "name,links" in csv_text
        assert "1;2" in csv_text

    def test_parse_link_empty_string(self, db, client, auth_headers):
        from cndb.plugins.tables.transfer import _parse_link_import_value

        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_tf1"})
        wid = ws.json()["id"]
        tb = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "targets"})
        tid_b = tb.json()["id"]
        ta = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "sources"})
        tid_a = ta.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_a}/fields",
            headers=auth_headers,
            json={"name": "name", "field_type": "text", "order": 0},
        )
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_a}/fields",
            headers=auth_headers,
            json={
                "name": "link_to_target",
                "field_type": "link",
                "order": 1,
                "config": {"target_table_id": tid_b, "multiple": True},
            },
        )
        tbl = db.query(DataTable).filter_by(id=tid_a).first()
        result = _parse_link_import_value(tbl, {"name": "x", "link_to_target": ""})
        assert result["link_to_target"] == []
        result = _parse_link_import_value(tbl, {"name": "y", "link_to_target": "5"})
        assert result["link_to_target"] == [5]
        result = _parse_link_import_value(tbl, {"name": "z", "link_to_target": "1;2;3"})
        assert result["link_to_target"] == [1, 2, 3]
        result = _parse_link_import_value(tbl, {"name": "w", "link_to_target": [1, 2]})
        assert result["link_to_target"] == [1, 2]
        result = _parse_link_import_value(tbl, {"name": "q", "link_to_target": None})
        assert result["link_to_target"] is None

    def test_parse_link_invalid_raises(self, db, client, auth_headers):
        from cndb.plugins.tables.transfer import _parse_link_import_value

        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_tf2"})
        wid = ws.json()["id"]
        tb = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "targets2"})
        tid_b = tb.json()["id"]
        ta = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "sources2"})
        tid_a = ta.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_a}/fields",
            headers=auth_headers,
            json={"name": "name", "field_type": "text", "order": 0},
        )
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_a}/fields",
            headers=auth_headers,
            json={
                "name": "link_to_target",
                "field_type": "link",
                "order": 1,
                "config": {"target_table_id": tid_b, "multiple": True},
            },
        )
        tbl = db.query(DataTable).filter_by(id=tid_a).first()
        with pytest.raises(ValueError):
            _parse_link_import_value(tbl, {"name": "bad", "link_to_target": "abc;xyz"})

    def test_import_xlsx_empty(self, db_engine):
        from openpyxl import Workbook

        from cndb.plugins.tables.transfer import import_rows_from_xlsx

        wb = Workbook()
        ws_wb = wb.active
        assert ws_wb is not None
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        tbl = DataTable(name="t_empty_xlsx", db_table_name="t_empty_xlsx777")
        result = import_rows_from_xlsx(db_engine, tbl, buf.getvalue(), db=None)
        assert result == []
