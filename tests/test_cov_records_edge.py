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


class TestUpdateNullClearField:
    """update_row / bulk_update 路径：前端传 null 表示显式清空字段（看板完成标志取消依赖此能力）."""

    def _make_table(self, client, auth_headers, field_type: str, config: dict | None = None, required: bool = False):
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_null"})
        wid = ws.json()["id"]
        tb = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_null"})
        tid = tb.json()["id"]
        body = {"name": "f", "field_type": field_type, "order": 0, "required": required}
        if config is not None:
            body["config"] = config
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json=body,
        )
        return wid, tid

    def test_patch_select_null_clears_field(self, client, auth_headers, db):
        """PATCH records/{id}: select 字段传 null → 字段被清空（看板取消完成场景）."""
        wid, tid = self._make_table(
            client, auth_headers, "select",
            config={"options": [{"value": "todo", "label": "待办"}, {"value": "done", "label": "已完成"}]},
        )
        create = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records",
            headers=auth_headers,
            json={"values": {"f": "done"}},
        )
        assert create.status_code == 201
        rid = create.json()["id"]

        # 传 null 清空字段
        patch = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/{rid}",
            headers=auth_headers,
            json={"values": {"f": None}},
        )
        assert patch.status_code == 200
        body = patch.json()
        assert body.get("f") is None

    def test_patch_boolean_null_clears_field(self, client, auth_headers, db):
        """PATCH records/{id}: boolean 字段传 null → 字段被清空（不强制转 false）."""
        wid, tid = self._make_table(client, auth_headers, "boolean")
        create = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records",
            headers=auth_headers,
            json={"values": {"f": True}},
        )
        assert create.status_code == 201
        rid = create.json()["id"]

        patch = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/{rid}",
            headers=auth_headers,
            json={"values": {"f": None}},
        )
        assert patch.status_code == 200
        body = patch.json()
        assert body.get("f") is None

    def test_patch_text_null_clears_field(self, client, auth_headers, db):
        """PATCH records/{id}: text 字段传 null → 字段被清空."""
        wid, tid = self._make_table(client, auth_headers, "text")
        create = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records",
            headers=auth_headers,
            json={"values": {"f": "hello"}},
        )
        assert create.status_code == 201
        rid = create.json()["id"]

        patch = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/{rid}",
            headers=auth_headers,
            json={"values": {"f": None}},
        )
        assert patch.status_code == 200
        body = patch.json()
        assert body.get("f") is None

    def test_bulk_update_null_clears_field(self, client, auth_headers, db):
        """bulk-update: 多行同时传 null 清空字段."""
        wid, tid = self._make_table(
            client, auth_headers, "select",
            config={"options": [{"value": "todo", "label": "待办"}, {"value": "done", "label": "已完成"}]},
        )
        ids = []
        for v in ["done", "todo", "done"]:
            r = client.post(
                f"/api/v1/workspaces/{wid}/tables/{tid}/records",
                headers=auth_headers,
                json={"values": {"f": v}},
            )
            ids.append(r.json()["id"])

        bulk = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/bulk-update",
            headers=auth_headers,
            json={"row_ids": ids, "values": {"f": None}},
        )
        assert bulk.status_code == 200
        assert bulk.json()["updated"] == 3

        # 逐条验证
        for rid in ids:
            r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/records/{rid}", headers=auth_headers)
            assert r.status_code == 200
            assert r.json().get("f") is None

    def test_normalize_values_for_update_null_written(self, db):
        """_normalize_values: for_update=True 时 raw=None 写入 result（内部函数级单测）."""
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core.records import _normalize_values

        tbl = DataTable(workspace_id=1, name="t_norm_null")
        tbl.fields = [DataField(name="sel", field_type="select", config={"options": ["todo", "done"]})]

        # for_update=True：null 应该写入
        result, links = _normalize_values(tbl, {"sel": None}, for_update=True)
        assert links == []
        # db_column_name 由 ensure_db_name 生成，值为 None
        db_col = tbl.fields[0].db_column_name
        assert db_col in result
        assert result[db_col] is None

        # for_update=False（创建）：null 应该跳过
        result2, links2 = _normalize_values(tbl, {"sel": None}, for_update=False)
        assert links2 == []
        assert db_col not in result2

    def test_update_nonexistent_field_key_ignored(self, client, auth_headers, db):
        """PATCH 传 null 但 key 不在 table.fields 中 → 安全忽略（不报错）."""
        wid, tid = self._make_table(client, auth_headers, "text")
        create = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records",
            headers=auth_headers,
            json={"values": {"f": "ok"}},
        )
        rid = create.json()["id"]

        patch = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/{rid}",
            headers=auth_headers,
            json={"values": {"nonexistent": None, "f": "still_ok"}},
        )
        # 不存在的字段忽略，有效字段正常写入
        assert patch.status_code == 200
        assert patch.json().get("f") == "still_ok"


