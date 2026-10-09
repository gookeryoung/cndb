"""单机模式（LOCAL_MODE）行为测试 —— 差异面收敛.

覆盖计划验收标准：
- AC-1 无认证 me 返回内置本地用户（幂等、字段正确、旧 token 被忽略）
- AC-2 auth-mode 端点双模式返回
- AC-3 模式内 403 矩阵（register/login/share/forms/wechat）
- AC-6 LOCAL_MODE=False 回归（jwt 模式、无头 me 401）
- _get_local_user 幂等/字段/IntegrityError 回退
- CLI serve host 推导与回环拒绝、service enable 回环校验
"""

from __future__ import annotations

import argparse
import sys
import types

import pytest
from sqlalchemy.exc import IntegrityError

from cndb.api.deps import _get_local_user
from cndb.core.config import settings
from cndb.plugins.accounts.models import User

AUTH = "/api/v1/accounts/auth"


@pytest.fixture
def local_mode(monkeypatch):
    """开启单机模式，测试结束自动恢复 False."""
    monkeypatch.setattr(settings, "LOCAL_MODE", True)
    return settings


class TestLocalModeAPI:
    """AC-1/2/3：单机模式 HTTP 行为矩阵."""

    def test_me_without_token_returns_local_user(self, local_mode, client):
        r = client.get(f"{AUTH}/me")
        assert r.status_code == 200
        body = r.json()
        assert body["username"] == "local"
        assert body["is_superuser"] is True

    def test_me_idempotent_same_id(self, local_mode, client):
        first = client.get(f"{AUTH}/me").json()["id"]
        second = client.get(f"{AUTH}/me").json()["id"]
        assert first == second

    def test_stale_token_ignored(self, local_mode, client):
        """单机模式语义：Authorization 头完全忽略（含无效旧 token）."""
        r = client.get(f"{AUTH}/me", headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 200
        assert r.json()["username"] == "local"

    def test_auth_mode_local(self, local_mode, client):
        assert client.get(f"{AUTH}/auth-mode").json() == {"mode": "local"}

    def test_register_forbidden(self, local_mode, client):
        r = client.post(f"{AUTH}/register", json={"username": "alice", "password": "passw0rd"})
        assert r.status_code == 403
        assert "单机模式已禁用注册" in r.json()["detail"]

    def test_login_forbidden(self, local_mode, client):
        r = client.post(f"{AUTH}/login", json={"login": "local", "password": "whatever"})
        assert r.status_code == 403
        assert "单机模式已禁用登录" in r.json()["detail"]

    def test_public_share_forbidden(self, local_mode, client):
        r = client.get("/api/v1/public/share/any-slug")
        assert r.status_code == 403
        assert "单机模式" in r.json()["detail"]

    def test_public_form_submit_forbidden(self, local_mode, client):
        r = client.post("/api/v1/public/forms/any-slug", json={})
        assert r.status_code == 403

    def test_wechat_login_forbidden(self, local_mode, client):
        r = client.post("/api/v1/wechat-auth/login", json={"code": "any"})
        assert r.status_code == 403
        assert "单机模式已禁用微信登录" in r.json()["detail"]

    def test_business_smoke_create_workspace(self, local_mode, client):
        """业务链冒烟：无认证创建工作区归属本地用户."""
        r = client.post("/api/v1/workspaces", json={"name": "local-smoke"})
        assert r.status_code == 201
        assert r.json()["name"] == "local-smoke"


class TestJwtModeRegression:
    """AC-6：LOCAL_MODE=False（默认）现网行为不变."""

    def test_auth_mode_jwt(self, client):
        assert client.get(f"{AUTH}/auth-mode").json() == {"mode": "jwt"}

    def test_me_without_token_401(self, client):
        assert client.get(f"{AUTH}/me").status_code == 401


class TestGetLocalUser:
    """_get_local_user 单元行为."""

    def test_creates_with_expected_fields(self, local_mode, db):
        user = _get_local_user(db)
        assert user.username == "local"
        assert user.nickname == "本地用户"
        assert user.is_superuser is True
        # hashed_password 随机不可知，密码校验永不通过
        assert user.check_password("local") is False

    def test_idempotent(self, local_mode, db):
        assert _get_local_user(db).id == _get_local_user(db).id

    def test_integrity_error_fallback(self, local_mode, db, monkeypatch):
        """并发首建竞态：commit 撞 unique 约束后回退重查命中先建方."""
        existing = User(username="local", nickname="本地用户", is_superuser=True)
        existing.hashed_password = "x"
        db.add(existing)
        db.commit()

        class _Query:
            def __init__(self, result):
                self._result = result

            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return self._result

        # 首查返回 None（模拟竞态窗口），回退重查返回先建方
        results = iter([None, existing])
        monkeypatch.setattr(db, "query", lambda *a, **kw: _Query(next(results)))

        user = _get_local_user(db)
        assert user is existing

    def test_integrity_error_reraise_when_refetch_empty(self, local_mode, db, monkeypatch):
        """理论边界：回退重查仍为 None 时直接上抛，不吞异常."""

        class _Query:
            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return None

        monkeypatch.setattr(db, "query", lambda *a, **kw: _Query())

        def _raise_commit():
            raise IntegrityError("stmt", {}, Exception("UNIQUE constraint failed"))

        monkeypatch.setattr(db, "commit", _raise_commit)
        with pytest.raises(IntegrityError, match="UNIQUE"):
            _get_local_user(db)


def _serve_args(**kw) -> argparse.Namespace:
    """构造 serve 子命令 args（对齐 main() 的字段集合）."""
    return argparse.Namespace(
        host=kw.get("host"),
        port=8000,
        reload=False,
        workers=1,
        local=kw.get("local", False),
    )


@pytest.fixture
def patched_uvicorn(monkeypatch):
    """替换 uvicorn.run 捕获启动参数，并屏蔽 Proactor 噪音处理."""
    import cndb.cli.main as cli_main

    captured: dict = {}
    monkeypatch.setattr(cli_main, "_silence_proactor_reset_noise", lambda: None)
    # uvicorn.run(app_str, **kwargs) —— app 为位置参数
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        types.SimpleNamespace(run=lambda *a, **kw: captured.update({"app": a[0] if a else None}, **kw)),
    )
    return captured


