"""直编并发冲突检测测试（ADR 0140）—— `_rev` 懒补 / `_etag` / `If-Match` / 各写路径自增.

覆盖卡片约束：
- C1 带 `If-Match` 时版本不一致 → 409 且不落库；不带时行为与改造前一致
- C2 409 走统一错误体（`detail` + `code=record_stale`）
- C3 所有写路径（直编 / 批量 / 导入 upsert / 恢复 / 合并）都让 `_rev` 递增
- C6 `_rev` 懒补（旧表首次读写即补齐、幂等）
- C7 `_rev` / `_etag` 不进导出
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import inspect, select, text

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services import transfer
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def owner(db):
    u = User(username="concurrency_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth_owner_api(client, owner):
    r = client.post("/api/v1/accounts/auth/login", json={"login": owner.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def ws_owner(db, owner):
    w = Workspace(name="ConcurrencyWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws_owner):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws_owner.id, name="并发表")
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
    return dt


# ── 纯函数：ETag 解析 ───────────────────────────────


class TestEtagHelpers:
    def test_row_etag_format(self):
        assert rec.row_etag(7, 3) == "v1-7-3"

    def test_parse_if_match(self):
        assert rec.parse_if_match(None) is None
        assert rec.parse_if_match("v1-12-0") == (12, 0)
        assert rec.parse_if_match('"v1-12-4"') == (12, 4)
        assert rec.parse_if_match("*") == (-1, -1)

    def test_parse_if_match_invalid(self):
        with pytest.raises(ValueError):
            rec.parse_if_match("12")
        with pytest.raises(ValueError):
            rec.parse_if_match("v1-x-1")


# ── C6：懒补列 ─────────────────────────────────────


class TestRowVersionColumn:
    def test_created_table_has_rev(self, db, table):
        cols = {c["name"] for c in inspect(db.get_bind()).get_columns(table.db_table_name)}
        assert "_rev" in cols

    def test_lazy_add_on_legacy_table(self, db, table):
        """模拟旧库缺列：DROP 后重建不带 _rev 的表，首次写入即补齐且幂等."""
        engine = db.get_bind()
        with engine.begin() as conn:
            conn.execute(text(f'ALTER TABLE "{table.db_table_name}" DROP COLUMN "_rev"'))
        ddl.invalidate_reflected_table(table.db_table_name)

        cols = {c["name"] for c in inspect(engine).get_columns(table.db_table_name)}
        assert "_rev" not in cols

        row = rec.create_row(engine, table, {"名称": "旧库行"}, db=db)
        assert row is not None
        cols = {c["name"] for c in inspect(engine).get_columns(table.db_table_name)}
        assert "_rev" in cols

        # 幂等：再调不报错、不重复 ALTER
        assert ddl.ensure_row_version_column(engine, table) is False

    def test_etag_in_row_payload_and_rev_hidden(self, db, table):
        engine = db.get_bind()
        row = rec.create_row(engine, table, {"名称": "A", "数量": 1})
        assert row["_etag"] == rec.row_etag(row["id"], 0)
        assert "_rev" not in row
        assert "_etag" in rec.get_row(engine, table, row["id"], db=db)


# ── C1 / C2：乐观并发 ───────────────────────────────


class TestOptimisticConcurrencyService:
    def test_expected_rev_hit_bumps_rev(self, db, table):
        engine = db.get_bind()
        row = rec.create_row(engine, table, {"名称": "A"})
        updated = rec.update_row(engine, table, row["id"], {"名称": "B"}, db=db, expected_rev=0)
        assert updated is not None
        assert updated["_etag"] == rec.row_etag(row["id"], 1)

    def test_expected_rev_miss_raises_and_does_not_write(self, db, table):
        from cndb.core.errors import ConflictError

        engine = db.get_bind()
        row = rec.create_row(engine, table, {"名称": "A"})
        rec.update_row(engine, table, row["id"], {"名称": "B"}, db=db, expected_rev=0)

        with pytest.raises(ConflictError) as exc:
            rec.update_row(engine, table, row["id"], {"名称": "C"}, db=db, expected_rev=0)
        assert exc.value.status_code == 409
        assert exc.value.code == "record_stale"
        assert rec.get_row(engine, table, row["id"], db=db)["名称"] == "B"

    def test_without_expected_rev_behaviour_unchanged(self, db, table):
        engine = db.get_bind()
        row = rec.create_row(engine, table, {"名称": "A"})
        updated = rec.update_row(engine, table, row["id"], {"名称": "B"}, db=db)
        assert updated["名称"] == "B"
        # 版本仍然单调递增（I2），只是不做校验
        assert updated["_etag"] == rec.row_etag(row["id"], 1)

    def test_expected_rev_on_missing_row_returns_none(self, db, table):
        assert rec.update_row(db.get_bind(), table, 99999, {"名称": "x"}, db=db, expected_rev=0) is None


class TestOptimisticConcurrencyAPI:
    def _create(self, client, ws_owner, table, auth) -> dict:
        r = client.post(
            f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records",
            json={"values": {"名称": "A"}},
            headers=auth,
        )
        assert r.status_code == 201
        return r.json()

    def test_if_match_hit(self, client, db, ws_owner, table, auth_owner_api):
        row = self._create(client, ws_owner, table, auth_owner_api)
        r = client.patch(
            f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records/{row['id']}",
            json={"values": {"名称": "B"}},
            headers={**auth_owner_api, "If-Match": row["_etag"]},
        )
        assert r.status_code == 200
        assert r.json()["名称"] == "B"
        assert r.json()["_etag"] == rec.row_etag(row["id"], 1)

    def test_if_match_stale_returns_409_with_code(self, client, db, ws_owner, table, auth_owner_api):
        row = self._create(client, ws_owner, table, auth_owner_api)
        url = f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records/{row['id']}"
        assert (
            client.patch(
                url, json={"values": {"名称": "B"}}, headers={**auth_owner_api, "If-Match": row["_etag"]}
            ).status_code
            == 200
        )

        r = client.patch(url, json={"values": {"名称": "C"}}, headers={**auth_owner_api, "If-Match": row["_etag"]})
        assert r.status_code == 409
        body = r.json()
        assert body["code"] == "record_stale"
        assert "detail" in body
        # 不落库
        latest = client.get(url, headers=auth_owner_api).json()
        assert latest["名称"] == "B"

    def test_invalid_if_match_400(self, client, ws_owner, table, auth_owner_api):
        row = self._create(client, ws_owner, table, auth_owner_api)
        r = client.patch(
            f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records/{row['id']}",
            json={"values": {"名称": "B"}},
            headers={**auth_owner_api, "If-Match": "not-an-etag"},
        )
        assert r.status_code == 400

    def test_without_if_match_still_works(self, client, ws_owner, table, auth_owner_api):
        row = self._create(client, ws_owner, table, auth_owner_api)
        r = client.patch(
            f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records/{row['id']}",
            json={"values": {"名称": "B"}},
            headers=auth_owner_api,
        )
        assert r.status_code == 200


# ── C3：各写路径都让版本递增 ─────────────────────────


class TestRevBumpedByEveryWritePath:
    def _rev(self, db, table, row_id: int) -> int:
        sa = ddl.get_reflected_table(db.get_bind(), table.db_table_name)
        with db.get_bind().connect() as conn:
            return int(conn.execute(select(sa.c._rev).where(sa.c.id == row_id)).scalar() or 0)

    def test_bulk_update_bumps(self, db, table):
        engine = db.get_bind()
        ids = [rec.create_row(engine, table, {"名称": f"R{i}", "数量": 0})["id"] for i in range(2)]
        assert rec.bulk_update(engine, table, ids, {"数量": 5}, db=db) == 2
        assert all(self._rev(db, table, rid) == 1 for rid in ids)

    def test_bulk_update_rows_bumps(self, db, table):
        engine = db.get_bind()
        ids = [rec.create_row(engine, table, {"名称": f"R{i}", "数量": 0})["id"] for i in range(2)]
        rec.bulk_update_rows(engine, table, [{"row_id": rid, "values": {"数量": 9}} for rid in ids], db=db)
        assert all(self._rev(db, table, rid) == 1 for rid in ids)

    def test_trash_and_restore_bump(self, db, table):
        engine = db.get_bind()
        row = rec.create_row(engine, table, {"名称": "A"})
        rec.trash_rows(engine, table, [row["id"]], db=db)
        assert self._rev(db, table, row["id"]) == 1
        rec.restore_rows(engine, table, [row["id"]], db=db)
        assert self._rev(db, table, row["id"]) == 2

    def test_stale_etag_after_bulk_update_conflicts(self, client, db, ws_owner, table, auth_owner_api):
        """C3 联合场景：别人批量改过之后，编辑器持有的旧 etag 提交必须 409."""
        row = client.post(
            f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records",
            json={"values": {"名称": "A", "数量": 0}},
            headers=auth_owner_api,
        ).json()
        r = client.post(
            f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records/bulk-update",
            json={"row_ids": [row["id"]], "values": {"数量": 3}},
            headers=auth_owner_api,
        )
        assert r.status_code == 200

        stale = client.patch(
            f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records/{row['id']}",
            json={"values": {"名称": "B"}},
            headers={**auth_owner_api, "If-Match": row["_etag"]},
        )
        assert stale.status_code == 409


# ── C7：导出不含版本键 ───────────────────────────────


def test_export_excludes_rev_and_etag():
    rows = [{"id": 1, "名称": "A", "_etag": "v1-1-2", "_rev": 2, "_trashed": False, "_trashed_at": None}]
    csv_text = transfer.export_rows_to_csv(rows, columns=["名称"])
    assert "_etag" not in csv_text and "_rev" not in csv_text
    assert json.loads(transfer.export_rows_to_json(rows)) == [{"id": 1, "名称": "A"}]


# ── 边界：只改 link 也参与版本校验 ───────────────────


def test_link_only_update_bumps_and_conflicts(db, ws_owner):
    """只传 link 字段（无物理列）时同样自增 `_rev` 并参与 If-Match 校验."""
    from cndb.core.errors import ConflictError

    target = DataTable(workspace_id=ws_owner.id, name="并发目标表")
    target.ensure_db_name()
    db.add(target)
    db.flush()
    tf = DataField(table_id=target.id, name="名称", field_type="text", order=0)
    tf.ensure_db_name()
    db.add(tf)
    db.commit()
    db.refresh(target)
    ddl.create_table(db.get_bind(), target)
    t_row = rec.create_row(db.get_bind(), target, {"名称": "T"})

    src = DataTable(workspace_id=ws_owner.id, name="并发源表")
    src.ensure_db_name()
    db.add(src)
    db.flush()
    link = DataField(table_id=src.id, name="引用", field_type="link", order=0)
    link.ensure_db_name()
    db.add(link)
    db.commit()
    db.refresh(src)
    link = next(f for f in src.fields if f.field_type == "link")
    link.config = {**(link.config or {}), "target_table_id": target.id, "display_field_id": tf.id}
    db.commit()
    ddl.create_table(db.get_bind(), src)

    engine = db.get_bind()
    row = rec.create_row(engine, src, {"引用": [t_row["id"]]}, db=db)
    assert row["_etag"] == rec.row_etag(row["id"], 0)

    updated = rec.update_row(engine, src, row["id"], {"引用": []}, db=db, expected_rev=0)
    assert updated is not None
    assert updated["_etag"] == rec.row_etag(row["id"], 1)

    with pytest.raises(ConflictError):
        rec.update_row(engine, src, row["id"], {"引用": [t_row["id"]]}, db=db, expected_rev=0)
