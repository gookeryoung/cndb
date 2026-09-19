"""通用文件导入建表 API 路由测试 — 覆盖 CSV / TSV / JSON / XLSX 四种格式.

测试的新端点：
- POST /{workspace_id}/import-file/analyze  — multipart 文件上传 + 分析
- POST /{workspace_id}/import-file          — multipart 文件上传 + 建表 + 导入
"""

from __future__ import annotations

import io
import json

import pytest
from openpyxl import Workbook

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def ws_auth(client, db):
    """工作区 + 认证 fixture（与 test_import_csv_api 兼容但独立，方便跑单测）."""
    session = db

    u = User(username="file_import_user", nickname="File Import User")
    u.set_password("passw0rd")
    session.add(u)
    session.flush()

    ws = Workspace(name="FileImportWS", created_by_id=u.id)
    session.add(ws)
    session.flush()
    session.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
    session.commit()

    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": "file_import_user", "password": "passw0rd"},
    )
    token = r.json()["access_token"]
    return ws.id, {"Authorization": f"Bearer {token}"}


# ── 测试辅助：构造四种格式的文件字节 ──────────────────


def _build_csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _build_tsv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _build_json_bytes(rows: list[dict]) -> bytes:
    return json.dumps(rows, ensure_ascii=False).encode("utf-8")


def _build_xlsx_bytes(headers: list[str], rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── POST /import-file/analyze ──────────────────────────


class TestImportFileAnalyzeApi:
    """multipart 文件分析端点 — 覆盖四种格式."""

    def test_analyze_csv(self, client, ws_auth):
        ws_id, auth = ws_auth
        csv_bytes = _build_csv_bytes("name,age,email\nAlice,30,a@b.com\nBob,25,c@d.com\n")
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file/analyze",
            files={"file": ("people.csv", csv_bytes, "text/csv")},
            headers=auth,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["format"] == "csv"
        assert data["total_rows"] == 2
        assert data["filename"] == "people.csv"
        col_names = [c["name"] for c in data["columns"]]
        assert col_names == ["name", "age", "email"]
        # 类型推断
        type_map = {c["name"]: c["field_type"] for c in data["columns"]}
        assert type_map["name"] == "text"
        assert type_map["age"] == "number"
        assert type_map["email"] == "email"

    def test_analyze_tsv(self, client, ws_auth):
        ws_id, auth = ws_auth
        tsv_bytes = _build_tsv_bytes("name\tage\nAlice\t30\nBob\t25\n")
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file/analyze",
            files={"file": ("data.tsv", tsv_bytes, "text/tab-separated-values")},
            headers=auth,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["format"] == "tsv"
        assert data["total_rows"] == 2
        assert [c["name"] for c in data["columns"]] == ["name", "age"]

    def test_analyze_json(self, client, ws_auth):
        ws_id, auth = ws_auth
        payload = [
            {"name": "Alice", "age": 30, "active": True},
            {"name": "Bob", "age": 25, "active": False},
        ]
        json_bytes = _build_json_bytes(payload)
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file/analyze",
            files={"file": ("data.json", json_bytes, "application/json")},
            headers=auth,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["format"] == "json"
        assert data["total_rows"] == 2
        col_names = [c["name"] for c in data["columns"]]
        assert set(col_names) == {"name", "age", "active"}
        # JSON 原生 bool/int 保留类型推断
        type_map = {c["name"]: c["field_type"] for c in data["columns"]}
        assert type_map["active"] == "boolean"
        assert type_map["age"] == "number"

    def test_analyze_xlsx(self, client, ws_auth):
        ws_id, auth = ws_auth
        xlsx_bytes = _build_xlsx_bytes(
            headers=["产品", "价格", "库存"],
            rows=[["手机", 2999.99, 100], ["笔记本", 8999.0, 50]],
        )
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file/analyze",
            files={
                "file": (
                    "products.xlsx",
                    xlsx_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            headers=auth,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["format"] == "xlsx"
        assert data["total_rows"] == 2
        col_names = [c["name"] for c in data["columns"]]
        assert col_names == ["产品", "价格", "库存"]
        type_map = {c["name"]: c["field_type"] for c in data["columns"]}
        assert type_map["价格"] in ("float", "number")
        assert type_map["库存"] == "number"

    def test_analyze_semicolon_csv(self, client, ws_auth):
        """分号分隔的 CSV（欧洲格式）."""
        ws_id, auth = ws_auth
        csv_bytes = b"name;amount\nAlice;10,5\nBob;20,5\n"
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file/analyze",
            files={"file": ("semicolon.csv", csv_bytes, "text/csv")},
            headers=auth,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["format"] == "csv"
        assert data["total_rows"] == 2
        # sniff 应识别为分号分隔
        col_names = [c["name"] for c in data["columns"]]
        assert col_names == ["name", "amount"]

    def test_analyze_sample_rows_truncated(self, client, ws_auth):
        """sample_rows 截断自单次解析的前 50 行 —— total_rows 仍按全量统计."""
        ws_id, auth = ws_auth
        lines = ["idx"] + [str(i) for i in range(120)]
        csv_bytes = _build_csv_bytes("\n".join(lines) + "\n")
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file/analyze",
            files={"file": ("big.csv", csv_bytes, "text/csv")},
            headers=auth,
        )
        assert r.status_code == 200
        data = r.json()
        # 全量统计不受样本截断影响
        assert data["total_rows"] == 120
        # 样本仅截取前 50 行，内容为首行起的连续截断
        assert len(data["sample_rows"]) == 50
        assert data["sample_rows"][0] == {"idx": "0"}
        assert data["sample_rows"][-1] == {"idx": "49"}

    def test_analyze_empty_file(self, client, ws_auth):
        ws_id, auth = ws_auth
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file/analyze",
            files={"file": ("empty.csv", b"", "text/csv")},
            headers=auth,
        )
        assert r.status_code == 400

    def test_analyze_xls_rejected(self, client, ws_auth):
        """旧版 .xls 应拒绝并提示用户另存为 .xlsx."""
        ws_id, auth = ws_auth
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file/analyze",
            files={"file": ("legacy.xls", b"dummy", "application/vnd.ms-excel")},
            headers=auth,
        )
        assert r.status_code == 400
        assert "xlsx" in r.json()["detail"].lower() or "另存" in r.json()["detail"]

    def test_analyze_unauthorized(self, client, ws_auth):
        ws_id, _auth = ws_auth
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file/analyze",
            files={"file": ("test.csv", b"a\n1\n", "text/csv")},
        )
        assert r.status_code in (401, 403)


