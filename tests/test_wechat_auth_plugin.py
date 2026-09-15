"""wechat_auth 插件单元 & 集成测试.

覆盖 client.py 的参数校验 / 请求成功 / 微信错误三条路径，
以及 routers/login.py 的未启用 / 自动注册 / 已有绑定 / 禁用自动注册四条主分支.

注意：路由集成测试依赖 client fixture，会通过 plugin_registry 自动发现 wechat_auth.
"""

from __future__ import annotations

import re
from unittest import mock

import pytest

from cndb.core.config import settings
from cndb.plugins.wechat_auth import client as wx_client
from cndb.plugins.wechat_auth import routers as wx_routers

# ── client.code2session ────────────────────────────────────────────────


def test_code2session_not_enabled() -> None:
    """WECHAT_AUTH_ENABLED=False 直接抛 ValueError."""
    settings.WECHAT_AUTH_ENABLED = False
    with pytest.raises(ValueError, match=r"未开启"):
        wx_client.code2session("wx_code_dummy")


def test_code2session_missing_appid() -> None:
    """AppID 或 Secret 未配置抛 ValueError."""
    settings.WECHAT_AUTH_ENABLED = True
    settings.WECHAT_APPID = ""
    settings.WECHAT_SECRET = "secret"
    with pytest.raises(ValueError, match=r"未配置"):
        wx_client.code2session("wx_code_dummy")


def test_code2session_missing_secret() -> None:
    settings.WECHAT_AUTH_ENABLED = True
    settings.WECHAT_APPID = "appid"
    settings.WECHAT_SECRET = ""
    with pytest.raises(ValueError, match=r"未配置"):
        wx_client.code2session("wx_code_dummy")


def test_code2session_success() -> None:
    """正常请求返回微信 session dict."""
    settings.WECHAT_AUTH_ENABLED = True
    settings.WECHAT_APPID = "appid"
    settings.WECHAT_SECRET = "secret"

    fake_resp = mock.Mock()
    fake_resp.json.return_value = {
        "openid": "o_TESTOPENID0000000000",
        "session_key": "sk_test_key",
        "unionid": "u_TESTUNIONID",
    }
    fake_resp.raise_for_status = mock.Mock()

    with mock.patch("cndb.plugins.wechat_auth.client.requests.get", return_value=fake_resp):
        data = wx_client.code2session("wx_code_dummy")

    assert data["openid"] == "o_TESTOPENID0000000000"
    assert data["session_key"] == "sk_test_key"


def test_code2session_wechat_errcode_nonzero() -> None:
    """微信返回 errcode != 0 抛 RuntimeError."""
    settings.WECHAT_AUTH_ENABLED = True
    settings.WECHAT_APPID = "appid"
    settings.WECHAT_SECRET = "secret"

    fake_resp = mock.Mock()
    fake_resp.json.return_value = {"errcode": 40029, "errmsg": "invalid code"}
    fake_resp.raise_for_status = mock.Mock()

    with (
        mock.patch("cndb.plugins.wechat_auth.client.requests.get", return_value=fake_resp),
        pytest.raises(RuntimeError, match=r"errcode=40029"),
    ):
        wx_client.code2session("wx_code_dummy")


# ── routers.login._serialize_user ──────────────────────────────────────


def test_serialize_user_basic() -> None:
    from cndb.plugins.accounts.models import User

    u = User(username="alice", nickname=None, role="user")
    u.id = 42
    u.is_superuser = False
    data = wx_routers.login._serialize_user(u)
    assert data["id"] == 42
    assert data["username"] == "alice"
    assert data["nickname"] == "alice"  # fallback username
    assert data["role"] == "user"
    assert data["is_superuser"] is False


def test_serialize_user_with_nickname() -> None:
    from cndb.plugins.accounts.models import User

    u = User(username="alice", nickname="艾莉丝", role="user")
    u.id = 42
    u.is_superuser = False
    data = wx_routers.login._serialize_user(u)
    assert data["nickname"] == "艾莉丝"


# ── routers.wechat_login（需要完整 app + DB）────────────────────────────


@pytest.fixture(autouse=True)
def _enable_wechat_auth():
    """每个路由测试自动开启微信登录 + 允许自动注册."""
    old_enabled = settings.WECHAT_AUTH_ENABLED
    old_auto = settings.WECHAT_LOGIN_AUTO_REGISTER
    settings.WECHAT_AUTH_ENABLED = True
    settings.WECHAT_LOGIN_AUTO_REGISTER = True
    settings.WECHAT_APPID = "appid"
    settings.WECHAT_SECRET = "secret"
    yield
    settings.WECHAT_AUTH_ENABLED = old_enabled
    settings.WECHAT_LOGIN_AUTO_REGISTER = old_auto


@pytest.fixture
def _fake_wechat_session():
    """patch code2session 返回固定 openid."""
    with mock.patch(
        "cndb.plugins.wechat_auth.routers.login.code2session",
        return_value={
            "openid": "o_AUTOTEST_OPENID_12345678",
            "session_key": "sk_autotest",
            "unionid": "u_AUTOTEST_UNIONID",
        },
    ):
        yield


@pytest.fixture
def _fake_wechat_session_collision():
    """patch code2session 返回一个 openid，其前 8 位碰撞已有 username."""
    with mock.patch(
        "cndb.plugins.wechat_auth.routers.login.code2session",
        return_value={
            "openid": "o_AUTOTEST_COLLISION_ABCDEF",
            "session_key": "sk_collision",
        },
    ):
        yield


LOGIN_URL = "/api/v1/wechat-auth/login"


