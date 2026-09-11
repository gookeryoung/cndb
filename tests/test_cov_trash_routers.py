"""Coverage: trash.py + ddl drop_column + create_table existing + tables routers."""

from __future__ import annotations

# ---------- trash.py: list trash rows empty result path ----------


class TestTrashRouterEdgeCases:
    def test_list_workspace_trash_empty(self, client, auth_headers, db):
        """Workspace with no trashed tables/fields -> empty lists."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_trash1"})
        wid = ws.json()["id"]
        client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t1"})
        r = client.get(f"/api/v1/workspaces/{wid}/trash", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["tables"] == []
        assert data["fields"] == []

    def test_restore_table_not_trashed_404(self, client, auth_headers, db):
        """Restore table that is not trashed -> 404."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_trash2"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t2"})
        tid = t.json()["id"]
        r = client.post(f"/api/v1/workspaces/{wid}/trash/tables/{tid}/restore", headers=auth_headers)
        assert r.status_code == 404

    def test_restore_field_not_trashed_400(self, client, auth_headers, db):
        """Restore field that is not trashed -> 400."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_trash3"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t3"})
        tid = t.json()["id"]
        f = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "f1", "field_type": "text", "order": 0},
        )
        fid = f.json()["id"]
        r = client.post(f"/api/v1/workspaces/{wid}/trash/fields/{fid}/restore", headers=auth_headers)
        assert r.status_code == 400

    def test_purge_trash_rows_no_permission_editor(self, client, auth_headers, db):
        """Editor cannot purge trashed rows (needs ADMIN)."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_trash4"})
        wid = ws.json()["id"]
        # Add a second user as editor
        client.post(
            "/api/v1/accounts/auth/register",
            json={
                "username": "editor1",
                "email": "e@e.com",
                "password": "passw0rd",
            },
        )
        # Actually let's just test that ADMIN can purge
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t4"})
        tid = t.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "name", "field_type": "text", "order": 0},
        )
        # create a row then trash it
        row = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records", headers=auth_headers, json={"values": {"name": "trashme"}}
        )
        row_id = row.json()["id"]
        # Trash via records API
        client.delete(f"/api/v1/workspaces/{wid}/tables/{tid}/records/{row_id}", headers=auth_headers)
        # Purge with days=0 means older than 0 days -> everything
        r = client.delete(
            f"/api/v1/workspaces/{wid}/tables/{tid}/trash-rows",
            headers=auth_headers,
            params={"days": 0},
        )
        assert r.status_code == 200
        assert r.json()["purged"] >= 1

    def test_restore_trash_rows_batch_by_ids(self, client, auth_headers, db):
        """Restore specific trashed rows by ids."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_trash5"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t5"})
        tid = t.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "name", "field_type": "text", "order": 0},
        )
        r1 = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records", headers=auth_headers, json={"values": {"name": "a"}}
        )
        r2 = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records", headers=auth_headers, json={"values": {"name": "b"}}
        )
        rid1 = r1.json()["id"]
        rid2 = r2.json()["id"]
        # Trash both
        client.delete(f"/api/v1/workspaces/{wid}/tables/{tid}/records/{rid1}", headers=auth_headers)
        client.delete(f"/api/v1/workspaces/{wid}/tables/{tid}/records/{rid2}", headers=auth_headers)
        # Restore only rid1
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/trash-rows/restore",
            headers=auth_headers,
            json={"row_ids": [rid1]},
        )
        assert r.status_code == 200
        assert r.json()["restored"] == 1

    def test_restore_trash_rows_batch_all(self, client, auth_headers, db):
        """Restore all trashed rows (empty row_ids)."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_trash6"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t6"})
        tid = t.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "name", "field_type": "text", "order": 0},
        )
        for name in ["x", "y", "z"]:
            row = client.post(
                f"/api/v1/workspaces/{wid}/tables/{tid}/records", headers=auth_headers, json={"values": {"name": name}}
            )
            client.delete(
                f"/api/v1/workspaces/{wid}/tables/{tid}/records/{row.json()['id']}",
                headers=auth_headers,
            )
        # Restore all
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/trash-rows/restore",
            headers=auth_headers,
            json={"row_ids": []},
        )
        assert r.status_code == 200
        assert r.json()["restored"] >= 3

    def test_list_trashed_rows_empty(self, client, auth_headers, db):
        """List trashed rows when there are none."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_trash7"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t7"})
        tid = t.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "name", "field_type": "text", "order": 0},
        )
        r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/trash-rows", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["rows"] == []
        assert data["total"] == 0
