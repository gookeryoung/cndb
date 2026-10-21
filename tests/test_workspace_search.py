"""工作区统一检索（顶栏搜索框）—— ``GET /api/v1/workspaces/{wid}/search``.

覆盖口径：
1. 文档走 FTS（与文档全文搜索同源），表名 / 表行命中分别成项；
2. **数据表默认只在当前激活视图范围内检索**：带 ``table_id`` + ``view_id`` 时，
   视图 filters 作为前置条件（AND / OR 语义保留），视图外的行不得命中；
3. ``scope`` 分路（all / documents / tables）；
4. 非成员一律 403。
"""

from __future__ import annotations

from typing import Any

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def owner(db) -> User:
    u = User(username="gs_owner", nickname="GS Owner")
    u.set_password("pw")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth(client, owner) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": owner.username, "password": "pw"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def ws(db, owner) -> Workspace:
    w = Workspace(name="GS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws, owner) -> DataTable:
    """两张文本字段的表：名称（标题列）+ 状态（用于视图筛选）."""
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="客户清单", owner_id=owner.id)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for name, order in [("名称", 0), ("状态", 1)]:
        df = DataField(table_id=dt.id, name=name, field_type="text", order=order)
        df.ensure_db_name()
        db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    return dt


def _rows_url(ws: Workspace, table: DataTable) -> str:
    return f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records"


def _add_row(client, ws, table, auth, name: str, status: str | None = None) -> None:
    values = {"名称": name}
    if status is not None:
        values["状态"] = status
    r = client.post(_rows_url(ws, table), json={"values": values}, headers=auth)
    assert r.status_code in (200, 201), r.text


