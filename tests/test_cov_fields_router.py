"""Coverage: routers/fields.py _validate_link_config bad config + nonexistent target + delete_field rollback."""

from __future__ import annotations


class TestLinkFieldValidation:
    def test_link_field_bad_config(self, client, auth_headers, db):
        """Link field with invalid config (bad target_table_id) -> 400."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_lf"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_lf"})
        tid = t.json()["id"]
        # Bad config: target_table_id does not exist
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={
                "name": "bad_link",
                "field_type": "link",
                "order": 0,
                "config": {"target_table_id": 99999, "multiple": True},
            },
        )
        assert r.status_code == 400

    def test_link_field_bad_config_format(self, client, auth_headers, db):
        """Link field with malformed config (missing required field) -> 400."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_lf2"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_lf2"})
        tid = t.json()["id"]
        # Missing target_table_id in config
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={
                "name": "bad_link2",
                "field_type": "link",
                "order": 0,
                "config": {"multiple": True},  # missing target_table_id
            },
        )
        assert r.status_code == 400

    def test_create_unknown_field_type(self, client, auth_headers, db):
        """Unknown field type -> 400."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_ut"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_ut"})
        tid = t.json()["id"]
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "f", "field_type": "nonexistent_type_xyz", "order": 0},
        )
        assert r.status_code == 400

    def test_delete_nonexistent_field(self, client, auth_headers, db):
        """Delete field that does not exist -> 404."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_df"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_df"})
        tid = t.json()["id"]
        r = client.delete(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields/99999",
            headers=auth_headers,
        )
        assert r.status_code == 404
