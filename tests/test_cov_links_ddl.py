"""Coverage: links.py + ddl.py + records.py missing lines."""

from __future__ import annotations

from cndb.plugins.tables import ddl, links
from cndb.plugins.tables.models import DataField, DataTable


def _make_table(db, ws_id, name="t_x"):
    tbl = DataTable(workspace_id=ws_id, name=name)
    tbl.ensure_db_name()
    db.add(tbl)
    db.commit()
    db.refresh(tbl)
    return tbl


class TestDDLBuildSaTable:
    def test_skip_trashed_field(self, db_engine, db):
        from sqlalchemy import MetaData

        tbl = _make_table(db, 1, "t_ddl1")
        f1 = DataField(table_id=tbl.id, name="visible", field_type="text", order=0)
        f1.ensure_db_name()
        f2 = DataField(table_id=tbl.id, name="hidden", field_type="text", order=1, trashed=True)
        f2.ensure_db_name()
        db.add_all([f1, f2])
        db.commit()
        db.refresh(tbl)
        md = MetaData()
        sa_table = ddl.build_sa_table(md, tbl, include_trashed=False)
        col_names = {c.name for c in sa_table.columns}
        assert f1.db_column_name in col_names
        assert f2.db_column_name not in col_names

    def test_skip_unknown_field_type(self, db_engine, db):
        from sqlalchemy import MetaData

        tbl = _make_table(db, 1, "t_ddl2")
        f1 = DataField(table_id=tbl.id, name="good", field_type="text", order=0)
        f1.ensure_db_name()
        f2 = DataField(table_id=tbl.id, name="bad", field_type="weird_xyz_type", order=1)
        f2.ensure_db_name()
        db.add_all([f1, f2])
        db.commit()
        db.refresh(tbl)
        md = MetaData()
        sa_table = ddl.build_sa_table(md, tbl)
        col_names = {c.name for c in sa_table.columns}
        assert f1.db_column_name in col_names
        assert f2.db_column_name not in col_names

    def test_skip_link_field_no_physical_column(self, db_engine, db):
        from sqlalchemy import MetaData

        tbl = _make_table(db, 1, "t_ddl3")
        f1 = DataField(table_id=tbl.id, name="name", field_type="text", order=0)
        f1.ensure_db_name()
        f2 = DataField(
            table_id=tbl.id,
            name="rel",
            field_type="link",
            order=1,
            config={"target_table_id": 1, "multiple": True},
        )
        f2.ensure_db_name()
        db.add_all([f1, f2])
        db.commit()
        db.refresh(tbl)
        md = MetaData()
        sa_table = ddl.build_sa_table(md, tbl)
        col_names = {c.name for c in sa_table.columns}
        assert f1.db_column_name in col_names
        assert f2.db_column_name not in col_names

    def test_unknown_field_type_graceful(self, db_engine, db):
        tbl = _make_table(db, 1, "t_ddl4")
        f = DataField(table_id=tbl.id, name="weird", field_type="does_not_exist_xyz", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        ddl.create_table(db_engine, tbl)
        assert ddl.table_exists(db_engine, tbl.db_table_name)

    def test_get_engine_sqlite(self):
        eng = ddl.get_engine("sqlite:///:memory:")
        assert eng is not None
        eng.dispose()


def _create_link_scenario(client, auth_headers):
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_links"})
    wid = ws.json()["id"]
    tb = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "targets"})
    tid_b = tb.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_b}/fields",
        headers=auth_headers,
        json={"name": "name", "field_type": "text", "order": 0},
    )
    for _n in ["t1", "t2", "t3"]:
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_b}/records", headers=auth_headers, json={"values": {"name": _n}}
        )
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
    return wid, tid_b, tid_a


class TestLinksEdgeCases:
    def test_set_links_dedupes(self, db_engine, db, client, auth_headers):
        wid, _tid_b, tid_a = _create_link_scenario(client, auth_headers)
        ra = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_a}/records",
            headers=auth_headers,
            json={"values": {"name": "src", "link_to_target": [1, 1, 2]}},
        )
        row_id = ra.json()["id"]
        fa = db.query(DataField).filter_by(table_id=tid_a, name="link_to_target").first()
        assert fa is not None
        mapping = links.load_links(db_engine, fa, [row_id])
        assert mapping[row_id] == [1, 2]

    def test_clear_row_links_empty_ids(self, db_engine):
        tbl = DataTable(name="t_cl", db_table_name="t_cl_clearlinks999")
        assert links.clear_row_links(db_engine, tbl, []) is None

    def test_link_fields_helper(self, db_engine, db, client, auth_headers):
        _wid, _tid_b, tid_a = _create_link_scenario(client, auth_headers)
        tbl = db.query(DataTable).filter_by(id=tid_a).first()
        assert tbl is not None
        lfs = links.link_fields(tbl)
        assert len(lfs) == 1
        assert lfs[0].name == "link_to_target"