class TestCliServeLocal:
    """AC-4：serve host 推导与回环硬校验."""

    def test_local_default_host_loopback(self, local_mode, patched_uvicorn):
        from cndb.cli import main as cli_main

        cli_main.serve(_serve_args(local=True))
        assert patched_uvicorn["host"] == "127.0.0.1"
        assert settings.LOCAL_MODE is True

    def test_env_source_default_host_loopback(self, local_mode, patched_uvicorn):
        """env 开启（--local 未传）同样推导 127.0.0.1."""
        from cndb.cli import main as cli_main

        cli_main.serve(_serve_args(local=False))
        assert patched_uvicorn["host"] == "127.0.0.1"

    def test_default_host_wildcard_when_disabled(self, monkeypatch, patched_uvicorn):
        """LOCAL_MODE=False 且未传 --host：保持 0.0.0.0 现网默认."""
        monkeypatch.setattr(settings, "LOCAL_MODE", False)
        from cndb.cli import main as cli_main

        cli_main.serve(_serve_args(local=False))
        assert patched_uvicorn["host"] == "0.0.0.0"

    def test_local_rejects_non_loopback(self, local_mode, patched_uvicorn, capsys):
        from cndb.cli import main as cli_main

        with pytest.raises(SystemExit) as ei:
            cli_main.serve(_serve_args(host="0.0.0.0", local=True))
        assert ei.value.code == 1
        assert "单机模式" in capsys.readouterr().err

    def test_loopback_alias_accepted(self, local_mode, patched_uvicorn):
        from cndb.cli import main as cli_main

        cli_main.serve(_serve_args(host="localhost", local=True))
        assert patched_uvicorn["host"] == "localhost"


class TestCliServiceLocal:
    """service enable/run 的单机模式透传与回环校验."""

    def test_build_run_command_appends_local(self, monkeypatch):
        from cndb.cli import service as svc

        monkeypatch.setattr(svc, "_exe_command", lambda: ["cndbw"])
        assert svc.build_run_command("127.0.0.1", 8000, local=True).endswith("--local")
        assert not svc.build_run_command("0.0.0.0", 8000, local=False).endswith("--local")

    def test_enable_rejects_non_loopback_local(self):
        from cndb.cli import service as svc

        with pytest.raises(ValueError, match="单机模式"):
            svc.enable("0.0.0.0", 8000, local=True)

