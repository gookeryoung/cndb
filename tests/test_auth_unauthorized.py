"""未认证统一 401 的回归测试（此前无认证头会 500）.

背景：`get_current_user` 在 AUTH_ENABLED=True 时，「无认证头 / 头格式非法 / 令牌为空」三条路径
原先返回 None，端点再解引用 `current_user.id` 就变成 500（实测 `/api/v1/workspaces`）。
现在统一抛 401；`get_optional_user` 会吞掉 401，匿名可用路由不受影响；AUTH_ENABLED=False 仍返回 None。
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from cndb.api.deps import get_current_user, get_optional_user
from cndb.core.config import settings

PROTECTED = "/api/v1/workspaces"


class TestUnauthenticatedReturns401:
    """未带/损坏认证信息 → 401（而不是 500）."""

    def test_missing_header_401(self, client):
        r = client.get(PROTECTED)
        assert r.status_code == 401, r.text
        assert r.headers.get("www-authenticate") == "Bearer"
        assert "detail" in r.json()

    def test_malformed_header_401(self, client):
        r = client.get(PROTECTED, headers={"Authorization": "Token abc"})
        assert r.status_code == 401, r.text

    def test_empty_bearer_401(self, client):
        r = client.get(PROTECTED, headers={"Authorization": "Bearer   "})
        assert r.status_code == 401, r.text

    def test_invalid_token_401(self, client):
        r = client.get(PROTECTED, headers={"Authorization": "Bearer not-a-real-token"})
        assert r.status_code == 401, r.text

    def test_valid_token_still_ok(self, client, auth_headers):
        assert client.get(PROTECTED, headers=auth_headers).status_code == 200


class TestAuthModeContracts:
    """AUTH_ENABLED=False / LOCAL_MODE 的既有语义不被破坏."""

    @staticmethod
    def _probe_app() -> FastAPI:
        app = FastAPI()

        @app.get("/required")
        def required(user: object = Depends(get_current_user)) -> dict[str, bool]:
            return {"authenticated": user is not None}

        @app.get("/optional")
        def optional(user: object = Depends(get_optional_user)) -> dict[str, bool]:
            return {"authenticated": user is not None}

        return app

    def test_auth_disabled_returns_none(self, db, monkeypatch):
        monkeypatch.setattr(settings, "AUTH_ENABLED", False)
        client = TestClient(self._probe_app())
        r = client.get("/required")
        assert r.status_code == 200
        assert r.json() == {"authenticated": False}

    def test_optional_user_tolerates_missing_token(self, db):
        """AUTH_ENABLED=True 下仍可匿名访问 optional 依赖（401 被吞掉）."""
        client = TestClient(self._probe_app())
        r = client.get("/optional")
        assert r.status_code == 200
        assert r.json() == {"authenticated": False}

    def test_local_mode_maps_to_builtin_user(self, client, monkeypatch):
        """单机模式无认证头也应正常工作（映射内置本地用户）."""
        monkeypatch.setattr(settings, "LOCAL_MODE", True)
        r = client.get(PROTECTED)
        assert r.status_code == 200, r.text
