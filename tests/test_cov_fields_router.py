"""Coverage: routers/fields.py 分支覆盖."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException


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


# ── fields.py 剩余分支覆盖 ────────────────────────────


class TestFieldsRouterRemaining:
    def test_validate_field_config_unknown_type(self, db):
        """_validate_field_config 遇到未知 field_type -> 400 (覆盖 line 30)."""
        from cndb.plugins.tables.field_types import default_registry
        from cndb.plugins.tables.routers.fields import _validate_field_config

        with patch.object(default_registry, "get", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                _validate_field_config("ghost_type", {}, db)
            assert exc_info.value.status_code == 400
            assert "未知字段类型" in exc_info.value.detail

    def test_create_field_add_column_failure_rollback(self, client, auth_headers, db):
        """create_field 时 add_column 抛异常 -> 500 (覆盖 line 95-97)."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_acf"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_acf"})
        tid = t.json()["id"]

        # patch 目标是 fields 模块里已经 import 的 add_column
        with patch("cndb.plugins.tables.routers.fields.add_column", side_effect=RuntimeError("disk full")):
            r = client.post(
                f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
                headers=auth_headers,
                json={"name": "bad_col", "field_type": "text", "order": 0},
            )
        assert r.status_code == 500
        assert "物理加列失败" in r.json()["detail"]

    def test_delete_field_drop_column_failure_rollback(self, client, auth_headers, db):
        """delete_field 时 drop_column 抛异常 -> 500 + trashed 回滚 (覆盖 line 161-164)."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_dcf"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_dcf"})
        tid = t.json()["id"]
        # 先正常建个字段
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "rollback_col", "field_type": "text", "order": 0},
        )
        assert r.status_code == 201
        fid = r.json()["id"]

        # 删列失败时应回滚 trashed=True
        with patch("cndb.plugins.tables.routers.fields.drop_column", side_effect=RuntimeError("cannot drop")):
            r = client.delete(
                f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}",
                headers=auth_headers,
            )
        assert r.status_code == 500
        assert "物理删列失败" in r.json()["detail"]

        # 确认 trashed 已被回滚为 False
        fields = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields?include_trashed=true",
            headers=auth_headers,
        )
        target = next(f for f in fields.json() if f["id"] == fid)
        assert target["trashed"] is False
