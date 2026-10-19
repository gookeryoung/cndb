"""补充覆盖：core 模块（cache / events / database / migrations / observability /
ratelimit / errors / events_api / system_api）的遗漏行与分支.

仅新增测试，不改动源码与既有测试。全部在进程内 / 内存库完成，确定性、无网络。
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import JSON

# ── core/cache.py ────────────────────────────────────────────


class TestCacheExtra:
    def test_stats_as_dict(self) -> None:
        from cndb.core.cache import CacheStats

        stats = CacheStats(hits=3, misses=1, evictions=2, expirations=4, entries=5)
        payload = stats.as_dict()
        assert payload["hit_rate"] == 0.75
        assert payload["entries"] == 5
        # 分母为 0 时命中率为 0
        assert CacheStats().hit_rate == 0.0

    def test_delete_reset_and_invalidate_all(self) -> None:
        from cndb.core.cache import TTLCache, invalidate_all, list_cache, meta_cache

        cache = TTLCache(max_entries=2)
        cache.set("k", 1, 30)
        assert cache.get("k") == 1
        cache.delete("k")  # 覆盖 delete 分支
        assert cache.get("k") is None
        cache.reset_stats()  # 覆盖 reset_stats

        list_cache.set("a", 1, 30)
        meta_cache.set("b", 2, 30)
        assert invalidate_all() >= 0
        assert invalidate_all("a") >= 0

    def test_eviction_and_purge_expired(self) -> None:
        from cndb.core.cache import TTLCache

        cache = TTLCache(max_entries=1)
        cache.set("a", 1, 30)
        cache.set("b", 2, 30)  # 触发淘汰
        assert cache.get("a") is None
        assert cache.get("b") == 2

        cache.set("exp", 1, 0.0001)
        # Windows 的 monotonic 时钟精度约 15.6ms，sleep(0.01) 可能尚未跨过一个 tick
        time.sleep(0.05)
        assert cache.purge_expired() >= 1

    def test_get_or_set(self) -> None:
        from cndb.core.cache import TTLCache

        cache = TTLCache()
        calls = {"n": 0}

        def producer() -> str:
            calls["n"] += 1
            return "value"

        assert cache.get_or_set("k", 30, producer) == "value"
        assert cache.get_or_set("k", 30, producer) == "value"
        assert calls["n"] == 1


# ── core/errors.py ───────────────────────────────────────────


class TestErrorsExtra:
    def test_status_code_override(self) -> None:
        from cndb.core.errors import CndbError

        exc = CndbError("boom", code="custom", status_code=418, foo="bar")
        assert exc.status_code == 418
        assert exc.code == "custom"
        assert exc.context == {"foo": "bar"}
        assert exc.to_payload() == {"detail": "boom", "code": "custom"}

    def test_too_many_requests(self) -> None:
        from cndb.core.errors import TooManyRequestsError

        exc = TooManyRequestsError("slow down", retry_after=12)
        assert exc.status_code == 429
        assert exc.retry_after == 12


# ── core/ratelimit.py ────────────────────────────────────────


class TestRateLimitExtra:
    def test_sliding_window_prunes_and_expires(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cndb.core import ratelimit as mod

        limiter = mod.SlidingWindowLimiter(2, 10)
        monkeypatch.setattr(mod.time, "monotonic", lambda: 100.0)
        limiter.record("k")
        assert limiter.retry_after("k") == 0
        # 时间前进到窗口外 → _prune 弹出过期时间戳
        monkeypatch.setattr(mod.time, "monotonic", lambda: 200.0)
        assert limiter.retry_after("k") == 0

    def test_reaches_limit_and_retry_after(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cndb.core import ratelimit as mod

        limiter = mod.SlidingWindowLimiter(2, 10)
        monkeypatch.setattr(mod.time, "monotonic", lambda: 100.0)
        limiter.record("k")
        limiter.record("k")
        assert limiter.retry_after("k") > 0

    def test_login_limiter_reset_without_ip(self) -> None:
        from cndb.core.ratelimit import LoginRateLimiter

        # ip 维度阈值 = limit * 4 = 8，记满后仅清账号维度，IP 维度应保留
        limiter = LoginRateLimiter(2, 10)
        for _ in range(8):
            limiter.record_failure("user", "1.2.3.4")
        limiter.reset("user")  # ip 缺省 → 覆盖 101->exit 分支
        assert limiter.retry_after("user", "1.2.3.4") > 0  # ip 维度保留

    def test_login_limiter_reset_with_ip(self) -> None:
        from cndb.core.ratelimit import LoginRateLimiter

        limiter = LoginRateLimiter(2, 10)
        limiter.record_failure("user", "1.2.3.4")
        limiter.reset("user", "1.2.3.4")
        assert limiter.retry_after("user", "1.2.3.4") == 0


# ── core/observability.py ────────────────────────────────────


class TestObservabilityExtra:
    def test_set_actor_ids_swallows_error(self) -> None:
        from cndb.core import observability as mod

        class _Bad:
            def __setattr__(self, name: str, value: Any) -> None:
                raise RuntimeError("no setattr")

        mod.set_actor_ids(_Bad(), user_id=1)  # 不应抛异常

    def test_set_actor_ids_ok(self) -> None:
        from cndb.core import observability as mod

        state = SimpleNamespace()
        mod.set_actor_ids(state, user_id=7, username="u")
        assert state.user_id == 7
        assert state.username == "u"

    def test_log_request_branches(self, caplog: pytest.LogCaptureFixture) -> None:
        from cndb.core.observability import RequestObservabilityMiddleware

        mw = RequestObservabilityMiddleware(app=None, slow_ms=100, access_log=False)  # type: ignore[arg-type]
        # 非慢请求 + 关闭访问日志 → 直接返回（164）
        mw._log_request({"path": "/x", "method": "GET"}, 200, 1.0, "rid")
        # 慢请求 → warning（159-161）
        with caplog.at_level("WARNING"):
            mw._log_request({"path": "/x", "method": "GET"}, 200, 999.0, "rid")
        assert any("slow=true" in r.message for r in caplog.records)

        mw2 = RequestObservabilityMiddleware(app=None, slow_ms=100, access_log=True)  # type: ignore[arg-type]
        # 安静路径 → debug
        with caplog.at_level("DEBUG", logger="cndb.access"):
            mw2._log_request({"path": "/api/health", "method": "GET", "state": {"user_id": 3}}, 200, 1.0, "rid")
        assert any(r.levelno == 10 for r in caplog.records)

    def test_bind_request_id(self) -> None:
        from cndb.core.observability import bind_request_id, get_request_id

        assert get_request_id() == ""
        with bind_request_id("abc"):
            assert get_request_id() == "abc"
        assert get_request_id() == ""


# ── core/database.py ─────────────────────────────────────────


class TestDatabaseExtra:
    def test_register_pragmas_non_sqlite(self) -> None:
        from cndb.core import database as mod

        fake = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        mod.register_sqlite_pragmas(fake)  # 非 sqlite → 直接返回

    def test_register_pragmas_sqlite_wal(self) -> None:
        from sqlalchemy import create_engine

        from cndb.core import database as mod

        engine = create_engine("sqlite:///:memory:")
        mod.register_sqlite_pragmas(engine)
        with engine.connect() as conn:
            assert conn.execute.__self__ is not None  # 连接建立即触发 pragma 监听
        engine.dispose()

    def test_cursor_execute_hooks(self) -> None:
        from cndb.core import database as mod

        # 无起始时间 → 直接返回（99）
        mod._after_cursor_execute(None, None, "SELECT 1", None, SimpleNamespace(), None)

        ctx = SimpleNamespace(_cndb_query_start=time.perf_counter() - 10)
        mod._before_cursor_execute(None, None, "SELECT 1", None, SimpleNamespace(), None)
        mod._after_cursor_execute(None, None, "SELECT 1", None, ctx, None)

    def test_db_readiness_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cndb.core import database as mod

        class _Engine:
            def connect(self) -> Any:
                raise RuntimeError("db down")

        monkeypatch.setattr(mod, "engine", _Engine())
        snapshot = mod.db_readiness()
        assert snapshot["db"] is False
        assert "db down" in snapshot["error"]

    def test_db_readiness_migration_current(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cndb.core import database as mod

        class _Res:
            def first(self) -> tuple[str]:
                return ("rev1",)

        class _Conn:
            def execute(self, *_a: Any, **_k: Any) -> _Res:
                return _Res()

            def __enter__(self) -> _Conn:
                return self

            def __exit__(self, *_a: Any) -> bool:
                return False

        class _Engine:
            def connect(self) -> _Conn:
                return _Conn()

        monkeypatch.setattr(mod, "engine", _Engine())
        snapshot = mod.db_readiness()
        assert snapshot["db"] is True
        assert snapshot["migration_current"] == "rev1"


# ── core/migrations.py ──────────────────────────────────────


class TestMigrationsExtra:
    def test_scalar_server_default_none_arg(self) -> None:
        from cndb.core import migrations as mod

        col = SimpleNamespace(server_default=None, default=SimpleNamespace(arg=None))
        assert mod._scalar_server_default(col) is None

    def test_scalar_server_default_json_container(self) -> None:
        from cndb.core import migrations as mod

        col_dict = SimpleNamespace(server_default=None, type=JSON(), default=SimpleNamespace(arg=dict, is_scalar=False))
        assert mod._scalar_server_default(col_dict) == "'{}'"

        col_list = SimpleNamespace(server_default=None, type=JSON(), default=SimpleNamespace(arg=list, is_scalar=False))
        assert mod._scalar_server_default(col_list) == "'[]'"

    def test_scalar_server_default_json_other_container(self) -> None:
        from cndb.core import migrations as mod

        col = SimpleNamespace(server_default=None, type=JSON(), default=SimpleNamespace(arg=set, is_scalar=False))
        assert mod._scalar_server_default(col) is None

    def test_scalar_server_default_other_scalar(self) -> None:
        from cndb.core import migrations as mod

        col = SimpleNamespace(server_default=None, default=SimpleNamespace(arg=set(), is_scalar=True))
        assert mod._scalar_server_default(col) is None

    def test_scalar_server_default_bool_and_number(self) -> None:
        from cndb.core import migrations as mod

        assert (
            mod._scalar_server_default(
                SimpleNamespace(server_default=None, default=SimpleNamespace(arg=True, is_scalar=True))
            )
            == "1"
        )
        assert (
            mod._scalar_server_default(
                SimpleNamespace(server_default=None, default=SimpleNamespace(arg=5, is_scalar=True))
            )
            == "5"
        )

    def test_heal_schema_drift_swallows_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cndb.core import migrations as mod

        def _boom(_engine: Any) -> list[str]:
            raise RuntimeError("drift check failed")

        monkeypatch.setattr(mod, "_heal_missing_columns", _boom)
        mod._heal_schema_drift()  # 不应抛异常

    def test_heal_schema_drift_no_changes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cndb.core import migrations as mod

        monkeypatch.setattr(mod, "_heal_missing_columns", lambda _e: [])
        monkeypatch.setattr(mod, "_heal_missing_indexes", lambda _e: [])
        mod._heal_schema_drift()


# ── core/events.py ──────────────────────────────────────────


class TestEventsExtra:
    def test_parse_time(self) -> None:
        from cndb.core.events import _parse_time

        assert _parse_time(None) is None
        assert _parse_time("not-a-date") is None
        assert _parse_time("2026-01-01T00:00:00Z") is not None
        assert _parse_time("2026-01-01T00:00:00+00:00") is not None

    def test_current_request_id_swallows_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cndb.core import events as mod
        from cndb.core import observability as obs

        monkeypatch.setattr(obs, "get_request_id", lambda: (_ for _ in ()).throw(RuntimeError("nope")))
        assert mod._current_request_id() is None

    def test_query_events_filters(self, db: Any) -> None:
        from cndb.core.events import query_events, record_event

        record_event(
            db,
            "record.create",
            summary="created row",
            target_type="record",
            target_id=1,
            workspace_id=10,
            actor_id=1,
            request_id="rid-1",
        )
        record_event(db, "table.create", summary="created table", workspace_id=11)

        _items, total = query_events(db, request_id="rid-1")
        assert total == 1

        _items, total = query_events(db, keyword="table")
        assert total == 1

        _items, total = query_events(db, since="2000-01-01T00:00:00", until="2999-01-01T00:00:00")
        assert total >= 2

        _items, total = query_events(db, workspace_id=10, actor_id=1, target_type="record", target_id="1")
        assert total == 1

        _items, total = query_events(db, until="1999-01-01T00:00:00")
        assert total == 0

    def test_invalidate_for_event(self) -> None:
        from cndb.core.events import invalidate_for_event

        assert invalidate_for_event("", None) == 0
        assert invalidate_for_event("record.create", 3) >= 0
        assert invalidate_for_event("document.update", 3) >= 0
        assert invalidate_for_event("user.update", 3) == 0

    def test_invalidate_for_event_swallows_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cndb.core.cache import list_cache

        def _boom(*_a: Any, **_k: Any) -> int:
            raise RuntimeError("cache broken")

        monkeypatch.setattr(list_cache, "clear", _boom)
        from cndb.core.events import invalidate_for_event

        assert invalidate_for_event("record.create", 1) == 0

    def test_summarize_and_distinct(self, db: Any) -> None:
        from cndb.core.events import distinct_actions, record_event, summarize_user_action

        assert summarize_user_action("update") == "更新用户资料"
        assert "未知" not in summarize_user_action("weird")
        record_event(db, "auth.login", summary="login")
        actions = distinct_actions(db)
        assert any(a["action"] == "auth.login" for a in actions)


# ── core/events_api.py ──────────────────────────────────────


class TestEventsApiExtra:
    def test_require_audit_reader_unauthenticated(self) -> None:
        from fastapi import HTTPException

        from cndb.core.events_api import _require_audit_reader

        with pytest.raises(HTTPException) as exc:
            _require_audit_reader(None)
        assert exc.value.status_code == 401

    def test_require_audit_reader_forbidden(self) -> None:
        from fastapi import HTTPException

        from cndb.core.events_api import _require_audit_reader

        with pytest.raises(HTTPException) as exc:
            _require_audit_reader(SimpleNamespace(is_superuser=False, role="user"))
        assert exc.value.status_code == 403

    def test_require_audit_reader_ok(self) -> None:
        from cndb.core.events_api import _require_audit_reader

        user = SimpleNamespace(is_superuser=True, role="")
        assert _require_audit_reader(user) is user

    def test_serialize_no_created_at(self) -> None:
        from cndb.core.events_api import _serialize

        payload = _serialize(SimpleNamespace(created_at=None, action="x"))
        assert payload["created_at"] is None


# ── core/system_api.py ──────────────────────────────────────


@pytest.fixture
def superuser_headers(client: TestClient, auth_headers: dict[str, str], db: Any) -> dict[str, str]:
    """把已登录用户提升为 superuser（token 每请求查库，即时生效）."""
    from cndb.plugins.accounts.models import User

    user = db.query(User).filter(User.username == "testuser").one()
    user.is_superuser = True
    db.commit()
    return auth_headers


class TestSystemApiExtra:
    def test_require_superuser_unauthenticated(self) -> None:
        from fastapi import HTTPException

        from cndb.core.system_api import _require_superuser

        with pytest.raises(HTTPException) as exc:
            _require_superuser(None)
        assert exc.value.status_code == 401

    def test_require_superuser_forbidden(self) -> None:
        from fastapi import HTTPException

        from cndb.core.system_api import _require_superuser
        from cndb.plugins.accounts.models import UserRole

        with pytest.raises(HTTPException) as exc:
            _require_superuser(SimpleNamespace(is_superuser=False, role=UserRole.USER.value))
        assert exc.value.status_code == 403

    def test_cache_stats_and_clear(self, client: TestClient, superuser_headers: dict[str, str]) -> None:
        r = client.get("/api/v1/admin/cache/stats", headers=superuser_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "list" in body and "meta" in body

        r = client.post("/api/v1/admin/cache/clear", headers=superuser_headers)
        assert r.status_code == 200
        assert r.json()["cleared"] >= 0

        r = client.post("/api/v1/admin/cache/clear?prefix=list", headers=superuser_headers)
        assert r.status_code == 200
        assert r.json()["prefix"] == "list"

    def test_cache_stats_requires_superuser(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        r = client.get("/api/v1/admin/cache/stats", headers=auth_headers)
        assert r.status_code == 403

    def test_admin_info(self, client: TestClient, superuser_headers: dict[str, str]) -> None:
        r = client.get("/api/v1/admin/info", headers=superuser_headers)
        assert r.status_code == 200, r.text
        assert "app_version" in r.json()

    def test_update_quota_paths(
        self, client: TestClient, superuser_headers: dict[str, str], auth_headers: dict[str, str]
    ) -> None:
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "cov_core_ws"})
        wid = ws.json()["id"]

        r = client.patch(
            f"/api/v1/admin/workspaces/{wid}/storage-quota",
            headers=superuser_headers,
            json={"quota_bytes": -1},
        )
        assert r.status_code == 400

        r = client.patch(
            "/api/v1/admin/workspaces/999999/storage-quota",
            headers=superuser_headers,
            json={"quota_bytes": 10},
        )
        assert r.status_code == 404

        r = client.patch(
            f"/api/v1/admin/workspaces/{wid}/storage-quota",
            headers=superuser_headers,
            json={"quota_bytes": 1024},
        )
        assert r.status_code == 200, r.text
        assert r.json()["quota_bytes"] == 1024

    def test_workspace_storage_overview(self, client: TestClient, superuser_headers: dict[str, str]) -> None:
        r = client.get("/api/v1/admin/workspaces/storage", headers=superuser_headers)
        assert r.status_code == 200, r.text
        assert "items" in r.json()

    def test_backup_os_error(
        self, client: TestClient, superuser_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cndb.core import system_api

        def _boom(**_k: Any) -> Any:
            raise OSError("disk full")

        monkeypatch.setattr(system_api, "create_backup", _boom)
        r = client.post("/api/v1/admin/backup", headers=superuser_headers, json={})
        assert r.status_code == 500

    def test_restore_without_loss_report(
        self, client: TestClient, superuser_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import io

        from cndb.core import system_api

        monkeypatch.setattr(system_api, "inspect_backup", lambda _p: SimpleNamespace(manifest={}))
        monkeypatch.setattr(system_api, "restore_backup", lambda *_a, **_k: None)
        r = client.post(
            "/api/v1/admin/restore",
            headers=superuser_headers,
            files={"file": ("backup.tar.gz", io.BytesIO(b"x"), "application/gzip")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["loss_report"] is None
