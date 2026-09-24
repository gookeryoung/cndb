"""import-api 路由 + transfer JSON 推断 集成测试."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.services.transfer import (
    analyze_json_columns,
    create_table_from_json_data,
)
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

# ── fixtures ──────────────────────────────────────────


@pytest.fixture
def workspace_with_auth(client, db):
    """创建一个 workspace + owner 用户 + 登录 token."""
    u = User(username="api_user", nickname="API User")
    u.set_password("passw0rd")
    db.add(u)
    db.flush()

    ws = Workspace(name="API-WS", created_by_id=u.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
    db.commit()

    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": "api_user", "password": "passw0rd"},
    )
    token = r.json()["access_token"]
    return ws.id, {"Authorization": f"Bearer {token}"}


# ── analyze_json_columns 单元测试 ─────────────────────


class TestAnalyzeJsonColumns:
    def test_basic_types(self):
        rows = [
            {"name": "Alice", "age": 30, "score": 95.5, "active": True},
            {"name": "Bob", "age": 25, "score": 88.0, "active": False},
        ]
        cols = analyze_json_columns(rows)
        name_map = {c["name"]: c for c in cols}
        assert name_map["name"]["field_type"] == "text"
        assert name_map["age"]["field_type"] == "number"
        assert name_map["score"]["field_type"] == "float"
        assert name_map["active"]["field_type"] == "boolean"

    def test_email_url_date_inference(self):
        rows = [
            {"email": "a@example.com", "site": "https://x.com", "birthday": "1990-01-01"},
        ]
        cols = analyze_json_columns(rows)
        name_map = {c["name"]: c for c in cols}
        assert name_map["email"]["field_type"] == "email"
        assert name_map["site"]["field_type"] == "url"
        assert name_map["birthday"]["field_type"] == "date"

    def test_nested_json_field(self):
        rows = [
            {"name": "A", "profile": {"age": 10, "tags": ["x", "y"]}},
        ]
        cols = analyze_json_columns(rows)
        name_map = {c["name"]: c for c in cols}
        assert name_map["profile"]["field_type"] == "json"

    def test_low_cardinality_promoted_to_select(self):
        """唯一值数 / 非空样本数 ≤ 0.5 才会提升为 select."""
        rows = [
            {"status": "ok"},
            {"status": "ok"},
            {"status": "ok"},
            {"status": "fail"},
            {"status": "fail"},
        ]
        cols = analyze_json_columns(rows)
        status = next(c for c in cols if c["name"] == "status")
        # 2 个唯一值 / 5 行 = 0.4 ≤ 0.5
        assert status["field_type"] == "select"
        assert "options" in status

    def test_null_ratio(self):
        rows = [
            {"a": 1, "b": None},
            {"a": 2, "b": "x"},
            {"a": 3, "b": ""},
        ]
        cols = analyze_json_columns(rows)
        name_map = {c["name"]: c for c in cols}
        # b 列 2/3 空
        assert name_map["b"]["null_ratio"] == pytest.approx(2 / 3, abs=0.01)

    def test_empty_rows(self):
        assert analyze_json_columns([]) == []

    def test_missing_key_in_some_rows(self):
        rows = [
            {"a": 1, "b": 2},
            {"a": 3},  # b 缺失
            {"a": 4, "b": 5},
        ]
        cols = analyze_json_columns(rows)
        names = {c["name"] for c in cols}
        assert names == {"a", "b"}


# ── create_table_from_json_data（需要 DB） ────────────


class TestCreateTableFromJsonData:
    def test_end_to_end(self, db_engine, db):
        rows = [
            {"name": "北京", "temp": 22.5, "humidity": 60, "sunny": True, "date": "2024-06-01"},
            {"name": "上海", "temp": 26.1, "humidity": 75, "sunny": False, "date": "2024-06-01"},
            {"name": "广州", "temp": 30.2, "humidity": 80, "sunny": True, "date": "2024-06-01"},
        ]
        ws = Workspace(name="JSON-WS")
        db.add(ws)
        db.flush()

        dt, ids = create_table_from_json_data(db_engine, db, ws.id, "天气", rows)

        assert dt.id is not None
        assert len(ids) == 3
        field_names = {f.name: f.field_type for f in dt.fields}
        assert "name" in field_names
        assert field_names["temp"] == "float"
        assert field_names["humidity"] == "number"
        assert field_names["sunny"] == "boolean"

        # 自动建表同时生成默认视图「全部」
        from cndb.plugins.tables.models import DataView

        views = db.query(DataView).filter(DataView.table_id == dt.id).all()
        assert len(views) == 1
        v = views[0]
        assert v.name == "全部"
        assert v.view_type == "grid"
        assert v.is_default is True

        from cndb.plugins.tables.services.core import records as rec

        got_rows, _total = rec.list_rows(db_engine, dt, db=db)
        assert len(got_rows) == 3

    def test_select_field_config_preserved_as_dicts(self, db_engine, db):
        """JSON 含低基数离散列 → 推断为 select,config.options 存为 dict 格式."""
        rows = [
            {"name": "张三", "status": "进行中", "金额": 1000},
            {"name": "李四", "status": "已完成", "金额": 2000},
            {"name": "王五", "status": "进行中", "金额": 3000},
            {"name": "赵六", "status": "已取消", "金额": 4000},
            {"name": "孙七", "status": "进行中", "金额": 5000},
            {"name": "周八", "status": "已完成", "金额": 6000},
            {"name": "吴九", "status": "进行中", "金额": 7000},
            {"name": "郑十", "status": "已完成", "金额": 8000},
        ]
        ws = Workspace(name="JSON-SELECT-WS")
        db.add(ws)
        db.flush()

        dt, ids = create_table_from_json_data(db_engine, db, ws.id, "项目表", rows)

        assert len(ids) == 8
        status_field = next(f for f in dt.fields if f.name == "status")
        assert status_field.field_type == "select"
        opts = status_field.config.get("options")
        assert opts is not None, f"options missing from config: {status_field.config}"
        assert len(opts) == 3, f"expected 3 options, got {opts}"
        for opt in opts:
            assert isinstance(opt, dict), f"expected dict option, got {type(opt)}: {opt}"
            assert "label" in opt and "value" in opt
        labels = [o["label"] for o in opts]
        assert set(labels) == {"进行中", "已完成", "已取消"}


# ── Mock httpx2 辅助 ──────────────────────────────────


def _build_mock_client(status_code: int, body: dict | list | bytes, content_type: str = "application/json"):
    resp = MagicMock()
    resp.status_code = status_code
    raw = json.dumps(body).encode("utf-8") if isinstance(body, (dict, list)) else body
    resp.content = raw
    resp.text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    resp.headers = {"content-type": content_type}

    client = MagicMock()
    client.request.return_value = resp
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


# ── POST /import-api/analyze ─────────────────────────


class TestImportApiAnalyzeEndpoint:
    def test_analyze_ok(self, client, workspace_with_auth):
        ws_id, auth = workspace_with_auth
        mock_client = _build_mock_client(
            200,
            {
                "data": [
                    {"name": "北京", "temp": 22.5, "sunny": True},
                    {"name": "上海", "temp": 26.1, "sunny": False},
                ]
            },
        )
        with patch("httpx2.Client", return_value=mock_client):
            r = client.post(
                f"/api/v1/workspaces/{ws_id}/import-api/analyze",
                json={"url": "https://api.open-meteo.com/v1/forecast"},
                headers=auth,
            )
            assert r.status_code == 200, r.text
            payload = r.json()
            assert payload["total_rows"] == 2
            assert any(c["name"] == "name" for c in payload["columns"])
            temp = next(c for c in payload["columns"] if c["name"] == "temp")
            assert temp["field_type"] == "float"

    def test_analyze_ssrf_blocked(self, client, workspace_with_auth):
        ws_id, auth = workspace_with_auth
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-api/analyze",
            json={"url": "http://127.0.0.1/admin"},
            headers=auth,
        )
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "保留" in detail or "SSRF" in detail

    def test_analyze_non_http(self, client, workspace_with_auth):
        ws_id, auth = workspace_with_auth
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-api/analyze",
            json={"url": "file:///etc/passwd"},
            headers=auth,
        )
        assert r.status_code == 400

    def test_analyze_api_error_propagated(self, client, workspace_with_auth):
        ws_id, auth = workspace_with_auth
        mock_client = _build_mock_client(500, b"server error", content_type="text/plain")
        with patch("httpx2.Client", return_value=mock_client):
            r = client.post(
                f"/api/v1/workspaces/{ws_id}/import-api/analyze",
                json={"url": "https://example.com/api"},
                headers=auth,
            )
            assert r.status_code == 400  # ValueError 被转 400


# ── POST /import-api（建表 + 导入） ────────────────────


class TestImportApiCreateTableEndpoint:
    def test_import_creates_table_and_rows(self, client, workspace_with_auth):
        ws_id, auth = workspace_with_auth
        mock_client = _build_mock_client(
            200,
            [
                {"name": "Bitcoin", "symbol": "BTC", "price": 65000.0},
                {"name": "Ethereum", "symbol": "ETH", "price": 3200.5},
                {"name": "Solana", "symbol": "SOL", "price": 145.3},
            ],
        )
        with patch("httpx2.Client", return_value=mock_client):
            r = client.post(
                f"/api/v1/workspaces/{ws_id}/import-api",
                json={
                    "url": "https://api.coingecko.com/api/v3/coins/markets",
                    "table_name": "加密货币行情",
                },
                headers=auth,
            )
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["table_name"] == "加密货币行情"
            assert data["imported_rows"] == 3
            assert data["field_count"] == 3
            assert data["table_id"] is not None

            # 再查 tables list 确认表真实存在
            r2 = client.get(f"/api/v1/workspaces/{ws_id}/tables/", headers=auth)
            assert r2.status_code == 200
            names = [t["name"] for t in r2.json()]
            assert "加密货币行情" in names

    def test_import_empty_response(self, client, workspace_with_auth):
        ws_id, auth = workspace_with_auth
        mock_client = _build_mock_client(200, {"data": []})
        with patch("httpx2.Client", return_value=mock_client):
            r = client.post(
                f"/api/v1/workspaces/{ws_id}/import-api",
                json={"url": "https://x.com/empty", "table_name": "空表"},
                headers=auth,
            )
            assert r.status_code == 400

    def test_import_unauthorized(self, client, workspace_with_auth):
        ws_id, _auth = workspace_with_auth
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-api",
            json={"url": "https://x.com", "table_name": "x"},
        )
        assert r.status_code in (401, 403)


# ── POST /tables/{table_id}/import-api（追加） ──────────


class TestImportApiAppendEndpoint:
    def test_append_rows(self, client, workspace_with_auth):
        ws_id, auth = workspace_with_auth

        # 先建一个表（用 CSV 路由）
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-csv",
            json={
                "table_name": "测试表",
                "csv_text": "name,value\nA,1\nB,2\n",
            },
            headers=auth,
        )
        assert r.status_code == 200, r.text
        table_id = r.json()["table_id"]
        assert r.json()["imported_rows"] == 2

        # 再追加 API 数据
        mock_client = _build_mock_client(
            200,
            [{"name": "C", "value": 3}, {"name": "D", "value": 4}],
        )
        with patch("httpx2.Client", return_value=mock_client):
            r = client.post(
                f"/api/v1/workspaces/{ws_id}/tables/{table_id}/import-api",
                json={"url": "https://x.com/api"},
                headers=auth,
            )
            assert r.status_code == 200, r.text
            assert r.json()["appended_rows"] == 2

        # 验证总行数
        r = client.get(
            f"/api/v1/workspaces/{ws_id}/tables/{table_id}/records",
            headers=auth,
        )
        assert r.status_code == 200
        items = r.json().get("items", [])
        assert len(items) == 4

    def test_append_table_not_found(self, client, workspace_with_auth):
        ws_id, auth = workspace_with_auth
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/99999/import-api",
            json={"url": "https://x.com"},
            headers=auth,
        )
        assert r.status_code == 404


__all__ = []