def test_wechat_login_not_enabled(client) -> None:
    """WECHAT_AUTH_ENABLED=False → 403."""
    settings.WECHAT_AUTH_ENABLED = False
    r = client.post(LOGIN_URL, json={"code": "wx_any_code"})
    assert r.status_code == 403
    assert "未启用" in r.json()["detail"]


def test_wechat_login_errcode_from_wechat(client) -> None:
    """微信 jscode2session 返回 RuntimeError → 400."""
    with mock.patch(
        "cndb.plugins.wechat_auth.routers.login.code2session",
        side_effect=RuntimeError("微信返回错误: errcode=40029"),
    ):
        r = client.post(LOGIN_URL, json={"code": "wx_any_code"})
    assert r.status_code == 400


def test_wechat_login_valueerror(client) -> None:
    """code2session 抛 ValueError（未配置）→ 500."""
    with mock.patch(
        "cndb.plugins.wechat_auth.routers.login.code2session",
        side_effect=ValueError("WECHAT_APPID 未配置"),
    ):
        r = client.post(LOGIN_URL, json={"code": "wx_any_code"})
    assert r.status_code == 500


def test_wechat_login_auto_register(client, _fake_wechat_session, db) -> None:
    """首次出现 openid → 自动创建 User + WechatAccount."""
    r = client.post(
        LOGIN_URL,
        json={
            "code": "wx_auto_register",
            "nickname": "自动化测试用户",
            "avatar_url": "https://example.com/a.png",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["username"].startswith("wx_o_AUTO")
    assert body["user"]["nickname"] == "自动化测试用户"
    assert body["user"]["role"] == "user"

    # 数据库验证
    from cndb.plugins.wechat_auth.models import WechatAccount

    ws = (
        db.query(WechatAccount)
        .filter(
            WechatAccount.openid == "o_AUTOTEST_OPENID_12345678",
        )
        .first()
    )
    assert ws is not None
    assert ws.nickname == "自动化测试用户"
    assert ws.avatar_url == "https://example.com/a.png"
    assert ws.last_login_at is not None


def test_wechat_login_existing_binding(client, _fake_wechat_session, db) -> None:
    """已有绑定 → 更新 session_key / last_login_at，首次填充 nickname."""
    # 先手动造一条绑定
    from cndb.plugins.accounts.models import User, UserRole
    from cndb.plugins.wechat_auth.models import WechatAccount

    u = User(username="prebind_user", role=UserRole.USER.value, nickname="老昵称")
    u.set_password("xxx")
    db.add(u)
    db.flush()
    wa = WechatAccount(
        openid="o_AUTOTEST_OPENID_12345678",
        session_key="old_sk",
        user_id=u.id,
        nickname=None,
    )
    db.add(wa)
    db.commit()

    # 本次登录带了新昵称，wa.nickname 原本为空 → 首次填
    r = client.post(
        LOGIN_URL,
        json={
            "code": "wx_existing",
            "nickname": "新昵称首次填入",
            "avatar_url": "https://example.com/b.png",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["username"] == "prebind_user"

    db.refresh(wa)
    assert wa.session_key == "sk_autotest"  # 更新了
    assert wa.nickname == "新昵称首次填入"  # 原来 None，首次填
    assert wa.avatar_url == "https://example.com/b.png"
    assert wa.last_login_at is not None


def test_wechat_login_disabled_auto_register(client, _fake_wechat_session, db) -> None:
    """未绑定 + 不允许自动注册 → 403."""
    settings.WECHAT_LOGIN_AUTO_REGISTER = False
    r = client.post(LOGIN_URL, json={"code": "wx_disabled"})
    assert r.status_code == 403
    assert "自动注册" in r.json()["detail"] or "绑定" in r.json()["detail"]


def test_wechat_login_disabled_user(client, db) -> None:
    """已有绑定但 User 被禁用 → 400."""
    from cndb.plugins.accounts.models import User, UserRole
    from cndb.plugins.wechat_auth.models import WechatAccount

    u = User(username="disabled_user", role=UserRole.USER.value, nickname="禁用用户", is_active=False)
    u.set_password("xxx")
    db.add(u)
    db.flush()
    db.add(
        WechatAccount(
            openid="o_AUTOTEST_OPENID_12345678",
            session_key="sk",
            user_id=u.id,
        )
    )
    db.commit()

    with mock.patch(
        "cndb.plugins.wechat_auth.routers.login.code2session",
        return_value={"openid": "o_AUTOTEST_OPENID_12345678", "session_key": "sk"},
    ):
        r = client.post(LOGIN_URL, json={"code": "wx_disabled_user"})
    assert r.status_code == 400
    assert "禁用" in r.json()["detail"]


def test_wechat_login_username_collision(client, _fake_wechat_session_collision, db) -> None:
    """openid 前 8 位 → wx_o_AUTOTE 已存在 → 自动加后缀."""
    from cndb.plugins.accounts.models import User, UserRole

    # openid 前 8 位是 o_AUTOTE，拼接 wx_ → wx_o_AUTOTE
    existing = User(
        username="wx_o_AUTOTE",
        role=UserRole.USER.value,
        nickname="先占坑",
    )
    existing.set_password("xxx")
    db.add(existing)
    db.commit()

    r = client.post(LOGIN_URL, json={"code": "wx_collision"})
    assert r.status_code == 200, r.text
    body = r.json()
    # 最终 username 应该是 wx_o_AUTOTE_1（加后缀）
    assert body["user"]["username"] != "wx_o_AUTOTE"
    assert re.match(r"^wx_o_AUTOTE(_\d+)?$", body["user"]["username"]), body["user"]["username"]


def test_wechat_login_invalid_payload(client) -> None:
    """缺少 code → 422."""
    r = client.post(LOGIN_URL, json={})
    assert r.status_code == 422
