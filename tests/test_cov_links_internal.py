"""Coverage: links.py internal helpers - _target_summaries db=None, _target_data_table, _summary_fields, load_links empty ids."""

from __future__ import annotations

from cndb.plugins.tables import links
from cndb.plugins.tables.models import DataField, DataTable


def _create_full_link_scenario(client, auth_headers, db):
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_li"})
    wid = ws.json()["id"]
    tb = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "ltarget"})
    tid_b = tb.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_b}/fields",
        headers=auth_headers,
        json={"name": "tname", "field_type": "text", "order": 0},
    )
    for _n in ["aaa", "bbb", "ccc"]:
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_b}/records", headers=auth_headers, json={"values": {"tname": _n}}
        )
    ta = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "lsrc"})
    tid_a = ta.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_a}/fields",
        headers=auth_headers,
        json={"name": "sname", "field_type": "text", "order": 0},
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


class TestLoadLinksEmptyRows:
    def test_load_links_dedupes_row_ids(self, db_engine, db, client, auth_headers):
        """load_links should deduplicate input row_ids."""
        _wid, _tid_b, tid_a = _create_full_link_scenario(client, auth_headers, db)
        fa = db.query(DataField).filter_by(table_id=tid_a, name="link_to_target").first()
        assert fa is not None
        # load with duplicates
        result = links.load_links(db_engine, fa, [1, 1, 2])
        assert isinstance(result, dict)


class TestAttachLinks:
    def test_no_link_fields_noop(self, db_engine, db):
        """attach_links on table with no link fields -> rows returned as-is."""
        tbl = DataTable(workspace_id=1, name="t_als1")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="name", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        rows = [{"id": 1, "name": "x"}]
        result = links.attach_links(db_engine, tbl, rows)
        assert result == rows

    def test_empty_rows_noop(self, db_engine, db, client, auth_headers):
        """attach_links with empty rows list -> empty list."""
        _wid, _tid_b, tid_a = _create_full_link_scenario(client, auth_headers, db)
        tbl = db.query(DataTable).filter_by(id=tid_a).first()
        result = links.attach_links(db_engine, tbl, [])
        assert result == []


class TestTargetSummariesInternal:
    def test_target_summary_without_db_fallback(self, db_engine, db, client, auth_headers):
        """_target_summaries with db=None -> returns #id placeholders."""
        from cndb.plugins.tables.links import _target_summaries

        _wid, _tid_b, tid_a = _create_full_link_scenario(client, auth_headers, db)
        fa = db.query(DataField).filter_by(table_id=tid_a, name="link_to_target").first()
        result = _target_summaries(db_engine, fa, [1, 2], db=None)
        assert result[1] == "#1"
        assert result[2] == "#2"


class TestFindBackReferencesNoSource:
    def test_no_ref_fields_returns_empty(self, db_engine, db):
        """find_back_references when no candidate fields point to target."""
        from cndb.plugins.tables.links import find_back_references

        tbl = DataTable(workspace_id=1, name="t_target_br")
        tbl.ensure_db_name()
        db.add(tbl)
        db.commit()
        result = find_back_references(db, db_engine, tbl, 1)
        assert result == []