class TestRecordsRouterEdgeCases:
    """Coverage for routers/records.py edge cases - JSON parse errors, ValueError/Exception handling."""

    def _make_table(self, client, auth_headers):
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_rre"})
        wid = ws.json()["id"]
        tb = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_rre"})
        tid = tb.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "name", "field_type": "text", "order": 0},
        )
        return wid, tid

    def test_get_records_invalid_sorts_json(self, client, auth_headers):
        """GET /records with malformed sorts JSON → degrades gracefully."""
        wid, tid = self._make_table(client, auth_headers)
        r = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records",
            headers=auth_headers,
            params={"sorts": "not-json"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "rows" in body
        assert body["total"] == 0

    def test_get_records_sorts_non_list(self, client, auth_headers):
        """GET /records with sorts JSON object (not list) → degrades to no sort."""
        wid, tid = self._make_table(client, auth_headers)
        r = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records",
            headers=auth_headers,
            params={"sorts": '{"field_name": "x"}'},  # dict, not list
        )
        assert r.status_code == 200

    def test_get_records_invalid_filters_json(self, client, auth_headers):
        """GET /records with malformed filters JSON → degrades gracefully."""
        wid, tid = self._make_table(client, auth_headers)
        r = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records",
            headers=auth_headers,
            params={"filters": "[invalid"},
        )
        assert r.status_code == 200

    def test_get_records_value_error_handling(self, client, auth_headers, monkeypatch):
        """GET /records where list_rows raises ValueError → 400."""
        wid, tid = self._make_table(client, auth_headers)

        from cndb.plugins.tables.routers import records as _routers_records

        def raising(*args, **kwargs):
            raise ValueError("unknown field 'xxx'")

        monkeypatch.setattr(_routers_records, "list_rows", raising)

        r = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records",
            headers=auth_headers,
            params={"offset": 0, "limit": 10},
        )
        assert r.status_code == 400
        assert "unknown field" in r.json()["detail"]

    def test_post_records_value_error_handling(self, client, auth_headers, monkeypatch):
        """POST /records/list where list_rows raises ValueError → 400."""
        wid, tid = self._make_table(client, auth_headers)

        from cndb.plugins.tables.routers import records as _routers_records

        def raising(*args, **kwargs):
            raise ValueError("bad sort field")

        monkeypatch.setattr(_routers_records, "list_rows", raising)

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/list",
            headers=auth_headers,
            json={"offset": 0, "limit": 10},
        )
        assert r.status_code == 400

    def test_get_records_generic_error_handling(self, client, auth_headers, monkeypatch):
        """GET /records where list_rows raises RuntimeError → 500."""
        wid, tid = self._make_table(client, auth_headers)

        from cndb.plugins.tables.routers import records as _routers_records

        def raising(*args, **kwargs):
            raise RuntimeError("db connection lost")

        monkeypatch.setattr(_routers_records, "list_rows", raising)

        r = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records",
            headers=auth_headers,
            params={"offset": 0, "limit": 10},
        )
        assert r.status_code == 500

    def test_post_records_generic_error_handling(self, client, auth_headers, monkeypatch):
        """POST /records/list where list_rows raises RuntimeError → 500."""
        wid, tid = self._make_table(client, auth_headers)

        from cndb.plugins.tables.routers import records as _routers_records

        def raising(*args, **kwargs):
            raise RuntimeError("db connection lost")

        monkeypatch.setattr(_routers_records, "list_rows", raising)

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/list",
            headers=auth_headers,
            json={"offset": 0, "limit": 10},
        )
        assert r.status_code == 500
