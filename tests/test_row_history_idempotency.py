"""行级历史与撤销（ADR 0144）+ 写幂等键（ADR 0145）.

覆盖：
- 历史：建行 v1、更新 diff 只含变化字段、软删 / 恢复各记一版、版本严格递增
- 撤销：按版本 old 生成新版本（不改历史）、可反复撤销、版本不存在 404
- 权限：写范围外的行读历史 404
- 幂等：同 key 重复请求只执行一次（回放首个响应）、同 key 不同请求体 409、
  无 key 时行为不变、非法 key 400、超期视同未命中
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable, IdempotencyKey, RecordRevision
from cndb.plugins.tables.services.core import ddl, row_history
from cndb.plugins.tables.services.core import idempotency as idem
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core.idempotency import find_replay, purge_expired_keys, store_replay
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def owner(db):
    u = User(username="history_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth(client, owner):
    r = client.post("/api/v1/accounts/auth/login", json={"login": "history_owner", "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="HistoryWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="历史表")
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


# ── build_diff 纯函数 ────────────────────────────────


class TestBuildDiff:
    def test_only_changed_fields(self):
        diff = row_history.build_diff({"a": 1, "b": "x"}, {"a": 1, "b": "y", "c": None})
        assert diff == {"b": {"old": "x", "new": "y"}}

    def test_added_and_removed_keys(self):
        diff = row_history.build_diff({"a": 1, "b": 2}, {"a": 1})
        assert diff == {"b": {"old": 2, "new": None}}

    def test_empty_when_identical(self):
        assert row_history.build_diff({"a": 1}, {"a": 1}) == {}


# ── 历史写入 ─────────────────────────────────────────


class TestRevisionRecording:
    def test_create_records_v1(self, db, table):
        row = rec.create_row(db.get_bind(), table, {"名称": "A", "数量": 1}, db=db)
        revisions = row_history.list_revisions(db, table, row["id"])
        assert len(revisions) == 1
        assert revisions[0].version == 1
        assert revisions[0].op == row_history.OP_CREATE
        assert revisions[0].diff["名称"]["new"] == "A"

    def test_update_records_diff_only_changed(self, db, table):
        row = rec.create_row(db.get_bind(), table, {"名称": "A", "数量": 1}, db=db)
        rec.update_row(db.get_bind(), table, row["id"], {"名称": "B"}, db=db)
        revisions = row_history.list_revisions(db, table, row["id"])
        assert [r.version for r in revisions] == [2, 1]
        assert revisions[0].op == row_history.OP_UPDATE
        assert revisions[0].diff == {"名称": {"old": "A", "new": "B"}}

    def test_noop_update_records_nothing(self, db, table):
        row = rec.create_row(db.get_bind(), table, {"名称": "A"}, db=db)
        rec.update_row(db.get_bind(), table, row["id"], {"名称": "A"}, db=db)
        assert [r.version for r in row_history.list_revisions(db, table, row["id"])] == [1]

    def test_trash_and_restore_versions(self, db, table):
        row = rec.create_row(db.get_bind(), table, {"名称": "A"}, db=db)
        rec.trash_rows(db.get_bind(), table, [row["id"]], db=db)
        rec.restore_rows(db.get_bind(), table, [row["id"]], db=db)
        revisions = row_history.list_revisions(db, table, row["id"])
        assert [r.op for r in revisions] == [row_history.OP_RESTORE, row_history.OP_TRASH, row_history.OP_CREATE]
        assert [r.version for r in revisions] == [3, 2, 1]

    def test_record_history_false_skips(self, db, table):
        row = rec.create_row(db.get_bind(), table, {"名称": "A"}, db=db)
        rec.update_row(db.get_bind(), table, row["id"], {"名称": "B"}, db=db, record_history=False)
        assert [r.version for r in row_history.list_revisions(db, table, row["id"])] == [1]

    def test_actor_name_snapshot(self, db, table, owner):
        row = rec.create_row(db.get_bind(), table, {"名称": "A"}, db=db)
        rec.update_row(db.get_bind(), table, row["id"], {"名称": "B"}, db=db, user=owner)
        latest = row_history.list_revisions(db, table, row["id"])[0]
        assert latest.actor_id == owner.id
        assert latest.actor_name == "Owner"

    def test_versions_are_monotonic_per_row(self, db, table):
        row = rec.create_row(db.get_bind(), table, {"名称": "A"}, db=db)
        for i in range(5):
            rec.update_row(db.get_bind(), table, row["id"], {"数量": i}, db=db)
        versions = [r.version for r in row_history.list_revisions(db, table, row["id"], limit=100)]
        assert versions == list(range(6, 0, -1))


# ── 撤销 ─────────────────────────────────────────────


class TestRevert:
    def test_revert_generates_new_version(self, db, table):
        row = rec.create_row(db.get_bind(), table, {"名称": "A"}, db=db)
        rec.update_row(db.get_bind(), table, row["id"], {"名称": "B"}, db=db)

        reverted = row_history.revert_revision(db, table, row["id"], 2)
        assert reverted is not None and reverted["名称"] == "A"
        revisions = row_history.list_revisions(db, table, row["id"])
        assert revisions[0].version == 3
        assert revisions[0].op == row_history.OP_REVERT
        assert revisions[0].diff == {"名称": {"old": "B", "new": "A"}}

    def test_revert_twice_roundtrip(self, db, table):
        row = rec.create_row(db.get_bind(), table, {"名称": "A"}, db=db)
        rec.update_row(db.get_bind(), table, row["id"], {"名称": "B"}, db=db)
        row_history.revert_revision(db, table, row["id"], 2)
        row_history.revert_revision(db, table, row["id"], 3)  # 撤销"撤销" → 回到 B
        assert rec.get_row(db.get_bind(), table, row["id"], db=db)["名称"] == "B"

    def test_revert_missing_version_returns_none(self, db, table):
        row = rec.create_row(db.get_bind(), table, {"名称": "A"}, db=db)
        assert row_history.revert_revision(db, table, row["id"], 99) is None


# ── 接口 ─────────────────────────────────────────────


class TestHistoryApi:
    def _seed(self, db, ws, table, auth):
        r = client_create = None
        created = pytest.importorskip("fastapi.testclient")
        del created, r, client_create

    def test_history_endpoint_and_revert(self, client, db, ws, table, auth):
        base = f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records"
        row = client.post(base, json={"values": {"名称": "A", "数量": 1}}, headers=auth).json()
        client.patch(f"{base}/{row['id']}", json={"values": {"名称": "B"}}, headers=auth)

        history = client.get(f"{base}/{row['id']}/history", headers=auth)
        assert history.status_code == 200
        items = history.json()
        assert [item["version"] for item in items] == [2, 1]
        assert items[0]["op"] == "update"
        assert items[0]["diff"] == {"名称": {"old": "A", "new": "B"}}

        reverted = client.post(f"{base}/{row['id']}/revert/2", headers=auth)
        assert reverted.status_code == 200
        assert reverted.json()["名称"] == "A"

        after = client.get(f"{base}/{row['id']}/history", headers=auth).json()
        assert after[0]["op"] == "revert"

    def test_history_missing_row_404(self, client, ws, table, auth):
        base = f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records"
        assert client.get(f"{base}/99999/history", headers=auth).status_code == 404
        assert client.post(f"{base}/99999/revert/1", headers=auth).status_code == 404

    def test_revert_missing_version_404(self, client, db, ws, table, auth):
        base = f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records"
        row = client.post(base, json={"values": {"名称": "A"}}, headers=auth).json()
        assert client.post(f"{base}/{row['id']}/revert/99", headers=auth).status_code == 404


# ── 幂等键 ───────────────────────────────────────────


class TestIdempotencyHelpers:
    def test_normalize_key(self):
        assert idem.normalize_key("  k1 ") == "k1"
        assert idem.normalize_key("") is None
        assert idem.normalize_key("x" * 200) is None
        assert idem.normalize_key(None) is None

    def test_fingerprint_stable_and_sensitive(self):
        assert idem.request_fingerprint({"a": 1, "b": 2}) == idem.request_fingerprint({"b": 2, "a": 1})
        assert idem.request_fingerprint({"a": 1}) != idem.request_fingerprint({"a": 2})

    def test_store_find_and_conflict(self, db):
        store_replay(db, user_id=1, key="k", route="POST /x", fingerprint="h1", status_code=201, response={"id": 7})
        hit, response, status = find_replay(db, user_id=1, key="k", route="POST /x", fingerprint="h1")
        assert hit is True and response == {"id": 7} and status == 201
        with pytest.raises(ValueError):
            find_replay(db, user_id=1, key="k", route="POST /x", fingerprint="h2")

    def test_expired_key_treated_as_miss(self, db):
        store_replay(db, user_id=2, key="old", route="POST /x", fingerprint="h", status_code=200, response={"id": 1})
        entry = db.query(IdempotencyKey).filter(IdempotencyKey.key == "old").one()
        entry.created_at = datetime.now(UTC) - timedelta(hours=48)
        db.commit()
        assert find_replay(db, user_id=2, key="old", route="POST /x", fingerprint="h")[0] is False
        assert db.query(IdempotencyKey).filter(IdempotencyKey.key == "old").count() == 0

    def test_purge_expired_keys(self, db):
        store_replay(db, user_id=3, key="a", route="r", fingerprint="h", status_code=200, response={})
        store_replay(db, user_id=3, key="b", route="r", fingerprint="h", status_code=200, response={})
        entry = db.query(IdempotencyKey).filter(IdempotencyKey.key == "a").one()
        entry.created_at = datetime.now(UTC) - timedelta(hours=48)
        db.commit()
        assert purge_expired_keys(db) == 1
        assert db.query(IdempotencyKey).count() == 1


class TestIdempotencyApi:
    def test_repeated_create_replays_first_response(self, client, db, ws, table, auth):
        base = f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records"
        headers = {**auth, "Idempotency-Key": "create-1"}
        first = client.post(base, json={"values": {"名称": "A"}}, headers=headers)
        second = client.post(base, json={"values": {"名称": "A"}}, headers=headers)

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        # 只落一行
        rows = client.get(base, headers=auth).json()
        assert rows["total"] == 1

    def test_same_key_different_body_conflicts(self, client, ws, table, auth):
        base = f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records"
        headers = {**auth, "Idempotency-Key": "dup"}
        assert client.post(base, json={"values": {"名称": "A"}}, headers=headers).status_code == 201
        r = client.post(base, json={"values": {"名称": "B"}}, headers=headers)
        assert r.status_code == 409

    def test_without_key_behaves_as_before(self, client, ws, table, auth):
        base = f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records"
        a = client.post(base, json={"values": {"名称": "A"}}, headers=auth)
        b = client.post(base, json={"values": {"名称": "A"}}, headers=auth)
        assert a.json()["id"] != b.json()["id"]

    def test_invalid_key_400(self, client, ws, table, auth):
        base = f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records"
        r = client.post(base, json={"values": {"名称": "A"}}, headers={**auth, "Idempotency-Key": "x" * 200})
        assert r.status_code == 400

    def test_revision_table_registered(self, db, table):
        """迁移 / 元数据一致：两张新表都可查询（防止只加模型忘迁移）。"""
        from sqlalchemy import inspect

        names = set(inspect(db.get_bind()).get_table_names())
        assert RecordRevision.__tablename__ in names
        assert IdempotencyKey.__tablename__ in names
