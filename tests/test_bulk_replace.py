"""批量查找替换（需求 0149）.

覆盖：匹配模式（contains / exact / regex）、筛选范围、dry_run 不写库、
apply 写库并跳过校验失败行、字段类型与虚拟字段拒绝、上限、非法正则、接口层
"""

from __future__ import annotations

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core.bulk_replace import bulk_replace
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def owner(db):
    u = User(username="replace_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth(client, owner):
    r = client.post("/api/v1/accounts/auth/login", json={"login": "replace_owner", "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="ReplaceWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="替换表")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for order, (name, ftype) in enumerate([("名称", "text"), ("金额", "number")]):
        f = DataField(table_id=dt.id, name=name, field_type=ftype, order=order)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    for name in ("北京分公司", "上海分公司", "北京代表处"):
        rec.create_row(engine, dt, {"名称": name, "金额": 1}, db=db)
    return dt


def _names(db, table) -> list[str]:
    rows, _ = rec.list_rows(db.get_bind(), table, limit=0, db=db)
    return [row["名称"] for row in rows]


class TestBulkReplace:
    def test_contains_dry_run_reports_only(self, db, table):
        report = bulk_replace(db.get_bind(), table, field_name="名称", find="北京", replace="北京市", db=db)
        assert report["dry_run"] is True
        assert report["matched"] == 2
        assert report["updated"] == 0
        assert {item["new"] for item in report["preview"]} == {"北京市分公司", "北京市代表处"}
        # 未写库
        assert "北京分公司" in _names(db, table)

    def test_contains_apply(self, db, table):
        report = bulk_replace(
            db.get_bind(), table, field_name="名称", find="北京", replace="北京市", dry_run=False, db=db
        )
        assert report["updated"] == 2
        names = _names(db, table)
        assert "北京市分公司" in names and "北京市代表处" in names
        assert "上海分公司" in names

    def test_exact_match_only_whole_value(self, db, table):
        report = bulk_replace(
            db.get_bind(),
            table,
            field_name="名称",
            find="北京分公司",
            replace="总部",
            match="exact",
            dry_run=False,
            db=db,
        )
        assert report["updated"] == 1
        names = _names(db, table)
        assert "总部" in names and "北京代表处" in names

    def test_regex_match(self, db, table):
        report = bulk_replace(
            db.get_bind(),
            table,
            field_name="名称",
            find="^(北京|上海)",
            replace="华北-",
            match="regex",
            dry_run=False,
            db=db,
        )
        assert report["updated"] == 3
        assert all(name.startswith("华北-") for name in _names(db, table))

    def test_invalid_regex_rejected(self, db, table):
        with pytest.raises(ValueError, match="正则表达式非法"):
            bulk_replace(db.get_bind(), table, field_name="名称", find="([bad", match="regex", db=db)

    def test_unknown_match_mode(self, db, table):
        with pytest.raises(ValueError, match="不支持的匹配模式"):
            bulk_replace(db.get_bind(), table, field_name="名称", find="x", match="fuzzy", db=db)

    def test_empty_find_rejected(self, db, table):
        with pytest.raises(ValueError, match="不能为空"):
            bulk_replace(db.get_bind(), table, field_name="名称", find="", db=db)

    def test_non_text_field_rejected(self, db, table):
        with pytest.raises(ValueError, match="不是文本类型"):
            bulk_replace(db.get_bind(), table, field_name="金额", find="1", db=db)

    def test_virtual_field_rejected(self, db, table):
        field = next(f for f in table.fields if f.name == "名称")
        field.field_type = "formula"
        db.commit()
        db.refresh(table)
        with pytest.raises(ValueError, match="没有物理列"):
            bulk_replace(db.get_bind(), table, field_name="名称", find="北京", db=db)

    def test_unknown_field_rejected(self, db, table):
        with pytest.raises(ValueError, match="字段不存在"):
            bulk_replace(db.get_bind(), table, field_name="不存在", find="x", db=db)

    def test_filters_scope(self, db, table):
        report = bulk_replace(
            db.get_bind(),
            table,
            field_name="名称",
            find="公司",
            replace="公司（已改）",
            filters=[{"field_name": "名称", "op": "contains", "value": "上海"}],
            dry_run=False,
            db=db,
        )
        assert report["updated"] == 1
        names = _names(db, table)
        assert "上海分公司（已改）" in names
        assert "北京分公司" in names  # 范围外不动

    def test_max_rows_rejected(self, db, table):
        with pytest.raises(ValueError, match="超过单次替换上限"):
            bulk_replace(db.get_bind(), table, field_name="名称", find="公司", max_rows=1, db=db)

    def test_skips_invalid_rows(self, db, ws):
        """替换后触发字段规则的行被跳过并计数（不整批失败）。"""
        engine = db.get_bind()
        dt = DataTable(workspace_id=ws.id, name="替换规则表")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        code = DataField(table_id=dt.id, name="编号", field_type="text", order=0)
        code.ensure_db_name()
        code.config = {"validation": {"pattern": r"^[A-Z]{2}$"}}
        db.add(code)
        db.commit()
        db.refresh(dt)
        ddl.create_table(engine, dt)
        rec.create_row(engine, dt, {"编号": "AB"}, db=db)
        rec.create_row(engine, dt, {"编号": "CD"}, db=db)

        report = bulk_replace(engine, dt, field_name="编号", find="AB", replace="bad", dry_run=False, db=db)
        # matched = 命中的候选行；被字段规则拒绝的计入 skipped
        assert report["matched"] == 1
        assert report["updated"] == 0
        assert report["skipped"] == 1
        assert "AB" in [row["编号"] for row in rec.list_rows(engine, dt, limit=0, db=db)[0]]


class TestBulkReplaceApi:
    def test_dry_run_then_apply(self, client, db, ws, table, auth):
        url = f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/bulk-replace"
        preview = client.post(url, json={"field": "名称", "find": "北京", "replace": "北京市"}, headers=auth)
        assert preview.status_code == 200, preview.text
        assert preview.json()["matched"] == 2 and preview.json()["dry_run"] is True
        assert "北京分公司" in _names(db, table)

        applied = client.post(
            url, json={"field": "名称", "find": "北京", "replace": "北京市", "dry_run": False}, headers=auth
        )
        assert applied.status_code == 200
        assert applied.json()["updated"] == 2
        assert "北京市分公司" in _names(db, table)

    def test_api_rejects_bad_field(self, client, ws, table, auth):
        url = f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/bulk-replace"
        r = client.post(url, json={"field": "金额", "find": "1", "replace": "2"}, headers=auth)
        assert r.status_code == 400

    def test_api_viewer_forbidden(self, client, db, ws, table, auth):
        viewer = User(username="replace_viewer", nickname="V")
        viewer.set_password("passw0rd")
        db.add(viewer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        login = client.post("/api/v1/accounts/auth/login", json={"login": "replace_viewer", "password": "passw0rd"})
        viewer_auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
        url = f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/bulk-replace"
        r = client.post(url, json={"field": "名称", "find": "北京", "replace": "x"}, headers=viewer_auth)
        assert r.status_code in (403, 404)
