"""公开注册入口已收窄：RegisterRequest 不再含 role 字段.

Wave 1 测试文件。覆盖：
- RegisterRequest 拒绝 role 字段 (extra=forbid → 422)
- 公开注册默认为 user 角色
- PUBLIC_REGISTERABLE_ROLES 常量已移除
- admin-register 端点不受影响
"""

from __future__ import annotations

import pytest

from cndb.plugins.accounts.models import User


@pytest.fixture
def su(db, client):
    """注入一个超级管理员并返回 JWT."""
    u = User(username="su_seed_rc", email="su_rc@x.com")
    u.set_password("pw1234")
    u.is_superuser = True
    db.add(u)
    db.commit()
    db.refresh(u)
    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": "su_seed_rc", "password": "pw1234"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


class TestRegisterConstraint:
    def test_register_rejects_role_field(self, client):
        """公开注册携带 role 字段应触发 422（pydantic extra=forbid）."""
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "no_role", "password": "pw1234", "role": "system_admin"},
        )
        assert r.status_code == 422, r.text

    def test_register_success_no_role(self, client):
        """不带 role 的正常注册应 201，且角色强制为 user."""
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "plain_x", "password": "pw1234"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["role"] == "user"

    def test_public_registerable_roles_constant_removed(self):
        """PUBLIC_REGISTERABLE_ROLES 常量已移除（不再需要降级逻辑）."""
        import cndb.plugins.accounts.schemas.auth as auth_schema

        assert not hasattr(auth_schema, "PUBLIC_REGISTERABLE_ROLES")


class TestAdminRegisterStillWorks:
    def test_admin_register_accepts_role(self, client, su):
        """admin-register 端点不受影响，仍可指定任意角色."""
        r = client.post(
            "/api/v1/accounts/auth/admin-register",
            json={"username": "still_admin_x", "password": "pw1234", "role": "system_admin"},
            headers={"Authorization": f"Bearer {su}"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["role"] == "system_admin"
