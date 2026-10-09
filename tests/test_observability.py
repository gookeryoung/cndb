"""可观测性测试：health liveness/readiness 拆分 + 慢查询日志."""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import text

from cndb.core import database as dbmod

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
