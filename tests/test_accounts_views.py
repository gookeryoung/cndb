"""accounts 视图测试：注册、登录、登出与个人信息."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from cndb.accounts.models import User

pytestmark = pytest.mark.django_db

REGISTER_URL = "/api/auth/register/"
LOGIN_URL = "/api/auth/login/"
LOGOUT_URL = "/api/auth/logout/"
ME_URL = "/api/auth/me/"


def _register_payload() -> dict[str, str]:
    """构造合法注册请求体."""
    return {
        "username": "bob",
        "email": "bob@example.com",
        "password": "Str0ng-Pass-43",
        "nickname": "鲍勃",
    }


def test_register_creates_user_and_session(api: APIClient) -> None:
    """注册成功：落库、返回用户信息并直接建立会话."""
    resp = api.post(REGISTER_URL, _register_payload(), format="json")
    assert resp.status_code == 201
    assert resp.data["username"] == "bob"
    assert "password" not in resp.data
    assert User.objects.filter(username="bob").exists()
    me = api.get(ME_URL)
    assert me.status_code == 200
    assert me.data["username"] == "bob"


def test_register_duplicate_username_rejected(api: APIClient, user: User) -> None:
    """用户名重复：返回 400."""
    payload = _register_payload() | {"username": "alice"}
    resp = api.post(REGISTER_URL, payload, format="json")
    assert resp.status_code == 400


def test_register_weak_password_rejected(api: APIClient) -> None:
    """弱密码：返回 400 且不落库."""
    payload = _register_payload() | {"password": "123"}
    resp = api.post(REGISTER_URL, payload, format="json")
    assert resp.status_code == 400
    assert not User.objects.filter(username="bob").exists()


def test_register_missing_email_rejected(api: APIClient) -> None:
    """缺少邮箱：返回 400."""
    payload = _register_payload()
    del payload["email"]
    resp = api.post(REGISTER_URL, payload, format="json")
    assert resp.status_code == 400


def test_login_success(api: APIClient, user: User) -> None:
    """登录成功：返回用户信息并建立会话."""
    resp = api.post(LOGIN_URL, {"username": "alice", "password": "Str0ng-Pass-42"}, format="json")
    assert resp.status_code == 200
    assert resp.data["username"] == "alice"
    me = api.get(ME_URL)
    assert me.status_code == 200


def test_login_wrong_password(api: APIClient, user: User) -> None:
    """密码错误：返回 401（Token 认证器提供 WWW-Authenticate 头）."""
    resp = api.post(LOGIN_URL, {"username": "alice", "password": "wrong-pass"}, format="json")
    assert resp.status_code == 401


def test_me_requires_authentication(api: APIClient) -> None:
    """未登录访问个人信息：返回 401."""
    resp = api.get(ME_URL)
    assert resp.status_code == 401


def test_me_update_nickname(auth_client: APIClient, user: User) -> None:
    """更新昵称：返回 200 且落库."""
    resp = auth_client.patch(ME_URL, {"nickname": "新昵称"}, format="json")
    assert resp.status_code == 200
    user.refresh_from_db()
    assert user.nickname == "新昵称"


def test_logout_destroys_session(api: APIClient, user: User) -> None:
    """登出后个人信息不可访问."""
    api.post(LOGIN_URL, {"username": "alice", "password": "Str0ng-Pass-42"}, format="json")
    resp = api.post(LOGOUT_URL)
    assert resp.status_code == 204
    assert api.get(ME_URL).status_code == 401


def test_user_str(user: User) -> None:
    """用户 __str__ 返回用户名."""
    assert str(user) == "alice"
