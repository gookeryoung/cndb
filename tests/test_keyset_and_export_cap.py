"""keyset 分页 + 可配导出上限（需求 0148）.

覆盖：
- 游标编解码：往返、非法串 400、超长拒绝
- keyset WHERE：按 id / 单字段排序 / 多字段混向 / NULL 排序键拒绝
- 接口：翻页不重不漏（与 offset 结果一致）、分页边界、next_cursor 语义、非法游标 400
- 导出上限：EXPORT_MAX_ROWS 命中 400（先 COUNT 不拉全表）、0 表示不限制
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core.keyset import (
    CURSOR_INVALID,
    CURSOR_TOO_LONG,
    build_keyset_where,
    decode_cursor,
    encode_cursor,
)
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def owner(db):
    u = User(username="keyset_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth(client, owner):
    r = client.post("/api/v1/accounts/auth/login", json={"login": "keyset_owner", "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="KeysetWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="游标表")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for order, (name, ftype) in enumerate([("名称", "text"), ("数量", "number")]):
        f = DataField(table_id=dt.id, name=name, field_type=ftype, order=order)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    # 数量刻意重复：验证 id 兜底让翻页稳定
    for i, amount in enumerate([5, 5, 3, 5, 1, 3]):
        rec.create_row(engine, dt, {"名称": f"行{i}", "数量": amount}, db=db)
    return dt


# ── 游标编解码 ───────────────────────────────────────


class TestCursorCodec:
    def test_roundtrip(self):
        values = [3, "行3", 1]
        assert decode_cursor(encode_cursor(values)) == values

    def test_invalid_cursor(self):
        for bad in ("", "not-base64!!", "Zm9v", "eyJ2IjogW119"):
            with pytest.raises(ValueError) as exc:
                decode_cursor(bad)
            assert str(exc.value) in {CURSOR_INVALID, CURSOR_TOO_LONG}

    def test_too_long(self):
        with pytest.raises(ValueError, match="长度超出"):
            decode_cursor(encode_cursor(list(range(20))))


# ── keyset WHERE ─────────────────────────────────────


class TestKeysetWhere:
    def _rows_after(self, db, table, sorts, cursor) -> list[int]:
        engine = db.get_bind()
        sa = ddl.get_reflected_table(engine, table.db_table_name)
        stmt = sa.select().where(build_keyset_where(table, sa, sorts, cursor))
        from cndb.plugins.tables.services.core.query import compile_sorts

        if sorts:
            stmt = stmt.order_by(*compile_sorts(table, sa, sorts))
        else:
            stmt = stmt.order_by(sa.c.id)
        with engine.connect() as conn:
            return [int(r[0]) for r in conn.execute(stmt).all()]

    def test_id_cursor(self, db, table):
        engine = db.get_bind()
        sa = ddl.get_reflected_table(engine, table.db_table_name)
        with engine.connect() as conn:
            ids = [int(r[0]) for r in conn.execute(select(sa.c.id).order_by(sa.c.id)).all()]
        after_second = self._rows_after(db, table, None, [ids[1]])
        assert after_second == ids[2:]

    def test_single_sort_asc(self, db, table):
        sorts = [{"field_name": "数量", "direction": "asc"}]
        rows = rec.list_rows(db.get_bind(), table, sorts=sorts, limit=None, db=db)[0]
        first_page = rows[:3]
        last = first_page[-1]
        after = self._rows_after(db, table, sorts, [last["数量"], last["id"]])
        assert after == [int(r["id"]) for r in rows[3:]]

    def test_mixed_directions(self, db, table):
        sorts = [
            {"field_name": "数量", "direction": "desc"},
            {"field_name": "名称", "direction": "asc"},
        ]
        rows = rec.list_rows(db.get_bind(), table, sorts=sorts, limit=None, db=db)[0]
        last = rows[2]
        after = self._rows_after(db, table, sorts, [last["数量"], last["名称"], last["id"]])
        assert after == [int(r["id"]) for r in rows[3:]]

    def test_null_sort_value_rejected(self, db, table):
        engine = db.get_bind()
        sa = ddl.get_reflected_table(engine, table.db_table_name)
        row = rec.create_row(engine, table, {"名称": "空数量"}, db=db)
        del row
        with pytest.raises(ValueError, match="空排序值"):
            build_keyset_where(table, sa, [{"field_name": "数量", "direction": "asc"}], [None, 1])

    def test_wrong_cursor_length_rejected(self, db, table):
        engine = db.get_bind()
        sa = ddl.get_reflected_table(engine, table.db_table_name)
        with pytest.raises(ValueError):
            build_keyset_where(table, sa, None, [1, 2])

    def test_virtual_field_rejected(self, db, table):
        engine = db.get_bind()
        sa = ddl.get_reflected_table(engine, table.db_table_name)
        field = next(f for f in table.fields if f.name == "名称")
        field.field_type = "formula"
        db.commit()
        db.refresh(table)
        with pytest.raises(ValueError, match="没有物理列"):
            build_keyset_where(table, sa, [{"field_name": "名称", "direction": "asc"}], ["x", 1])


# ── 接口：翻页不重不漏 ───────────────────────────────


class TestKeysetApi:
    def _page(self, client, ws, table, auth, *, after=None, limit=2, sorts=None):
        params = {"limit": limit}
        if after:
            params["after"] = after
        if sorts:
            import json as _json

            params["sorts"] = _json.dumps(sorts)
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records",
            params=params,
            headers=auth,
        )
        assert r.status_code == 200, r.text
        return r.json()

    def test_walk_all_pages_without_dup_or_missing(self, client, db, ws, table, auth):
        seen: list[int] = []
        cursor: str | None = None
        for _ in range(10):
            body = self._page(client, ws, table, auth, after=cursor)
            seen.extend(int(row["id"]) for row in body["rows"])
            cursor = body.get("next_cursor")
            if not cursor:
                break
        total = rec.count_rows(db.get_bind(), table, db=db)
        assert len(seen) == len(set(seen)) == int(total)

    def test_sorted_walk_matches_offset(self, client, db, ws, table, auth):
        sorts = [{"field_name": "数量", "direction": "desc"}]
        offset_rows = rec.list_rows(db.get_bind(), table, sorts=sorts, limit=None, db=db)[0]
        expected = [int(r["id"]) for r in offset_rows]

        seen: list[int] = []
        cursor: str | None = None
        for _ in range(10):
            body = self._page(client, ws, table, auth, after=cursor, sorts=sorts)
            seen.extend(int(row["id"]) for row in body["rows"])
            cursor = body.get("next_cursor")
            if not cursor:
                break
        assert seen == expected

    def test_last_page_has_no_cursor(self, client, db, ws, table, auth):
        body = self._page(client, ws, table, auth, limit=100)
        assert body["next_cursor"] is None

    def test_invalid_cursor_400(self, client, ws, table, auth):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records",
            params={"after": "not-a-cursor"},
            headers=auth,
        )
        assert r.status_code == 400

    def test_cursor_with_wrong_length_400(self, client, ws, table, auth):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records",
            params={"after": encode_cursor([1, 2, 3])},
            headers=auth,
        )
        assert r.status_code == 400


# ── 导出上限 ─────────────────────────────────────────


class TestExportCap:
    def test_export_over_cap_400(self, client, db, ws, table, auth, monkeypatch):
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "EXPORT_MAX_ROWS", 2)
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/export?format=csv",
            headers=auth,
        )
        assert r.status_code == 400
        assert "EXPORT_MAX_ROWS" in r.text

    def test_export_within_cap_ok(self, client, db, ws, table, auth, monkeypatch):
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "EXPORT_MAX_ROWS", 100)
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/export?format=csv",
            headers=auth,
        )
        assert r.status_code == 200

    def test_zero_cap_means_unlimited(self, client, ws, table, auth, monkeypatch):
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "EXPORT_MAX_ROWS", 0)
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/export?format=csv",
            headers=auth,
        )
        assert r.status_code == 200


class TestKeysetCursorInList:
    """网格翻页用到的最小保证：游标查询的 total 与 next_cursor 语义稳定（需求 0148）。"""

    def test_cursor_page_reports_total_and_next_cursor(self, client, db, ws, table, auth):
        url = f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records"
        first = client.get(url, params={"limit": 2}, headers=auth).json()
        assert first["next_cursor"]
        total = first["total"]

        second = client.get(url, params={"limit": 2, "after": first["next_cursor"]}, headers=auth).json()
        assert second["total"] == total
        assert {row["id"] for row in first["rows"]} & {row["id"] for row in second["rows"]} == set()

    def test_last_cursor_page_has_no_next(self, client, db, ws, table, auth):
        url = f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records"
        body = client.get(url, params={"limit": 100}, headers=auth).json()
        assert body["next_cursor"] is None
