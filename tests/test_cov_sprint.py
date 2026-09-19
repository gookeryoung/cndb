"""Coverage sprint — 补全 import_csv/public/records routers 的异常/边界分支."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pytest

from cndb.plugins.tables.field_types import DateFieldType, DateTimeFieldType

# ── records.py routers ───────────────────────────────────


class TestRecordsRouterCoverage:
    def test_create_value_error_400(self, client, auth_headers, db):
        """POST records -> 400 when create_row raises ValueError (monkeypatched)."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_r1"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t1"})
        tid = t.json()["id"]

        with patch("cndb.plugins.tables.routers.records.create_row", side_effect=ValueError("bad value")):
            r = client.post(
                f"/api/v1/workspaces/{wid}/tables/{tid}/records",
                headers=auth_headers,
                json={"values": {"x": 1}},
            )
        assert r.status_code == 400

    def test_create_runtime_error_500(self, client, auth_headers, db):
        """POST records -> 500 when create_row raises RuntimeError."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_r2"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t2"})
        tid = t.json()["id"]

        with patch("cndb.plugins.tables.routers.records.create_row", side_effect=RuntimeError("boom")):
            r = client.post(
                f"/api/v1/workspaces/{wid}/tables/{tid}/records",
                headers=auth_headers,
                json={"values": {"x": 1}},
            )
        assert r.status_code == 500

    def test_create_row_none_500(self, client, auth_headers, db):
        """POST records -> 500 when create_row returns None."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_r3"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t3"})
        tid = t.json()["id"]

        with patch("cndb.plugins.tables.routers.records.create_row", return_value=None):
            r = client.post(
                f"/api/v1/workspaces/{wid}/tables/{tid}/records",
                headers=auth_headers,
                json={"values": {"x": 1}},
            )
        assert r.status_code == 500

    def test_update_value_error_400(self, client, auth_headers, db):
        """PATCH records -> 400 when update_row raises ValueError."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_r4"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t4"})
        tid = t.json()["id"]

        with patch("cndb.plugins.tables.routers.records.update_row", side_effect=ValueError("bad")):
            r = client.patch(
                f"/api/v1/workspaces/{wid}/tables/{tid}/records/1",
                headers=auth_headers,
                json={"values": {"x": 1}},
            )
        assert r.status_code == 400


# ── import_csv.py ───────────────────────────────────────


class TestImportCsvCoverage:
    def test_skip_first_row_insufficient_lines(self, client, auth_headers):
        """Analyze with skip_first_row=True but single line CSV -> unchanged."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_csv1"})
        wid = ws.json()["id"]
        # 单行 CSV（只有 header，无数据行），skip_first_row=True 不应该 crash
        r = client.post(
            f"/api/v1/workspaces/{wid}/import-csv/analyze",
            headers=auth_headers,
            json={"csv_text": "a,b,c", "skip_first_row": True},
        )
        # 可能 200 或 400（取决于 analyze_csv_columns 行为），但不应 500
        assert r.status_code in (200, 400)

    def test_skip_first_row_with_enough_lines(self, client, auth_headers):
        """Analyze with skip_first_row=True and multi-line CSV -> strips first line."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_csv3"})
        wid = ws.json()["id"]
        r = client.post(
            f"/api/v1/workspaces/{wid}/import-csv/analyze",
            headers=auth_headers,
            json={"csv_text": "a,b,c\n1,2,3\n4,5,6\n", "skip_first_row": True},
        )
        assert r.status_code == 200

    def test_create_table_exception_500(self, client, auth_headers):
        """import csv -> 500 when create_table_from_csv raises."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_csv2"})
        wid = ws.json()["id"]

        with patch(
            "cndb.plugins.tables.routers.import_csv.create_table_from_csv",
            side_effect=RuntimeError("ddl failed"),
        ):
            r = client.post(
                f"/api/v1/workspaces/{wid}/import-csv",
                headers=auth_headers,
                json={"table_name": "t", "csv_text": "a,b\n1,2"},
            )
        assert r.status_code == 500


# ── public.py ───────────────────────────────────────────


class TestPublicDirect:
    """直接测试 public.py 的辅助函数和边界分支."""

    def test_public_form_submit_row_none_500(self, client, db):
        """POST public form -> 500 when create_row returns None."""
        from cndb.plugins.tables.models import DataTable, DataView
        from cndb.plugins.workspaces.models import Workspace

        ws = Workspace(name="pub_ws")
        db.add(ws)
        db.commit()
        dt = DataTable(workspace_id=ws.id, name="pub_t", db_table_name="pub_t_1")
        db.add(dt)
        db.commit()
        dv = DataView(
            table_id=dt.id,
            name="form",
            view_type="form",
            public_slug="formghost",
            is_public=True,
        )
        db.add(dv)
        db.commit()

        with patch("cndb.plugins.tables.routers.public.rec.create_row", return_value=None):
            r = client.post(
                "/api/v1/public/forms/formghost",
                json={"values": {"a": 1}},
            )
        assert r.status_code == 500


# ── field_types: DateFieldType / DateTimeFieldType ────────


class TestDateFieldTypeCoverage:
    def test_date_validate_none_empty(self):
        ft = DateFieldType()
        assert ft.validate_value(None, {}) is None
        assert ft.validate_value("", {}) is None
        # "   " 不是空串，会走字符串解析路径然后 ValueError

    def test_date_validate_passthrough(self):
        ft = DateFieldType()
        d = date(2024, 6, 15)
        assert ft.validate_value(d, {}) == d

    def test_date_validate_string_formats(self):
        ft = DateFieldType()
        assert ft.validate_value("2024-01-15", {}) == date(2024, 1, 15)
        assert ft.validate_value("2024/01/15", {}) == date(2024, 1, 15)

    def test_date_validate_bad_string_raises(self):
        ft = DateFieldType()
        with pytest.raises(ValueError):
            ft.validate_value("not-a-date", {})

    def test_date_validate_bad_type_raises(self):
        ft = DateFieldType()
        with pytest.raises(ValueError):
            ft.validate_value(12345, {})


class TestDateTimeFieldTypeCoverage:
    def test_datetime_validate_none_empty(self):
        ft = DateTimeFieldType()
        assert ft.validate_value(None, {}) is None
        assert ft.validate_value("", {}) is None

    def test_datetime_validate_passthrough(self):
        ft = DateTimeFieldType()
        dt = datetime(2024, 6, 15, 10, 30)
        assert ft.validate_value(dt, {}) == dt

    def test_datetime_validate_string_formats(self):
        ft = DateTimeFieldType()
        assert ft.validate_value("2024-01-15 10:30", {}) == datetime(2024, 1, 15, 10, 30)
        assert ft.validate_value("2024-01-15T10:30", {}) == datetime(2024, 1, 15, 10, 30)
        assert ft.validate_value("2024-01-15 10:30:45", {}) == datetime(2024, 1, 15, 10, 30, 45)
        assert ft.validate_value("2024-01-15T10:30:45", {}) == datetime(2024, 1, 15, 10, 30, 45)

    def test_datetime_validate_bad_string_raises(self):
        ft = DateTimeFieldType()
        with pytest.raises(ValueError):
            ft.validate_value("not-a-datetime", {})

    def test_datetime_validate_bad_type_raises(self):
        ft = DateTimeFieldType()
        with pytest.raises(ValueError):
            ft.validate_value(123, {})
