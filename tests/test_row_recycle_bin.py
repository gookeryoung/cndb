"""行回收站测试（ADR 0139）——软删统一口径 / 回收站列表 / 恢复幂等 / 彻底删除 / lookup 冗余列.

覆盖卡片约束：
- C1 批量删除改软删（不再物理 DELETE），link 关系保留
- C2 `trashed=none|only|include` 三态，回收站行带删除时间与操作人
- C3 恢复幂等
- C4 彻底删除只接受已删行，非已删行 400、越界 404
- C6 软删 / 恢复都重算消费方 lookup 冗余列
- C9 权限：viewer 恢复 / 彻底删除 403
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def owner(db):
    u = User(username="recycle_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws_owner(db, owner):
    w = Workspace(name="RecycleWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def auth_owner_api(client, owner):
    r = client.post("/api/v1/accounts/auth/login", json={"login": owner.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_table(db, ws, name: str, fields: list[tuple[str, str]]) -> DataTable:
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name=name)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for order, (fname, ftype) in enumerate(fields):
        f = DataField(table_id=dt.id, name=fname, field_type=ftype, order=order)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    return dt


@pytest.fixture
def table(db, ws_owner):
    return _make_table(db, ws_owner, "回收站表", [("名称", "text"), ("数量", "number")])


def _row_count(db, dt: DataTable) -> int:
    sa = ddl.get_reflected_table(db.get_bind(), dt.db_table_name)
    with db.get_bind().connect() as conn:
        return int(conn.execute(select(func.count(sa.c.id))).scalar() or 0)


# ── C1：批量删除改软删 ──────────────────────────────


class TestBulkDeleteSoft:
    def test_bulk_delete_keeps_rows_and_links(self, db, table):
        engine = db.get_bind()
        ids = [rec.create_row(engine, table, {"名称": "A", "数量": 1})["id"] for _ in range(3)]

        assert rec.bulk_delete(engine, table, ids, db=db) == 3

        # 物理行仍在，只是打了软删标记
        assert _row_count(db, table) == 3
        sa = ddl.get_reflected_table(engine, table.db_table_name)
        with engine.connect() as conn:
            trashed = [int(r[0]) for r in conn.execute(select(sa.c.id).where(sa.c._trashed.is_(True))).all()]
        assert sorted(trashed) == sorted(ids)
        # 默认列表不可见，回收站可见
        assert rec.list_rows(engine, table, db=db)[1] == 0
        only_rows, only_total = rec.list_rows(engine, table, db=db, only_trashed=True)
        assert only_total == 3
        assert all(r["_trashed_at"] is not None for r in only_rows)

    def test_bulk_delete_link_relation_preserved(self, db, ws_owner):
        """软删不清 link 关系：恢复后关联自动可用（对比硬删会清关联）."""
        target = _make_table(db, ws_owner, "目标表", [("名称", "text")])
        engine = db.get_bind()
        t_row = rec.create_row(engine, target, {"名称": "T"})

        src = _make_table(db, ws_owner, "源表", [("引用", "link")])
        link_field = next(f for f in src.fields if f.field_type == "link")
        link_field.config = {
            **(link_field.config or {}),
            "target_table_id": target.id,
            "display_field_id": target.fields[0].id,
        }
        db.commit()
        db.refresh(src)
        link_field = next(f for f in src.fields if f.field_type == "link")

        row = rec.create_row(engine, src, {"引用": [t_row["id"]]}, db=db)
        assert rec.load_links(engine, link_field, [row["id"]])[row["id"]] == [t_row["id"]]

        rec.bulk_delete(engine, src, [row["id"]], db=db)
        assert rec.load_links(engine, link_field, [row["id"]])[row["id"]] == [t_row["id"]]

        rec.restore_rows(engine, src, [row["id"]], db=db)
        assert rec.get_row(engine, src, row["id"], db=db) is not None

    def test_single_and_bulk_same_semantics(self, db, table):
        engine = db.get_bind()
        one = rec.create_row(engine, table, {"名称": "单"})["id"]
        many = [rec.create_row(engine, table, {"名称": f"批{i}"})["id"] for i in range(2)]

        assert rec.trash_row(engine, table, one, db=db) is True
        assert rec.bulk_delete(engine, table, many, db=db) == 2

        sa = ddl.get_reflected_table(engine, table.db_table_name)
        with engine.connect() as conn:
            trashed = int(conn.execute(select(func.count(sa.c.id)).where(sa.c._trashed.is_(True))).scalar() or 0)
        assert trashed == 3


# ── C6：软删 / 恢复重算 lookup 冗余列 ───────────────


def test_trash_and_restore_resync_lookup_columns(db, ws_owner):
    """软删目标行后，消费方 `_lk_*` 失效；恢复后回填（ADR 0131 下推口径不失真）."""
    target = _make_table(db, ws_owner, "被引用表", [("名称", "text")])
    engine = db.get_bind()
    t_row = rec.create_row(engine, target, {"名称": "小王"})

    consumer = _make_table(db, ws_owner, "引用表", [("关联", "link"), ("取值", "lookup")])
    link_field = next(f for f in consumer.fields if f.field_type == "link")
    link_field.config = {
        **(link_field.config or {}),
        "target_table_id": target.id,
        "display_field_id": target.fields[0].id,
    }
    lookup_field = next(f for f in consumer.fields if f.field_type == "lookup")
    lookup_field.config = {
        **(lookup_field.config or {}),
        "via_link_field_id": link_field.id,
        "source_field_id": target.fields[0].id,
    }
    db.commit()
    db.refresh(consumer)
    ddl.ensure_lookup_columns(engine, consumer)

    row = rec.create_row(engine, consumer, {"关联": [t_row["id"]]}, db=db)
    sa = ddl.get_reflected_table(engine, consumer.db_table_name)
    lk_col = next(c for c in sa.columns if c.name.startswith("_lk_")).name

    def lk_value() -> object:
        with engine.connect() as conn:
            return conn.execute(select(sa.c[lk_col]).where(sa.c.id == row["id"])).scalar()

    assert lk_value() not in (None, "")

    rec.trash_rows(engine, target, [t_row["id"]], db=db)
    assert lk_value() in (None, "")

    rec.restore_rows(engine, target, [t_row["id"]], db=db)
    assert lk_value() not in (None, "")


# ── C2 / C3 / C4 / C9：接口层 ────────────────────────


class TestRecycleBinAPI:
    def _seed(self, db, table) -> list[int]:
        engine = db.get_bind()
        return [rec.create_row(engine, table, {"名称": f"行{i}", "数量": i})["id"] for i in range(3)]

    def test_trashed_param_three_modes(self, client, db, ws_owner, table, auth_owner_api):
        ids = self._seed(db, table)
        base = f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records"
        rec.bulk_delete(db.get_bind(), table, ids[:2], db=db)

        r = client.get(base, headers=auth_owner_api)
        assert r.status_code == 200
        assert r.json()["total"] == 1

        r = client.get(f"{base}?trashed=only", headers=auth_owner_api)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        for row in body["rows"]:
            assert row["_trashed_at"] is not None
            # 删除操作人：出接口层时记录的是 actor（这里 0 行是由后台直接调 rec 删的，可能为 None）
            assert "_trashed_by" in row
            assert "_etag" in row

        r = client.get(f"{base}?trashed=include", headers=auth_owner_api)
        assert r.status_code == 200
        assert r.json()["total"] == 3

    def test_trashed_param_invalid_400(self, client, ws_owner, table, auth_owner_api):
        r = client.get(
            f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records?trashed=bogus",
            headers=auth_owner_api,
        )
        assert r.status_code == 400

    def test_restore_is_idempotent(self, client, db, ws_owner, table, auth_owner_api):
        (rid,) = self._seed(db, table)[:1]
        rec.trash_row(db.get_bind(), table, rid, db=db)
        url = f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records/{rid}/restore"

        assert client.post(url, headers=auth_owner_api).status_code == 200
        assert client.post(url, headers=auth_owner_api).status_code == 200  # 幂等
        row = client.get(
            f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records/{rid}",
            headers=auth_owner_api,
        )
        assert row.status_code == 200

    def test_batch_restore(self, client, db, ws_owner, table, auth_owner_api):
        ids = self._seed(db, table)
        rec.bulk_delete(db.get_bind(), table, ids, db=db)
        r = client.post(
            f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records/restore",
            json={"row_ids": ids},
            headers=auth_owner_api,
        )
        assert r.status_code == 200
        assert r.json()["restored"] == len(ids)

    def test_purge_only_trashed(self, client, db, ws_owner, table, auth_owner_api):
        ids = self._seed(db, table)
        base = f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records"

        # 活动行不允许彻底删除（整批 400，且不做部分成功）
        r = client.post(f"{base}/purge", json={"row_ids": ids[:1]}, headers=auth_owner_api)
        assert r.status_code == 400
        assert _row_count(db, table) == 3

        rec.trash_rows(db.get_bind(), table, ids[:2], db=db)
        r = client.post(f"{base}/purge", json={"row_ids": ids[:2]}, headers=auth_owner_api)
        assert r.status_code == 200
        assert r.json()["purged"] == 2
        assert _row_count(db, table) == 1

        # 单行彻底删除
        rec.trash_row(db.get_bind(), table, ids[2], db=db)
        r = client.post(f"{base}/{ids[2]}/purge", headers=auth_owner_api)
        assert r.status_code == 200
        assert r.json()["purged"] is True
        assert _row_count(db, table) == 0

    def test_purge_missing_id_404(self, client, db, ws_owner, table, auth_owner_api):
        r = client.post(
            f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records/purge",
            json={"row_ids": [99999]},
            headers=auth_owner_api,
        )
        assert r.status_code == 404

    def test_viewer_cannot_restore_or_purge(self, client, db, ws_owner, table, auth_owner_api):
        viewer = User(username="recycle_viewer", nickname="V")
        viewer.set_password("passw0rd")
        db.add(viewer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws_owner.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        login = client.post("/api/v1/accounts/auth/login", json={"login": "recycle_viewer", "password": "passw0rd"})
        viewer_auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

        (rid,) = self._seed(db, table)[:1]
        rec.trash_row(db.get_bind(), table, rid, db=db)
        base = f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records"

        assert client.post(f"{base}/{rid}/restore", headers=viewer_auth).status_code in (403, 404)
        assert client.post(f"{base}/purge", json={"row_ids": [rid]}, headers=viewer_auth).status_code in (403, 404)
        # 物理行未被动过（仍 3 行：1 行已软删 + 2 行活动）
        assert _row_count(db, table) == 3


# ── 边界：空 / 超量 / 不存在 / 未在回收站 ─────────────


class TestRecycleBinBoundaries:
    def test_purge_empty_ids_400(self, client, ws_owner, table, auth_owner_api):
        base = f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records"
        r = client.post(f"{base}/purge", json={"row_ids": []}, headers=auth_owner_api)
        # 载荷层 min_length=1 → 422；服务层空列表 → 400，两者都拒绝
        assert r.status_code in (400, 422)

    def test_purge_too_many_ids_400(self, db, client, ws_owner, table, auth_owner_api):
        from cndb.plugins.tables.routers.records import MAX_PURGE_ROWS, _ensure_all_trashed

        class _User:
            id = 1

        with pytest.raises(Exception) as exc:
            _ensure_all_trashed(db, table, list(range(1, MAX_PURGE_ROWS + 2)), _User())
        assert getattr(exc.value, "status_code", None) == 400

    def test_restore_missing_row_404(self, client, ws_owner, table, auth_owner_api):
        r = client.post(
            f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records/99999/restore",
            headers=auth_owner_api,
        )
        assert r.status_code == 404

    def test_purge_records_not_in_trash_returns_zero(self, db, table):
        """服务层：未在回收站的行不会被物理删除（返回 0）."""
        engine = db.get_bind()
        row = rec.create_row(engine, table, {"名称": "活动行"})
        assert rec.purge_rows(engine, table, [row["id"]], db=db) == 0
        assert rec.get_row(engine, table, row["id"], db=db) is not None

    def test_trash_and_restore_ignore_out_of_scope_ids(self, db, table):
        engine = db.get_bind()
        assert rec.trash_rows(engine, table, [], db=db) == 0
        assert rec.trash_rows(engine, table, [99999], db=db) == 0
        assert rec.restore_rows(engine, table, [99999], db=db) == 0
        assert rec.purge_rows(engine, table, [99999], db=db) == 0

    def test_trashed_only_reports_actor_name(self, client, db, ws_owner, table, auth_owner_api, owner):
        """经接口删除的行，回收站列表要能给出删除操作人（读 tables_auditlog）."""
        created = client.post(
            f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records",
            json={"values": {"名称": "待删"}},
            headers=auth_owner_api,
        ).json()
        assert (
            client.delete(
                f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records/{created['id']}",
                headers=auth_owner_api,
            ).status_code
            == 204
        )

        r = client.get(
            f"/api/v1/workspaces/{ws_owner.id}/tables/{table.id}/records?trashed=only",
            headers=auth_owner_api,
        )
        assert r.status_code == 200
        row = next(row for row in r.json()["rows"] if row["id"] == created["id"])
        assert row["_trashed_by"] == owner.id
        assert row["_trashed_by_name"] == owner.username


# ── 写范围 / 空集合 / 幂等清理 ───────────────────────


class TestRecycleBinScope:
    def test_trash_rows_with_write_scope(self, db, table, owner):
        engine = db.get_bind()
        row = rec.create_row(engine, table, {"名称": "范围内"})
        assert rec.trash_rows(engine, table, [row["id"]], db=db, user=owner, enforce_row_rules=True) == 1
        # 再删一次（已软删）→ 0
        assert rec.trash_rows(engine, table, [row["id"]], db=db, user=owner, enforce_row_rules=True) == 0
        # 恢复后再彻底删除两次：第二次 0
        rec.restore_rows(engine, table, [row["id"]], db=db)
        assert rec.purge_rows(engine, table, [row["id"]], db=db) == 0  # 活动行不删
        rec.trash_rows(engine, table, [row["id"]], db=db)
        assert rec.purge_rows(engine, table, [row["id"]], db=db) == 1
        assert rec.purge_rows(engine, table, [row["id"]], db=db) == 0

    def test_trash_actors_helper_empty_and_missing(self, db, table):
        from cndb.plugins.tables.routers.records import _trash_actors

        assert _trash_actors(db, int(table.id), []) == {}
        assert _trash_actors(db, int(table.id), [99999]) == {}