# ── POST /import-file (create table + import) ─────────


class TestImportFileCreateTableApi:
    """multipart 文件建表端点 — 覆盖四种格式."""

    def test_create_csv(self, client, ws_auth):
        ws_id, auth = ws_auth
        csv_bytes = b"name,age\nAlice,30\nBob,25\n"
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file",
            data={"table_name": "人员表"},
            files={"file": ("人员.csv", csv_bytes, "text/csv")},
            headers=auth,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["table_name"] == "人员表"
        assert data["imported_rows"] == 2
        assert data["field_count"] == 2
        assert data["table_id"] is not None

    def test_create_tsv(self, client, ws_auth):
        ws_id, auth = ws_auth
        tsv_bytes = b"name\tage\nAlice\t30\nBob\t25\n"
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file",
            data={"table_name": "tsv表"},
            files={"file": ("data.tsv", tsv_bytes, "text/tab-separated-values")},
            headers=auth,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["imported_rows"] == 2
        assert data["field_count"] == 2

    def test_create_json(self, client, ws_auth):
        ws_id, auth = ws_auth
        payload = [
            {"name": "Alice", "age": 30, "active": True},
            {"name": "Bob", "age": 25, "active": False},
        ]
        json_bytes = _build_json_bytes(payload)
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file",
            data={"table_name": "json表"},
            files={"file": ("data.json", json_bytes, "application/json")},
            headers=auth,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["imported_rows"] == 2
        assert data["field_count"] == 3

    def test_create_xlsx(self, client, ws_auth):
        ws_id, auth = ws_auth
        xlsx_bytes = _build_xlsx_bytes(
            headers=["产品", "价格"],
            rows=[["手机", 2999.99], ["笔记本", 8999]],
        )
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file",
            data={"table_name": "产品表"},
            files={
                "file": (
                    "products.xlsx",
                    xlsx_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            headers=auth,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["imported_rows"] == 2
        assert data["field_count"] == 2

    def test_create_without_table_name_uses_filename(self, client, ws_auth):
        """table_name 未传时，用文件名推断."""
        ws_id, auth = ws_auth
        csv_bytes = b"a,b\n1,2\n"
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file",
            files={"file": ("订单数据.csv", csv_bytes, "text/csv")},
            headers=auth,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["table_name"] == "订单数据"
        assert data["imported_rows"] == 1

    def test_create_select_field_auto_promoted(self, client, ws_auth):
        """低基数离散列应被自动提升为 select 类型."""
        ws_id, auth = ws_auth
        csv_bytes = "name,部门\nAlice,研发\nBob,研发\nCharlie,市场\n".encode()
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file",
            data={"table_name": "员工"},
            files={"file": ("emp.csv", csv_bytes, "text/csv")},
            headers=auth,
        )
        assert r.status_code == 200
        data = r.json()
        # 部门列只有两个唯一值，应被提升为 select
        cols = data.get("columns", [])
        dept_col = next((c for c in cols if c["name"] == "部门"), None)
        assert dept_col is not None
        assert dept_col["field_type"] == "select"

    def test_create_empty_file_rejected(self, client, ws_auth):
        ws_id, auth = ws_auth
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file",
            data={"table_name": "空表"},
            files={"file": ("empty.csv", b"", "text/csv")},
            headers=auth,
        )
        assert r.status_code == 400

    def test_create_unauthorized(self, client, ws_auth):
        ws_id, _auth = ws_auth
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file",
            data={"table_name": "test"},
            files={"file": ("test.csv", b"a\n1\n", "text/csv")},
        )
        assert r.status_code in (401, 403)


__all__ = []
