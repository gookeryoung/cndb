"""bulk + transfer 模块测试 —— 纯函数可独立测，路由走 API."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.models.base import Base
from cndb.plugins.accounts.models import User
from cndb.plugins.tables import ddl, transfer
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole

# ── transfer 纯函数测试 ──────────────────────────────


class TestTransferPure:
    def test_export_json(self):
        rows = [{"姓名": "A", "年龄": 1}, {"姓名": "B", "年龄": 2}]
        text = transfer.export_rows_to_json(rows)
        assert json.loads(text) == rows

    def test_export_json_empty(self):
        assert transfer.export_rows_to_json([]) == "[]"

    def test_export_csv(self):
        rows = [{"姓名": "A", "年龄": 1}]
        csv_text = transfer.export_rows_to_csv(rows)
        assert "姓名,年龄" in csv_text
        assert "A,1" in csv_text

    def test_export_csv_empty(self):
        assert transfer.export_rows_to_csv([]) == ""

    def test_export_xlsx(self):
        rows = [{"姓名": "A", "年龄": 1}]
        data = transfer.export_rows_to_xlsx(rows)
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_export_xlsx_empty(self):
        data = transfer.export_rows_to_xlsx([])
        assert isinstance(data, bytes)

    def test_guess_format(self):
        assert transfer.guess_format_from_filename("a.xlsx") == "xlsx"
        assert transfer.guess_format_from_filename("a.CSV") == "csv"
        assert transfer.guess_format_from_filename("a.json") == "json"
        with pytest.raises(ValueError):
            transfer.guess_format_from_filename("a.txt")


# ── bulk router API 测试 ─────────────────────────────


@pytest.fixture
def db(tmp_path):
    settings.AUTH_ENABLED = True
    db_path = tmp_path / "bulk.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    import cndb.plugins.accounts.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db):
    from cndb.app import app

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def owner(db):
    u = User(username="bulk_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth_owner(client, owner):
    r = client.post("/api/v1/accounts/auth/login", json={"login": owner.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def ws(db, owner):
    from cndb.plugins.workspaces.models import WorkspaceMember

    w = Workspace(name="BWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="BulkTable")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    df = DataField(table_id=dt.id, name="姓名", field_type="text", order=0)
    df.ensure_db_name()
    db.add(df)
    db.flush()
    df2 = DataField(table_id=dt.id, name="年龄", field_type="number", order=1)
    df2.ensure_db_name()
    db.add(df2)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    # 加几条数据
    from cndb.plugins.tables import records as rec

    rec.create_row(engine, dt, {"姓名": "张三", "年龄": 20})
    rec.create_row(engine, dt, {"姓名": "李四", "年龄": 30})
    rec.create_row(engine, dt, {"姓名": "王五", "年龄": 40})
    return dt


class TestBulkAPI:
    def test_bulk_create(self, client, ws, table, auth_owner):
        """覆盖 POST /records/bulk-create —— 批量新建行."""
        # 先用空 rows 测试 400
        r0 = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/bulk-create",
            json={"rows": []},
            headers=auth_owner,
        )
        assert r0.status_code == 400
        # 正常批量创建（values 包装格式）
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/bulk-create",
            json={
                "rows": [
                    {"values": {"姓名": "批量甲", "年龄": 25}},
                    {"values": {"姓名": "批量乙", "年龄": 28}},
                ],
            },
            headers=auth_owner,
        )
        assert r.status_code == 201
        assert r.json()["created"] == 2
        assert len(r.json()["ids"]) == 2

    def test_bulk_delete(self, client, ws, table, auth_owner):
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/bulk-delete",
            json={"row_ids": [1, 2]},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["deleted"] == 2

    def test_bulk_update(self, client, ws, table, auth_owner):
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/bulk-update",
            json={"row_ids": [1, 2], "values": {"年龄": 99}},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["updated"] == 2

    def test_bulk_update_empty(self, client, ws, table, auth_owner):
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/bulk-update",
            json={"row_ids": [], "values": {"年龄": 1}},
            headers=auth_owner,
        )
        assert r.status_code == 400

    def test_export_json(self, client, ws, table, auth_owner):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/export?format=json",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        data = json.loads(r.text)
        assert len(data) == 3

    def test_export_csv(self, client, ws, table, auth_owner):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/export?format=csv",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert "姓名" in r.text
        assert "张三" in r.text

    def test_export_invalid_format(self, client, ws, table, auth_owner):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/export?format=pdf",
            headers=auth_owner,
        )
        assert r.status_code == 400

    def test_import_json(self, client, ws, table, auth_owner):
        import io

        data = json.dumps([{"姓名": "导入1", "年龄": 100}, {"姓名": "导入2", "年龄": 200}])
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/import",
            files={"file": ("import.json", io.BytesIO(data.encode()), "application/json")},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["imported"] == 2

    def test_import_invalid_filename(self, client, ws, table, auth_owner):
        import io

        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/import",
            files={"file": ("test.txt", io.BytesIO(b"x"), "text/plain")},
            headers=auth_owner,
        )
        # guess_format 抛 ValueError 被 except 捕获 → 400
        assert r.status_code == 400

    def test_bulk_update_values_empty(self, client, ws, table, auth_owner):
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/bulk-update",
            json={"row_ids": [1, 2], "values": {}},
            headers=auth_owner,
        )
        assert r.status_code == 400

    def test_export_xlsx(self, client, ws, table, auth_owner):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/export?format=xlsx",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
        assert len(r.content) > 0

    def test_import_csv(self, client, ws, table, auth_owner):
        import io

        csv_content = "姓名,年龄\n赵六,60\n钱七,70\n"
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/import",
            files={"file": ("import.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["imported"] == 2

    def test_import_xlsx(self, client, ws, table, auth_owner):
        import io

        from openpyxl import Workbook

        wb = Workbook()
        ws_wb = wb.active
        assert ws_wb is not None
        ws_wb.append(["姓名", "年龄"])
        ws_wb.append(["孙八", 80])
        ws_wb.append(["周九", 90])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/import",
            files={"file": ("import.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["imported"] == 2

    def test_import_invalid_json_not_array(self, client, ws, table, auth_owner):
        import io

        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/import",
            files={"file": ("bad.json", io.BytesIO(b'"just a string"'), "application/json")},
            headers=auth_owner,
        )
        assert r.status_code == 400


__all__ = []
