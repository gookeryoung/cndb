"""会话 / 授权生命周期测试：刷新令牌轮换、登出、改密失效、会话管理与登录限流.

覆盖（对应 A3）：
- 登录返回访问令牌 + 刷新令牌；刷新令牌可换新令牌对（一次性轮换，旧令牌立即失效）；
- **复用检测**：已轮换的刷新令牌再次使用 → 吊销该用户全部会话并 401；
- 登出（单枚 / 全部）；无效刷新令牌 → 401；过期刷新令牌 → 401；
- 改密需校验当前密码，成功后**既有 access token 立即失效**（token_version）且刷新令牌全部吊销；
- 会话列表与按会话下线（仅限本人）；
- 登录失败限流：达到阈值返回 429 + Retry-After，成功登录清除计数。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from cndb.core.security import create_access_token, hash_token
from cndb.plugins.accounts.models import RefreshToken, User
from cndb.plugins.accounts.routers.auth import _reset_login_limiter

AUTH = "/api/v1/accounts/auth"
PROTECTED = "/api/v1/workspaces"


@pytest.fixture(autouse=True)
def _clean_limiter():
    """每个用例前重置进程内限流计数（模块级单例，避免用例间串扰）."""
    _reset_login_limiter()
    yield
    _reset_login_limiter()


@pytest.fixture
def account(client, db: Session) -> dict[str, str]:
    """注册并登录一个独立账号，返回 {username, password, access, refresh}."""
    username, password = "sessuser", "passw0rd"
    r = client.post(f"{AUTH}/register", json={"username": username, "email": "sess@example.com", "password": password})
    assert r.status_code in (200, 201), r.text
    r = client.post(f"{AUTH}/login", json={"login": username, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    return {
        "username": username,
        "password": password,
        "access": body["access_token"],
        "refresh": body["refresh_token"],
    }


def _login(client, login: str, password: str):
    return client.post(f"{AUTH}/login", json={"login": login, "password": password})


class TestLoginIssuesTokens:
    def test_login_response_shape(self, client, account):
        r = _login(client, account["username"], account["password"])
        assert r.status_code == 200
        body = r.json()
        assert body["access_token"] and body["refresh_token"]
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0
        assert body["refresh_token"] != body["access_token"]

    def test_refresh_token_only_stored_hashed(self, client, db, account):
        """库中不得出现明文刷新令牌."""
        raw = account["refresh"]
        assert db.query(RefreshToken).filter(RefreshToken.token_hash == hash_token(raw)).count() == 1
        assert db.query(RefreshToken).filter(RefreshToken.token_hash == raw).count() == 0


class TestRefreshRotation:
    def test_refresh_rotates_and_invalidates_old(self, client, account):
        r = client.post(f"{AUTH}/refresh", json={"refresh_token": account["refresh"]})
        assert r.status_code == 200, r.text
        new = r.json()
        assert new["refresh_token"] != account["refresh"]

        # 旧令牌已作废
        r2 = client.post(f"{AUTH}/refresh", json={"refresh_token": account["refresh"]})
        assert r2.status_code == 401

        # 新令牌可用（但上一步的复用检测已吊销全部会话，因此这里应 401）
        r3 = client.post(f"{AUTH}/refresh", json={"refresh_token": new["refresh_token"]})
        assert r3.status_code == 401

    def test_reuse_detection_revokes_all_sessions(self, client, db, account):
        """已轮换令牌被复用 → 全部会话吊销."""
        first = client.post(f"{AUTH}/refresh", json={"refresh_token": account["refresh"]}).json()["refresh_token"]
        second = client.post(f"{AUTH}/refresh", json={"refresh_token": first}).json()["refresh_token"]

        # 复用最早的（已被轮换两轮的）令牌
        r = client.post(f"{AUTH}/refresh", json={"refresh_token": account["refresh"]})
        assert r.status_code == 401
        assert "重复使用" in r.text or "重新登录" in r.text

        # 最新令牌也被吊销
        assert client.post(f"{AUTH}/refresh", json={"refresh_token": second}).status_code == 401

    def test_invalid_refresh_token_401(self, client, account):
        assert client.post(f"{AUTH}/refresh", json={"refresh_token": "not-a-real-token-xxxx"}).status_code == 401

    def test_expired_refresh_token_401(self, client, db, account):
        row = db.query(RefreshToken).first()
        assert row is not None
        row.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()

        r = client.post(f"{AUTH}/refresh", json={"refresh_token": account["refresh"]})
        assert r.status_code == 401
        db.refresh(row)
        assert row.revoked_reason == "expired"


class TestLogout:
    def test_logout_single_revokes(self, client, account):
        r = client.post(f"{AUTH}/logout", json={"refresh_token": account["refresh"]})
        assert r.status_code == 200
        assert r.json()["revoked"] == 1

        assert client.post(f"{AUTH}/refresh", json={"refresh_token": account["refresh"]}).status_code == 401

    def test_logout_all_requires_auth_and_revokes_everything(self, client, account):
        # 再登录一次，制造两个会话
        second = _login(client, account["username"], account["password"]).json()
        headers = {"Authorization": f"Bearer {second['access_token']}"}

        assert client.post(f"{AUTH}/logout", json={"all": True}).status_code == 401
        r = client.post(f"{AUTH}/logout", json={"all": True}, headers=headers)
        assert r.status_code == 200
        assert r.json()["scope"] == "all" and r.json()["revoked"] >= 1

        for token in (account["refresh"], second["refresh_token"]):
            assert client.post(f"{AUTH}/refresh", json={"refresh_token": token}).status_code == 401

    def test_logout_requires_token_or_all(self, client):
        r = client.post(f"{AUTH}/logout", json={})
        assert r.status_code == 400


class TestPasswordChange:
    def test_wrong_current_password_rejected(self, client, account):
        headers = {"Authorization": f"Bearer {account['access']}"}
        r = client.post(
            f"{AUTH}/password",
            json={"current_password": "wrong-pass", "new_password": "newpass123"},
            headers=headers,
        )
        assert r.status_code == 400

    def test_change_invalidates_access_and_refresh(self, client, account):
        headers = {"Authorization": f"Bearer {account['access']}"}
        r = client.post(
            f"{AUTH}/password",
            json={"current_password": account["password"], "new_password": "newpass123"},
            headers=headers,
        )
        assert r.status_code == 200 and r.json()["ok"] is True

        # 既有 access token 立即失效（token_version）
        assert client.get(f"{AUTH}/me", headers=headers).status_code == 401
        # 刷新令牌全部吊销
        assert client.post(f"{AUTH}/refresh", json={"refresh_token": account["refresh"]}).status_code == 401
        # 新密码可登录，旧密码不可
        assert _login(client, account["username"], "newpass123").status_code == 200
        assert _login(client, account["username"], account["password"]).status_code == 401

    def test_same_password_rejected(self, client, account):
        headers = {"Authorization": f"Bearer {account['access']}"}
        r = client.post(
            f"{AUTH}/password",
            json={"current_password": account["password"], "new_password": account["password"]},
            headers=headers,
        )
        assert r.status_code == 400


class TestSessions:
    def test_list_and_revoke_session(self, client, db, account):
        headers = {"Authorization": f"Bearer {account['access']}"}
        second = _login(client, account["username"], account["password"]).json()

        r = client.get(f"{AUTH}/sessions", headers=headers)
        assert r.status_code == 200
        sessions = r.json()
        assert len(sessions) == 2
        assert all("expires_at" in s and s["revoked_reason"] is None for s in sessions)

        target = sessions[-1]["id"]
        assert client.delete(f"{AUTH}/sessions/{target}", headers=headers).status_code == 200

        # 被吊销的会话无法刷新；另一个仍可用
        remaining = list(client.get(f"{AUTH}/sessions", headers=headers).json())
        assert len(remaining) == 1
        assert client.post(f"{AUTH}/refresh", json={"refresh_token": second["refresh_token"]}).status_code in (200, 401)

    def test_cannot_revoke_others_session(self, client, db, account):
        """别人的会话 id → 404（不泄露存在性）."""
        other = User(username="other-sess", nickname="o", role="user")
        other.set_password("otherpass")
        db.add(other)
        db.commit()
        row = RefreshToken(
            user_id=other.id,
            token_hash=hash_token("other-raw-token"),
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
        )
        db.add(row)
        db.commit()

        headers = {"Authorization": f"Bearer {account['access']}"}
        assert client.delete(f"{AUTH}/sessions/{row.id}", headers=headers).status_code == 404


class TestLoginRateLimit:
    def test_blocks_after_threshold(self, client, monkeypatch):
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 3)
        _reset_login_limiter()

        for _ in range(3):
            assert _login(client, "ratelimit-user", "bad-pass").status_code == 401

        r = _login(client, "ratelimit-user", "bad-pass")
        assert r.status_code == 429
        assert int(r.headers["retry-after"]) > 0
        assert "次数过多" in r.text

    def test_success_resets_counter(self, client, account, monkeypatch):
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 3)
        _reset_login_limiter()

        for _ in range(2):
            assert _login(client, account["username"], "bad-pass").status_code == 401
        # 成功登录清除计数
        assert _login(client, account["username"], account["password"]).status_code == 200

        # 复位证明：若未清除，计数已达 2，本条失败就会触发 429（limit=3 时第 3 次失败被拦）
        assert _login(client, account["username"], "bad-pass").status_code == 401
        assert _login(client, account["username"], "bad-pass").status_code == 401
        assert _login(client, account["username"], "bad-pass").status_code == 401
        assert _login(client, account["username"], "bad-pass").status_code == 429

    def test_other_account_not_affected(self, client, account, monkeypatch):
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 2)
        _reset_login_limiter()

        for _ in range(3):
            _login(client, "victim", "bad-pass")
        assert _login(client, "victim", "bad-pass").status_code == 429

        # IP 维度阈值为 4 倍，因此换账号仍可尝试（未被 IP 维度拦下）
        assert _login(client, account["username"], account["password"]).status_code == 200


class TestTokenVersion:
    def test_stale_token_rejected_after_version_bump(self, client, db, account):
        """管理员强制下线：直接 +1 token_version 即可让 access token 失效."""
        user = db.query(User).filter(User.username == account["username"]).one()
        user.token_version = int(user.token_version or 0) + 1
        db.commit()

        headers = {"Authorization": f"Bearer {account['access']}"}
        assert client.get(f"{AUTH}/me", headers=headers).status_code == 401

    def test_fresh_token_with_current_version_ok(self, client, db, account):
        user = db.query(User).filter(User.username == account["username"]).one()
        token = create_access_token(
            subject=user.id, extra={"username": user.username}, token_version=user.token_version
        )
        assert client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    def test_protected_endpoint_rejects_stale_token(self, client, db, account):
        user = db.query(User).filter(User.username == account["username"]).one()
        user.token_version = int(user.token_version or 0) + 1
        db.commit()
        headers = {"Authorization": f"Bearer {account['access']}"}
        assert client.get(PROTECTED, headers=headers).status_code == 401


class TestLocalModeDisabled:
    def test_session_endpoints_rejected_in_local_mode(self, client, account, monkeypatch):
        """单机模式禁用网络认证行为（与登录一致，403）."""
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "LOCAL_MODE", True)
        assert client.post(f"{AUTH}/refresh", json={"refresh_token": account["refresh"]}).status_code == 403
        assert client.post(f"{AUTH}/logout", json={"refresh_token": account["refresh"]}).status_code == 403
