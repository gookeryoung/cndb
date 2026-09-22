"""Coverage: remaining routers + records.py edge cases + ddl."""

from __future__ import annotations


class TestRecordsEdgeCases:
    def test_create_row_missing_required_field(self, client, auth_headers, db):
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_rec1"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_rec1"})
        tid = t.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "req_field", "field_type": "text", "order": 0, "required": True},
        )
        r = client.post(f"/api/v1/workspaces/{wid}/tables/{tid}/records", headers=auth_headers, json={"values": {}})
        assert r.status_code >= 400

    def test_get_row_not_found(self, client, auth_headers, db):
        """Get non-existent row -> 404."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_rec2"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_rec2"})
        tid = t.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "f", "field_type": "text", "order": 0},
        )
        r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/records/99999", headers=auth_headers)
        assert r.status_code == 404


class TestRoutersFields:
    def test_create_duplicate_field_name(self, client, auth_headers, db):
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_f1"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_f1"})
        tid = t.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "dup", "field_type": "text", "order": 0},
        )
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "dup", "field_type": "text", "order": 1},
        )
        assert r.status_code >= 400


class TestDDLMore:
    def test_create_table_idempotent(self, db_engine, db):
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core import ddl

        tbl = DataTable(workspace_id=1, name="t_idem")
        tbl.ensure_db_name()
        db.add(tbl)
        db.commit()
        db.refresh(tbl)
        f = DataField(table_id=tbl.id, name="name", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        ddl.create_table(db_engine, tbl)
        ddl.create_table(db_engine, tbl)
        assert ddl.table_exists(db_engine, tbl.db_table_name)

    def test_drop_column_link_field(self, db_engine, db):
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core import ddl

        tbl = DataTable(workspace_id=1, name="t_dc_link")
        tbl.ensure_db_name()
        db.add(tbl)
        db.commit()
        db.refresh(tbl)
        f = DataField(
            table_id=tbl.id,
            name="rel",
            field_type="link",
            order=0,
            config={"target_table_id": 1, "multiple": True},
        )
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        ddl.create_table(db_engine, tbl)
        assert ddl.table_exists(db_engine, f.link_table_name)
        ddl.drop_column(db_engine, tbl, f)
        assert not ddl.table_exists(db_engine, f.link_table_name)

    def test_add_column_link_field(self, db_engine, db):
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core import ddl

        tbl = DataTable(workspace_id=1, name="t_ac_link")
        tbl.ensure_db_name()
        db.add(tbl)
        db.commit()
        db.refresh(tbl)
        f1 = DataField(table_id=tbl.id, name="name", field_type="text", order=0)
        f1.ensure_db_name()
        db.add(f1)
        db.commit()
        db.refresh(tbl)
        ddl.create_table(db_engine, tbl)
        f2 = DataField(
            table_id=tbl.id,
            name="rel2",
            field_type="link",
            order=1,
            config={"target_table_id": 1, "multiple": True},
        )
        f2.ensure_db_name()
        db.add(f2)
        db.commit()
        ddl.add_column(db_engine, tbl, f2)
        assert ddl.table_exists(db_engine, f2.link_table_name)

    def test_drop_table_nonexistent(self, db_engine):
        from cndb.plugins.tables.services.core import ddl

        ddl.drop_table(db_engine, "nonexistent_table_xyz789")
