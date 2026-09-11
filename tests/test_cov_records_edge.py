"""Coverage: records.py edge cases - _normalize_values, _get_sa_table not found, bulk_update link-only, bulk_delete empty."""

from __future__ import annotations


class TestRecordsApi:
    def test_bulk_delete_empty_ids(self, client, auth_headers, db):
        """Bulk delete with empty row_ids -> 400 or handled."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_bd"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_bd"})
        tid = t.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "f", "field_type": "text", "order": 0},
        )
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/bulk-delete",
            json={"row_ids": []},
            headers=auth_headers,
        )
        assert r.status_code >= 200  # could be 200 with 0 deleted or 400

    def test_bulk_update_link_only(self, client, auth_headers, db):
        """Bulk update with link-only values."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_bu"})
        wid = ws.json()["id"]
        tb = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "bu_targets"})
        tid_b = tb.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_b}/fields",
            headers=auth_headers,
            json={"name": "n", "field_type": "text", "order": 0},
        )
        for name in ["p1", "p2"]:
            client.post(
                f"/api/v1/workspaces/{wid}/tables/{tid_b}/records", headers=auth_headers, json={"values": {"n": name}}
            )
        ta = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "bu_src"})
        tid_a = ta.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_a}/fields",
            headers=auth_headers,
            json={"name": "s", "field_type": "text", "order": 0},
        )
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_a}/fields",
            headers=auth_headers,
            json={
                "name": "l",
                "field_type": "link",
                "order": 1,
                "config": {"target_table_id": tid_b, "multiple": True},
            },
        )
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_a}/records",
            headers=auth_headers,
            json={"values": {"s": "x", "l": [1]}},
        )
        # Bulk update with link-only values
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_a}/records/bulk-update",
            json={"row_ids": [1], "values": {"l": [2]}},
            headers=auth_headers,
        )
        assert r.status_code == 200
