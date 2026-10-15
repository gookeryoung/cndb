"""可观测性测试：health liveness/readiness 拆分 + 慢查询日志."""

from __future__ import annotations

import logging
import time

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import text

from cndb.api.deps import get_request_id
from cndb.core import database as dbmod
from cndb.core.observability import (
    RequestObservabilityMiddleware,
    bind_request_id,
    configure_logging,
    set_actor_ids,
)
from cndb.core.observability import get_request_id as current_request_id

pytestmark = pytest.mark.usefixtures("db")


class TestHealthSplit:
    """liveness 与 readiness 分离."""

    def test_liveness_no_dependency_probe(self, client):
        """/api/health 仅表明进程存活，200 即可."""
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_readiness_ok(self, client):
        """DB 可达时 readiness 返回 200 并带迁移版本."""
        r = client.get("/api/health/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["db"] is True

    def test_readiness_unready_returns_503(self, client, monkeypatch):
        """DB 不可达时 readiness 返回 503（部署层摘除信号）."""

        def broken() -> dict[str, object]:
            return {"db": False, "migration_current": None, "error": "模拟不可达"}

        monkeypatch.setattr(dbmod, "db_readiness", broken)
        r = client.get("/api/health/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "unready"
        assert body["db"] is False


class TestSlowQueryLog:
    """慢查询结构化日志."""

    def test_slow_query_emits_warning(self, monkeypatch, caplog):
        """超过阈值的 SQL 执行应记 warning 日志（阈值置 0 强制触发）."""
        monkeypatch.setattr(dbmod, "SLOW_QUERY_SECONDS", 0.0)
        with caplog.at_level(logging.WARNING, logger="cndb.core.database"), dbmod.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        assert any("慢查询" in rec.message for rec in caplog.records)

    def test_fast_query_no_warning(self, monkeypatch, caplog):
        """阈值内（设为极大值）的 SQL 不产生慢查询日志."""
        monkeypatch.setattr(dbmod, "SLOW_QUERY_SECONDS", 1e9)
        with caplog.at_level(logging.WARNING, logger="cndb.core.database"), dbmod.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        assert not any("慢查询" in rec.message for rec in caplog.records)


class TestRequestIdMiddleware:
    """请求级观测：X-Request-ID + 访问耗时日志（中间件在 core/observability.py）."""

    @staticmethod
    def _app(*, slow_ms: int = 500, access_log: bool = True) -> FastAPI:
        app = FastAPI()
        app.add_middleware(RequestObservabilityMiddleware, slow_ms=slow_ms, access_log=access_log)

        @app.get("/ping")
        def ping() -> dict[str, str]:
            return {"ok": "1"}

        @app.get("/slow")
        def slow() -> dict[str, str]:
            time.sleep(0.03)
            return {"ok": "1"}

        @app.get("/whoami")
        def whoami(request: Request) -> dict[str, object]:
            set_actor_ids(request.state, user_id=7, username="tester")
            return {"dep_rid": get_request_id(), "ctx_rid": current_request_id()}

        return app

    def test_generates_and_echoes_request_id(self):
        client = TestClient(self._app())
        rid = client.get("/ping").headers["x-request-id"]
        assert rid and len(rid) == 32  # uuid4 hex

        assert client.get("/ping", headers={"X-Request-ID": "trace-abc"}).headers["x-request-id"] == "trace-abc"

    def test_dependency_sees_same_request_id(self):
        client = TestClient(self._app())
        body = client.get("/whoami", headers={"X-Request-ID": "trace-xyz"}).json()
        assert body["dep_rid"] == "trace-xyz" == body["ctx_rid"]

    def test_access_log_fields(self, caplog):
        client = TestClient(self._app())
        with caplog.at_level(logging.INFO, logger="cndb.access"):
            client.get("/ping")
        lines = [r.getMessage() for r in caplog.records if r.name == "cndb.access"]
        assert len(lines) == 1
        for fragment in ("method=GET", "path=/ping", "status=200", "duration_ms=", "request_id="):
            assert fragment in lines[0], lines[0]

    def test_slow_request_warns_even_without_access_log(self, caplog):
        client = TestClient(self._app(slow_ms=1, access_log=False))
        with caplog.at_level(logging.INFO, logger="cndb.access"):
            client.get("/slow")
        records = [r for r in caplog.records if r.name == "cndb.access"]
        assert [r.levelno for r in records] == [logging.WARNING]
        assert "slow=true" in records[0].getMessage()

    def test_user_id_included_when_state_set(self, caplog):
        client = TestClient(self._app())
        with caplog.at_level(logging.INFO, logger="cndb.access"):
            client.get("/whoami")
        line = next(r.getMessage() for r in caplog.records if r.name == "cndb.access")
        assert "user_id=7" in line


class TestSlowQueryCorrelation:
    """慢查询日志带上 request_id（复用 core/database.py 既有监听）."""

    def test_slow_query_log_includes_request_id(self, monkeypatch, caplog):
        monkeypatch.setattr(dbmod, "SLOW_QUERY_SECONDS", 0.0)
        with (
            caplog.at_level(logging.WARNING, logger="cndb.core.database"),
            bind_request_id("rid-42"),
            dbmod.engine.connect() as conn,
        ):
            conn.execute(text("SELECT 1"))
        line = next(rec.getMessage() for rec in caplog.records if "慢查询" in rec.getMessage())
        assert "request_id=rid-42" in line


class TestLoggingConfiguration:
    """cndb 命名空间日志配置（否则 INFO 级访问日志不会输出）."""

    def test_configure_logging_is_idempotent_and_sets_level(self):
        pkg = logging.getLogger("cndb")
        before = len(pkg.handlers)
        configure_logging(access_log=True)
        configure_logging(access_log=True)
        assert pkg.level == logging.INFO
        assert len(pkg.handlers) == max(before, 1)
        # 保持 propagate，测试的 caplog 才能捕获
        assert pkg.propagate is True

    def test_disabled_access_log_drops_level_to_warning(self):
        configure_logging(access_log=False)
        assert logging.getLogger("cndb").level == logging.WARNING
        # 复位，避免影响后续用例
        configure_logging(access_log=True)
        assert logging.getLogger("cndb").level == logging.INFO
