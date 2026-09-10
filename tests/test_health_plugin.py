"""health 插件集成测试."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pyweb_template.app import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_health_ping(client: TestClient) -> None:
    r = client.get("/api/v1/health/ping")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "pong"
    assert "timestamp" in d
    assert "python" in d


def test_health_ready(client: TestClient) -> None:
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"