def _add_view(client, ws, table, auth, name: str, filters: list[dict[str, Any]], logic: str = "AND") -> dict:
    r = client.post(
        f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
        json={"name": name, "view_type": "grid", "filters": filters, "filter_type": logic},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _add_doc(client, ws, auth, title: str, content: str = "正文内容") -> None:
    r = client.post(
        f"/api/v1/workspaces/{ws.id}/documents",
        json={"title": title, "content": content},
        headers=auth,
    )
    assert r.status_code == 201, r.text


def _search(client, ws, auth, q: str, **params: Any) -> dict:
    r = client.get(f"/api/v1/workspaces/{ws.id}/search", params={"q": q, **params}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


class TestScopeRouting:
    def test_all_scope_returns_both_sides(self, client, ws, table, auth):
        _add_row(client, ws, table, auth, "华东客户甲", "进行中")
        _add_doc(client, ws, auth, "华东客户复盘")

        data = _search(client, ws, auth, "华东")
        assert [d["title"] for d in data["documents"]] == ["华东客户复盘"]
        assert [r["title"] for r in data["rows"]] == ["华东客户甲"]
        assert data["tables"] == []  # 表名不含关键词

    def test_documents_scope_skips_tables(self, client, ws, table, auth):
        _add_row(client, ws, table, auth, "华东客户甲", "进行中")
        _add_doc(client, ws, auth, "华东客户复盘")

        data = _search(client, ws, auth, "华东", scope="documents")
        assert len(data["documents"]) == 1
        assert data["rows"] == [] and data["tables"] == []

    def test_tables_scope_skips_documents(self, client, ws, table, auth):
        _add_row(client, ws, table, auth, "华东客户甲", "进行中")
        _add_doc(client, ws, auth, "华东客户复盘")

        data = _search(client, ws, auth, "华东", scope="tables")
        assert data["documents"] == []
        assert len(data["rows"]) == 1

    def test_table_name_hit(self, client, ws, table, auth):
        data = _search(client, ws, auth, "客户清单", scope="tables")
        assert [t["name"] for t in data["tables"]] == ["客户清单"]

    def test_blank_query_returns_empty(self, client, ws, auth):
        data = _search(client, ws, auth, "   ")
        assert data == {"query": "", "documents": [], "tables": [], "rows": [], "view": None}


class TestActiveViewScope:
    def test_rows_limited_to_active_view_filter(self, client, ws, table, auth):
        """默认只在当前激活视图范围内检索：视图筛「进行中」，已归档行不命中"""
        _add_row(client, ws, table, auth, "华东客户甲", "进行中")
        _add_row(client, ws, table, auth, "华东客户乙", "已归档")
        view = _add_view(client, ws, table, auth, "进行中客户", [{"field_name": "状态", "op": "=", "value": "进行中"}])

        data = _search(
            client,
            ws,
            auth,
            "华东",
            scope="tables",
            table_id=table.id,
            view_id=view["id"],
        )
        assert [r["title"] for r in data["rows"]] == ["华东客户甲"]
        assert data["view"]["name"] == "进行中客户"
        assert data["view"]["table_id"] == table.id

    def test_without_view_searches_whole_table(self, client, ws, table, auth):
        _add_row(client, ws, table, auth, "华东客户甲", "进行中")
        _add_row(client, ws, table, auth, "华东客户乙", "已归档")

        data = _search(client, ws, auth, "华东", scope="tables", table_id=table.id)
        assert len(data["rows"]) == 2
        assert data["view"] == {"id": None, "name": "", "table_id": table.id, "table_name": "客户清单"}

    def test_view_logic_or_preserved(self, client, ws, table, auth):
        """视图 filter_type=OR 时，组内条件按 OR 组合后再与关键词 AND"""
        _add_row(client, ws, table, auth, "华东客户甲", "进行中")
        _add_row(client, ws, table, auth, "华东客户乙", "待确认")
        _add_row(client, ws, table, auth, "华东客户丙", "已归档")
        view = _add_view(
            client,
            ws,
            table,
            auth,
            "在办",
            [
                {"field_name": "状态", "op": "=", "value": "进行中"},
                {"field_name": "状态", "op": "=", "value": "待确认"},
            ],
            logic="OR",
        )

        data = _search(client, ws, auth, "华东", scope="tables", table_id=table.id, view_id=view["id"])
        assert sorted(r["title"] for r in data["rows"]) == ["华东客户乙", "华东客户甲"]

    def test_unknown_view_falls_back_to_whole_table(self, client, ws, table, auth):
        _add_row(client, ws, table, auth, "华东客户甲", "进行中")
        data = _search(client, ws, auth, "华东", scope="tables", table_id=table.id, view_id=999999)
        assert len(data["rows"]) == 1
        assert data["view"]["id"] is None

    def test_other_table_id_not_leaked(self, client, ws, table, auth, db):
        """同一工作区的另一张表：指定 table_id 时不得串到其它表"""
        other = DataTable(workspace_id=ws.id, name="供应商", owner_id=table.owner_id)
        other.ensure_db_name()
        db.add(other)
        db.flush()
        df = DataField(table_id=other.id, name="名称", field_type="text", order=0)
        df.ensure_db_name()
        db.add(df)
        db.commit()
        db.refresh(other)
        ddl.create_table(db.get_bind(), other)

        _add_row(client, ws, table, auth, "华东客户甲", "进行中")
        _add_row(client, ws, other, auth, "华东供应商甲", "正常")

        data = _search(client, ws, auth, "华东", scope="tables", table_id=table.id)
        assert {r["table_id"] for r in data["rows"]} == {table.id}


class TestAccess:
    def test_non_member_forbidden(self, client, ws, auth, db):
        outsider = User(username="gs_outsider", email="gs_outsider@example.com")
        outsider.set_password("pw")
        db.add(outsider)
        db.commit()
        r = client.post("/api/v1/accounts/auth/login", json={"login": "gs_outsider", "password": "pw"})
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

        resp = client.get(f"/api/v1/workspaces/{ws.id}/search", params={"q": "华东"}, headers=headers)
        assert resp.status_code == 403


def _make_table(db, ws: Workspace, owner: User, name: str) -> DataTable:
    """建一张只有「名称」文本列的空表，返回元数据对象."""
    dt = DataTable(workspace_id=ws.id, name=name, owner_id=owner.id)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    df = DataField(table_id=dt.id, name="名称", field_type="text", order=0)
    df.ensure_db_name()
    db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(db.get_bind(), dt)
    return dt


class TestCoverageAndCache:
    """工作区范围的全表覆盖与结果缓存（ADR 0015）."""

    def test_workspace_scope_scans_beyond_first_eight_tables(self, client, ws, table, auth, db):
        """第 9 张及以后的数据表也要被扫描（旧实现只扫前 8 张，永远搜不到）."""
        owner = db.get(User, table.owner_id)
        for i in range(9):
            _make_table(db, ws, owner, f"填充表{i}")
        last = _make_table(db, ws, owner, "最后一张表")
        _add_row(client, ws, last, auth, "深表命中词")

        data = _search(client, ws, auth, "深表命中词", scope="all")
        assert [r["table_id"] for r in data["rows"]] == [last.id]

    def test_workspace_scope_ignores_view_filter_and_table(self, client, ws, table, auth, db):
        """工作区范围不按当前表 / 视图收敛：视图外的行和其他表的行都要命中."""
        other = _make_table(db, ws, db.get(User, table.owner_id), "供应商")
        _add_row(client, ws, table, auth, "华东客户甲", "进行中")
        _add_row(client, ws, table, auth, "华东客户乙", "已归档")
        _add_row(client, ws, other, auth, "华东供应商甲")
        view = _add_view(client, ws, table, auth, "进行中客户", [{"field_name": "状态", "op": "=", "value": "进行中"}])

        data = _search(
            client,
            ws,
            auth,
            "华东",
            scope="all",
            table_id=table.id,
            view_id=view["id"],
        )
        assert sorted(r["title"] for r in data["rows"]) == ["华东供应商甲", "华东客户乙", "华东客户甲"]
        assert data["view"] is None

    def test_table_scope_still_converges_to_active_view(self, client, ws, table, auth, db):
        """数据表范围保持 ADR 0012 口径：只搜当前表，并按激活视图过滤."""
        other = _make_table(db, ws, db.get(User, table.owner_id), "供应商")
        _add_row(client, ws, table, auth, "华东客户甲", "进行中")
        _add_row(client, ws, table, auth, "华东客户乙", "已归档")
        _add_row(client, ws, other, auth, "华东供应商甲")
        view = _add_view(client, ws, table, auth, "进行中客户", [{"field_name": "状态", "op": "=", "value": "进行中"}])

        data = _search(
            client,
            ws,
            auth,
            "华东",
            scope="tables",
            table_id=table.id,
            view_id=view["id"],
        )
        assert [r["title"] for r in data["rows"]] == ["华东客户甲"]
        assert data["view"]["name"] == "进行中客户"

    def test_repeated_query_hits_result_cache(self, client, ws, table, auth, monkeypatch):
        """相同关键词 + 相同范围只应真正扫表一次."""
        from cndb.plugins.workspaces.services import search as search_service

        _add_row(client, ws, table, auth, "华东客户甲", "进行中")
        calls = {"n": 0}
        original = search_service._search_rows_in_table

        def counting(*args, **kwargs):
            calls["n"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(search_service, "_search_rows_in_table", counting)
        _search(client, ws, auth, "华东", scope="all")
        first = calls["n"]
        assert first > 0

        _search(client, ws, auth, "华东", scope="all")
        assert calls["n"] == first

    def test_row_create_invalidates_cache(self, client, ws, table, auth):
        """单行创建走 record.* 事件，搜索结果缓存应即时失效."""
        assert _search(client, ws, auth, "新增命中", scope="all")["rows"] == []

        _add_row(client, ws, table, auth, "新增命中", "进行中")

        data = _search(client, ws, auth, "新增命中", scope="all")
        assert [r["title"] for r in data["rows"]] == ["新增命中"]

    def test_bulk_create_invalidates_cache(self, client, ws, table, auth, db):
        """批量导入不写 audit，由写函数显式失效缓存."""
        from cndb.plugins.tables.services.core import records as rec

        assert _search(client, ws, auth, "批量命中", scope="all")["rows"] == []

        rec.bulk_create(db.get_bind(), table, [{"名称": "批量命中"}], db=db)

        data = _search(client, ws, auth, "批量命中", scope="all")
        assert [r["title"] for r in data["rows"]] == ["批量命中"]
