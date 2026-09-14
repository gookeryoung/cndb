"""import-api config/validate 和 config 批量建表端点测试 — 覆盖率补全."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def ws_with_auth(client, db):
    u = User(username="imp_api", nickname="API")
    u.set_password("passw0rd")
    db.add(u)
    db.flush()
    ws = Workspace(name="ImpWS", created_by_id=u.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
    db.commit()
    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": "imp_api", "password": "passw0rd"},
    )
    token = r.json()["access_token"]
    return ws.id, {"Authorization": f"Bearer {token}"}


# ── POST /import-api/config/validate ─────────────────


class TestApiConfigValidate:
    def test_validate_ok(self, client, ws_with_auth):
        ws_id, auth = ws_with_auth
        config_json = json.dumps(
            {
                "tables": [
                    {
                        "table_name": "股票行情",
                        "fetch": {
                            "url": "https://qt.gtimg.cn/q=sh600519",
                            "method": "GET",
                            "response_handler": "tencent_stock",
                            "encoding": "gbk",
                            "query_interval": 10,
                        },
                    },
                ]
            }
        )
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-api/config/validate",
            json={"config_json": config_json},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["valid"] is True
        assert data["table_count"] == 1
        assert data["tables"][0]["table_name"] == "股票行情"

    def test_validate_invalid_config(self, client, ws_with_auth):
        ws_id, auth = ws_with_auth
        # 顶层不是 dict
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-api/config/validate",
            json={"config_json": json.dumps([1, 2, 3])},
            headers=auth,
        )
        assert r.status_code == 400

    def test_validate_empty_tables_invalid(self, client, ws_with_auth):
        # 空 tables 数组 → ApiConfigError
        ws_id, auth = ws_with_auth
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-api/config/validate",
            json={"config_json": json.dumps({"tables": []})},
            headers=auth,
        )
        assert r.status_code == 400

    def test_validate_unauthorized(self, client, ws_with_auth):
        ws_id, _auth = ws_with_auth
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-api/config/validate",
            json={"config_json": "{}"},
        )
        assert r.status_code in (401, 403)

    def test_validate_not_viewer(self, client, db):
        # 工作区不存在
        u = User(username="imp_nw", nickname="NW")
        u.set_password("p1")
        db.add(u)
        db.commit()
        r = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": "imp_nw", "password": "p1"},
        )
        token = r.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        r = client.post(
            "/api/v1/workspaces/99999/import-api/config/validate",
            json={"config_json": "{}"},
            headers=auth,
        )
        assert r.status_code == 404


# ── POST /import-api/config（批量建表）────────────────


def _mock_api_fetch_response(status: int, body: dict | list):
    resp = MagicMock()
    resp.status_code = status
    raw = json.dumps(body).encode()
    resp.content = raw
    resp.text = raw.decode()
    resp.headers = {"content-type": "application/json"}
    client = MagicMock()
    client.request.return_value = resp
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


class TestApiConfigImport:
    def test_config_import_success(self, client, ws_with_auth):
        ws_id, auth = ws_with_auth
        config_json = json.dumps(
            {
                "tables": [
                    {
                        "table_name": "Config表A",
                        "fetch": {
                            "url": "https://api.example.com/data",
                            "method": "GET",
                            "response_handler": "json",
                        },
                    },
                ]
            }
        )
        mock_client = _mock_api_fetch_response(
            200, [{"name": "A", "value": 1}, {"name": "B", "value": 2}]
        )
        with patch("httpx2.Client", return_value=mock_client):
            r = client.post(
                f"/api/v1/workspaces/{ws_id}/import-api/config",
                json={"config_json": config_json},
                headers=auth,
            )
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["success_count"] >= 1
            assert data["stopped_on_error"] is False

    def test_config_import_invalid_config_json(self, client, ws_with_auth):
        ws_id, auth = ws_with_auth
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-api/config",
            json={"config_json": "not-valid-config-json"},
            headers=auth,
        )
        assert r.status_code == 400

    def test_config_import_stop_on_error(self, client, ws_with_auth):
        """stop_on_error=True 遇到第一个失败就停止."""
        ws_id, auth = ws_with_auth
        config_json = json.dumps(
            {
                "tables": [
                    {"table_name": "坏表", "fetch": {"url": "https://x.com"}},
                    {"table_name": "好表", "fetch": {"url": "https://x.com"}},
                ]
            }
        )
        mock_client = _mock_api_fetch_response(200, [{"x": 1}])
        call_count = [0]

        def _patched_ingest(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("第一个表失败")
            return [{"table_name": "好表", "table_id": 1}]

        with patch(
            "cndb.plugins.tables.routers.import_api.ingest_tables_from_config",
            side_effect=_patched_ingest,
        ):
            with patch("httpx2.Client", return_value=mock_client):
                r = client.post(
                    f"/api/v1/workspaces/{ws_id}/import-api/config",
                    json={"config_json": config_json, "stop_on_error": True},
                    headers=auth,
                )
                assert r.status_code == 200, r.text
                data = r.json()
                assert data["fail_count"] >= 1
                assert data["stopped_on_error"] is True
                # 只尝试了第一个表
                assert call_count[0] == 1

    def test_config_import_continue_on_error(self, client, ws_with_auth):
        """stop_on_error=False 遇到失败继续."""
        ws_id, auth = ws_with_auth
        config_json = json.dumps(
            {
                "tables": [
                    {"table_name": "坏表2", "fetch": {"url": "https://x.com"}},
                    {"table_name": "好表2", "fetch": {"url": "https://x.com"}},
                ]
            }
        )
        mock_client = _mock_api_fetch_response(200, [{"x": 1}])
        call_count = [0]

        def _patched_ingest(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("第一个表失败")
            return [{"table_name": "好表2", "table_id": 2}]

        with patch(
            "cndb.plugins.tables.routers.import_api.ingest_tables_from_config",
            side_effect=_patched_ingest,
        ):
            with patch("httpx2.Client", return_value=mock_client):
                r = client.post(
                    f"/api/v1/workspaces/{ws_id}/import-api/config",
                    json={"config_json": config_json, "stop_on_error": False},
                    headers=auth,
                )
                assert r.status_code == 200, r.text
                data = r.json()
                assert data["fail_count"] >= 1
                assert data["stopped_on_error"] is False
                # 两个表都尝试了
                assert call_count[0] == 2

    def test_config_import_unauthorized(self, client, ws_with_auth):
        ws_id, _auth = ws_with_auth
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-api/config",
            json={"config_json": "{}"},
        )
        assert r.status_code in (401, 403)


# ── api_analyze 异常分支补充 ────────────────────────────


class TestApiAnalyzeExceptions:
    def test_analyze_fetch_exception(self, client, ws_with_auth):
        ws_id, auth = ws_with_auth
        mock_client = MagicMock()
        mock_client.request.side_effect = ConnectionError("connection refused")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        with patch("httpx2.Client", return_value=mock_client):
            r = client.post(
                f"/api/v1/workspaces/{ws_id}/import-api/analyze",
                json={"url": "https://x.com/api"},
                headers=auth,
            )
            assert r.status_code == 502

    def test_analyze_empty_response(self, client, ws_with_auth):
        ws_id, auth = ws_with_auth
        mock_client = _mock_api_fetch_response(200, [])
        with patch("httpx2.Client", return_value=mock_client):
            r = client.post(
                f"/api/v1/workspaces/{ws_id}/import-api/analyze",
                json={"url": "https://x.com/api"},
                headers=auth,
            )
            assert r.status_code == 400
            assert "未返回" in r.json()["detail"]


# ── api_import_create_table 异常分支 ────────────────────


class TestApiImportCreateTableExceptions:
    def test_import_create_value_error(self, client, ws_with_auth):
        ws_id, auth = ws_with_auth
        with patch(
            "cndb.plugins.tables.transfer.ingest_from_api",
            side_effect=ValueError("bad url"),
        ):
            r = client.post(
                f"/api/v1/workspaces/{ws_id}/import-api",
                json={"url": "https://x.com", "table_name": "X"},
                headers=auth,
            )
            assert r.status_code == 400

    def test_import_create_general_exception(self, client, ws_with_auth):
        ws_id, auth = ws_with_auth
        with patch(
            "cndb.plugins.tables.transfer.ingest_from_api",
            side_effect=RuntimeError("boom"),
        ):
            r = client.post(
                f"/api/v1/workspaces/{ws_id}/import-api",
                json={"url": "https://x.com", "table_name": "X"},
                headers=auth,
            )
            assert r.status_code == 500


# ── api_import_append 异常分支 ──────────────────────────


class TestApiImportAppendExceptions:
    def test_append_fetch_exception(self, client, ws_with_auth, db_engine, db):
        ws_id, auth = ws_with_auth

        # 先建表
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-csv",
            json={"table_name": "TAPP", "csv_text": "a,b\n1,2\n"},
            headers=auth,
        )
        assert r.status_code == 200
        table_id = r.json()["table_id"]

        # mock 抓取异常
        mock_client = MagicMock()
        mock_client.request.side_effect = ConnectionError("network down")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        with patch("httpx2.Client", return_value=mock_client):
            r = client.post(
                f"/api/v1/workspaces/{ws_id}/tables/{table_id}/import-api",
                json={"url": "https://x.com"},
                headers=auth,
            )
            assert r.status_code == 502

    def test_append_empty_response(self, client, ws_with_auth, db_engine, db):
        ws_id, auth = ws_with_auth

        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-csv",
            json={"table_name": "TAPP2", "csv_text": "a,b\n1,2\n"},
            headers=auth,
        )
        assert r.status_code == 200
        table_id = r.json()["table_id"]

        mock_client = _mock_api_fetch_response(200, [])
        with patch("httpx2.Client", return_value=mock_client):
            r = client.post(
                f"/api/v1/workspaces/{ws_id}/tables/{table_id}/import-api",
                json={"url": "https://x.com"},
                headers=auth,
            )
            assert r.status_code == 400

    def test_append_import_exception(self, client, ws_with_auth, db_engine, db):
        ws_id, auth = ws_with_auth

        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-csv",
            json={"table_name": "TAPP3", "csv_text": "a,b\n1,2\n"},
            headers=auth,
        )
        assert r.status_code == 200
        table_id = r.json()["table_id"]

        mock_client = _mock_api_fetch_response(200, [{"a": 1}])
        with patch("httpx2.Client", return_value=mock_client):
            with patch(
                "cndb.plugins.tables.routers.import_api.import_rows_from_json",
                side_effect=RuntimeError("bad import"),
            ):
                r = client.post(
                    f"/api/v1/workspaces/{ws_id}/tables/{table_id}/import-api",
                    json={"url": "https://x.com"},
                    headers=auth,
                )
                assert r.status_code == 400


__all__ = []
