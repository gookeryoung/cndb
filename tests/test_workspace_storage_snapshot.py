"""工作区存储用量快照（ADR 0024）.

覆盖三块：

- 服务层：快照 upsert / 批量读 / 懒计算 / 乐观累加 / 脏集合 / 单点失败隔离；
- 接口层：管理台只读快照（**不触发统计**）、刷新端点异步投递、配额调整读快照；
- 后台线程：启停、无定时轮次时不自动轮转、脏唤醒触发一轮。
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from cndb.core.storage_refresh import StorageSnapshotRefresher
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import WorkspaceStorageSnapshot
from cndb.plugins.workspaces.services import storage_snapshot as snapshot_service
from cndb.plugins.workspaces.services.storage_snapshot import (
    RefreshReport,
    bump_used_bytes,
    mark_dirty,
    pop_dirty,
    read_snapshot,
    read_snapshots,
    refresh_all,
    refresh_workspace,
    reset_state,
    snapshot_age_seconds,
    snapshot_used_bytes,
)

TABLES = "/api/v1/workspaces/{ws}/tables"
STORAGE = "/api/v1/admin/workspaces/storage"


@pytest.fixture(autouse=True)
def _reset_snapshot_state():
    """进程内脏集合是模块级状态：每个用例前后清空，避免互相污染."""
    reset_state()
    yield
    reset_state()


@pytest.fixture
def superuser_headers(client: TestClient, auth_headers: dict[str, str], db) -> dict[str, str]:
    user = db.query(User).filter(User.username == "testuser").one()
    user.is_superuser = True
    db.commit()
    return auth_headers


def _create_workspace(client: TestClient, auth: dict[str, str], name: str) -> int:
    r = client.post("/api/v1/workspaces", json={"name": name}, headers=auth)
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _create_table_with_rows(client: TestClient, auth: dict[str, str], ws_id: int, values: list[str]) -> int:
    r = client.post(TABLES.format(ws=ws_id), json={"name": "用量表", "description": ""}, headers=auth)
    assert r.status_code == 201, r.text
    tid = int(r.json()["id"])
    r = client.post(
        f"{TABLES.format(ws=ws_id)}/{tid}/fields",
        json={"name": "名称", "field_type": "text", "order": 0},
        headers=auth,
    )
    assert r.status_code in (200, 201), r.text
    for value in values:
        r = client.post(
            f"{TABLES.format(ws=ws_id)}/{tid}/records",
            json={"values": {"名称": value}},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text
    return tid


class TestSnapshotService:
    def test_refresh_creates_and_updates_snapshot(self, client: TestClient, auth_headers: dict[str, str], db):
        ws_id = _create_workspace(client, auth_headers, "snap-ws")
        _create_table_with_rows(client, auth_headers, ws_id, ["甲", "乙"])

        first = refresh_workspace(db, ws_id)
        db.commit()
        assert first.used_bytes > 0
        assert first.duration_ms is not None and first.duration_ms >= 0
        assert read_snapshot(db, ws_id) is not None

        # 再刷一次覆盖旧值（upsert，不新增行）
        second = refresh_workspace(db, ws_id)
        db.commit()
        assert db.query(WorkspaceStorageSnapshot).filter_by(workspace_id=ws_id).count() == 1
        assert second.used_bytes == first.used_bytes

    def test_read_snapshots_batches_and_skips_missing(self, client: TestClient, auth_headers: dict[str, str], db):
        ws_a = _create_workspace(client, auth_headers, "batch-a")
        ws_b = _create_workspace(client, auth_headers, "batch-b")
        refresh_workspace(db, ws_a)
        db.commit()

        found = read_snapshots(db, [ws_a, ws_b])
        assert set(found) == {ws_a}
        assert read_snapshots(db, []) == {}

    def test_snapshot_used_bytes_lazy_fills_matching_metric(self, client: TestClient, auth_headers: dict[str, str], db):
        ws_id = _create_workspace(client, auth_headers, "lazy-ws")
        _create_table_with_rows(client, auth_headers, ws_id, ["懒计算"])

        # 无快照 + lazy=False → None（调用方据此显示「统计中」）
        assert snapshot_used_bytes(db, ws_id, lazy=False) is None
        assert read_snapshot(db, ws_id) is None

        used = snapshot_used_bytes(db, ws_id, lazy=True)
        assert used is not None and used > 0
        # 懒计算已落库，第二次直接读快照
        assert read_snapshot(db, ws_id) is not None
        assert snapshot_used_bytes(db, ws_id, lazy=False) == used

    def test_bump_used_bytes_accumulates_and_clamps(self, client: TestClient, auth_headers: dict[str, str], db):
        ws_id = _create_workspace(client, auth_headers, "bump-ws")
        refresh_workspace(db, ws_id)
        db.commit()
        base = read_snapshot(db, ws_id).used_bytes

        bump_used_bytes(db, ws_id, 1024)
        db.commit()
        assert read_snapshot(db, ws_id).used_bytes == base + 1024

        bump_used_bytes(db, ws_id, -(base + 4096))
        db.commit()
        assert read_snapshot(db, ws_id).used_bytes == 0

    def test_bump_without_snapshot_does_not_create(self, client: TestClient, auth_headers: dict[str, str], db):
        ws_id = _create_workspace(client, auth_headers, "bump-nosnap")
        bump_used_bytes(db, ws_id, 2048)
        db.commit()
        assert read_snapshot(db, ws_id) is None

    def test_dirty_set_dedupes(self):
        mark_dirty(3)
        mark_dirty(3)
        mark_dirty(7)
        dirty, all_flag = pop_dirty()
        assert dirty == {3, 7}
        assert all_flag is False
        # 取过一次即清空
        assert pop_dirty() == (set(), False)

    def test_mark_dirty_none_requests_full_refresh(self):
        mark_dirty(None)
        assert pop_dirty() == (set(), True)

    def test_refresh_all_only_dirty_limits_scope(
        self, client: TestClient, auth_headers: dict[str, str], db, monkeypatch
    ):
        ws_a = _create_workspace(client, auth_headers, "dirty-a")
        ws_b = _create_workspace(client, auth_headers, "dirty-b")
        seen: list[int] = []
        original = snapshot_service.workspace_storage_bytes

        def counting(inner_db, workspace_id):
            seen.append(workspace_id)
            return original(inner_db, workspace_id)

        monkeypatch.setattr(snapshot_service, "workspace_storage_bytes", counting)
        mark_dirty(ws_a)
        report = refresh_all(db, only_dirty=True)
        assert report.refreshed == 1
        assert seen == [ws_a]
        assert read_snapshot(db, ws_b) is None

    def test_refresh_all_isolates_single_failure(
        self, client: TestClient, auth_headers: dict[str, str], db, monkeypatch
    ):
        ws_bad = _create_workspace(client, auth_headers, "fail-a")
        ws_ok = _create_workspace(client, auth_headers, "fail-b")
        original = snapshot_service.workspace_storage_bytes

        def flaky(inner_db, workspace_id):
            if workspace_id == ws_bad:
                raise RuntimeError("统计炸了")
            return original(inner_db, workspace_id)

        monkeypatch.setattr(snapshot_service, "workspace_storage_bytes", flaky)
        report = refresh_all(db)
        assert report.failed == 1
        assert report.refreshed >= 1
        # 失败的工作区留空（下一轮重试），其余正常落库
        assert read_snapshot(db, ws_bad) is None
        assert read_snapshot(db, ws_ok) is not None

    def test_snapshot_age_seconds(self, client: TestClient, auth_headers: dict[str, str], db):
        ws_id = _create_workspace(client, auth_headers, "age-ws")
        assert snapshot_age_seconds(None) is None
        snap = refresh_workspace(db, ws_id)
        db.commit()
        age = snapshot_age_seconds(snap)
        assert age is not None and 0 <= age < 60


class TestAdminApi:
    def test_list_reads_snapshot_without_computing(
        self, client: TestClient, superuser_headers: dict[str, str], db, monkeypatch
    ):
        ws_id = _create_workspace(client, superuser_headers, "api-ws")
        _create_table_with_rows(client, superuser_headers, ws_id, ["甲"])
        refresh_all(db)

        def explode(*_args, **_kwargs):
            raise AssertionError("管理台列表不得在请求内做全量统计")

        monkeypatch.setattr(snapshot_service, "workspace_storage_bytes", explode)
        r = client.get(STORAGE, headers=superuser_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        item = next(it for it in body["items"] if it["workspace_id"] == ws_id)
        assert item["used_bytes"] > 0
        assert item["computed_at"]
        assert item["age_seconds"] is not None and item["age_seconds"] >= 0
        assert item["is_stale"] is False
        assert body["refresh_interval_seconds"] >= 0
        assert body["pending_workspace_count"] == 0

    def test_list_reports_pending_when_no_snapshot(self, client: TestClient, superuser_headers: dict[str, str]):
        ws_id = _create_workspace(client, superuser_headers, "pending-ws")
        r = client.get(STORAGE, headers=superuser_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        item = next(it for it in body["items"] if it["workspace_id"] == ws_id)
        # 尚未统计：返回 null（前端显示「统计中」），不拿 0 冒充
        assert item["used_bytes"] is None
        assert item["computed_at"] is None
        assert item["is_stale"] is True
        assert body["pending_workspace_count"] >= 1

    def test_refresh_endpoint_accepts_and_marks_dirty(
        self, client: TestClient, superuser_headers: dict[str, str], db, monkeypatch
    ):
        ws_id = _create_workspace(client, superuser_headers, "refresh-ws")
        called: list[list[int]] = []
        monkeypatch.setattr(
            snapshot_service, "request_refresh", lambda ids=None: called.append(ids or []) or (ids or [])
        )

        r = client.post(f"{STORAGE}/refresh", json={"workspace_ids": [ws_id]}, headers=superuser_headers)
        assert r.status_code == 202, r.text
        assert r.json() == {"status": "accepted", "workspace_ids": [ws_id], "all": False}
        assert called == [[ws_id]]

        # 省略 body = 全部工作区
        r = client.post(f"{STORAGE}/refresh", headers=superuser_headers)
        assert r.status_code == 202, r.text
        assert r.json()["all"] is True

    def test_refresh_endpoint_rejects_unknown_workspace(self, client: TestClient, superuser_headers: dict[str, str]):
        r = client.post(f"{STORAGE}/refresh", json={"workspace_ids": [99999]}, headers=superuser_headers)
        assert r.status_code == 404, r.text

    def test_refresh_endpoint_requires_superuser(self, client: TestClient, auth_headers: dict[str, str]):
        r = client.post(f"{STORAGE}/refresh", json={}, headers=auth_headers)
        assert r.status_code == 403, r.text

    def test_quota_update_returns_snapshot_usage(self, client: TestClient, superuser_headers: dict[str, str], db):
        ws_id = _create_workspace(client, superuser_headers, "quota-ws")
        _create_table_with_rows(client, superuser_headers, ws_id, ["配额"])

        r = client.patch(
            f"{STORAGE.replace('/storage', '')}/{ws_id}/storage-quota",
            json={"quota_bytes": 2048},
            headers=superuser_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # 快照缺失 → 懒计算一次（不返回 null），配额按提交值
        assert body["quota_bytes"] == 2048
        assert body["used_bytes"] is not None and body["used_bytes"] > 0


class TestRefresherThread:
    def test_start_stop_and_no_interval(self, monkeypatch):
        calls: list[bool] = []

        def fake_refresh_all(db=None, *, only_dirty=False):
            calls.append(only_dirty)
            return RefreshReport(refreshed=0, failed=0, duration_ms=0)

        monkeypatch.setattr(snapshot_service, "refresh_all", fake_refresh_all)
        refresher = StorageSnapshotRefresher(interval_seconds=0, startup_delay_seconds=0)
        assert refresher.start() is True
        assert refresher.start() is False  # 幂等
        try:
            _wait_until(lambda: len(calls) >= 1)
            # interval=0：不会自动轮转
            time.sleep(0.15)
            assert len(calls) == 1
        finally:
            refresher.stop()
        assert refresher.running is False
        assert refresher._thread is None

    def test_dirty_wakes_thread(self, monkeypatch):
        calls: list[bool] = []

        def fake_refresh_all(db=None, *, only_dirty=False):
            calls.append(only_dirty)
            return RefreshReport(refreshed=1, failed=0, duration_ms=1, workspace_ids=(1,))

        monkeypatch.setattr(snapshot_service, "refresh_all", fake_refresh_all)
        refresher = StorageSnapshotRefresher(interval_seconds=0, startup_delay_seconds=0)
        refresher.start()
        try:
            _wait_until(lambda: len(calls) >= 1)
            baseline = len(calls)
            mark_dirty(42)
            _wait_until(lambda: len(calls) > baseline)
            assert len(calls) > baseline
        finally:
            refresher.stop()


def _wait_until(predicate, timeout: float = 3.0) -> None:
    """轮询等待条件成立（后台线程无回调可用）."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("等待后台线程状态超时")
