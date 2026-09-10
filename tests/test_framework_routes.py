"""框架级 HTTP 路由测试."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from pyweb_template.app import app


@pytest.fixture()
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_health_endpoint(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["app"] == "pyweb_template"


def test_plugins_endpoint(client: TestClient) -> None:
    r = client.get("/api/plugins")
    assert r.status_code == 200
    names = {p["name"] for p in r.json()["plugins"]}
    assert "health" in names


def test_navigation_endpoint(client: TestClient) -> None:
    r = client.get("/api/navigation")
    assert r.status_code == 200
    nav = r.json()["navigation"]
    # 当前只有 health 插件（无 navigation 注册），返回空列表是合法的
    assert isinstance(nav, list)
