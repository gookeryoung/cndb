"""accounts 插件集成测试."""

import pytest

from cndb.plugins.accounts.models import User


@pytest.fixture
def superuser_token(db, client):
    """创建一个超级管理员并返回 JWT，同时 db session 已同步."""
    u = User(username="su_seed", email="su@example.com")
    u.set_password("pw1234")
    u.is_superuser = True
    db.add(u)
    db.commit()
    db.refresh(u)

    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": "su_seed", "password": "pw1234"},
    )
    assert r.status_code == 200
    return r.json()["access_token"]


class TestUserModel:
    def test_set_and_check_password(self, db):
        user = User(username="alice", email="a@b.c", nickname="A")
        user.set_password("hunter2")
        assert user.hashed_password != "hunter2"
        assert user.check_password("hunter2") is True
        assert user.check_password("wrong") is False


class TestAuthAPI:
    def test_register_success(self, client):
        r = client.post("/api/v1/accounts/auth/register", json={"username": "alice", "password": "passw0rd"})
        assert r.status_code == 201
        assert r.json()["username"] == "alice"
        assert "hashed_password" not in r.json()

    def test_register_duplicate_username(self, client):
        client.post("/api/v1/accounts/auth/register", json={"username": "dup", "password": "passw0rd"})
        r = client.post("/api/v1/accounts/auth/register", json={"username": "dup", "password": "other123"})
        assert r.status_code == 400

    def test_login_success(self, client):
        client.post("/api/v1/accounts/auth/register", json={"username": "luke", "password": "force42"})
        r = client.post("/api/v1/accounts/auth/login", json={"login": "luke", "password": "force42"})
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_login_wrong_password(self, client):
        client.post("/api/v1/accounts/auth/register", json={"username": "bad", "password": "force42"})
        r = client.post("/api/v1/accounts/auth/login", json={"login": "bad", "password": "wrongpw"})
        assert r.status_code == 401

    def test_me_with_jwt(self, client):
        client.post("/api/v1/accounts/auth/register", json={"username": "me", "password": "passw0rd"})
        token = client.post("/api/v1/accounts/auth/login", json={"login": "me", "password": "passw0rd"}).json()[
            "access_token"
        ]
        r = client.get("/api/v1/accounts/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["username"] == "me"

    def test_me_no_auth(self, client):
        r = client.get("/api/v1/accounts/auth/me")
        assert r.status_code == 401

    def test_me_invalid_token(self, client):
        r = client.get("/api/v1/accounts/auth/me", headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 401


class TestRoleField:
    """UserRole 枚举与 role 字段行为."""

    def test_user_default_role_is_user(self, db):
        from cndb.plugins.accounts.models import UserRole

        u = User(username="plain", email="p@example.com")
        u.set_password("pw1234")
        db.add(u)
        db.flush()  # flush 触发 SQLAlchemy default
        assert u.role == UserRole.USER.value
        assert u.role_enum == UserRole.USER
        assert u.is_system_admin is False
        assert u.is_security_admin is False
        assert u.is_audit_admin is False

    def test_system_admin_props(self, db):
        from cndb.plugins.accounts.models import UserRole

        u = User(username="sa", role=UserRole.SYSTEM_ADMIN.value)
        assert u.is_system_admin is True
        assert u.role_enum.display_name == "系统管理员"

    def test_all_roles_have_display_name(self):
        from cndb.plugins.accounts.models import UserRole

        for r in UserRole:
            assert r.display_name  # 非空


class TestAdminRegister:
    """管理员创建用户端点（/auth/admin-register）."""

    def test_admin_register_creates_system_admin(self, client, superuser_token):
        r = client.post(
            "/api/v1/accounts/auth/admin-register",
            json={
                "username": "sys1",
                "nickname": "系统管理员张三",
                "password": "pw1234",
                "role": "system_admin",
            },
            headers={"Authorization": f"Bearer {superuser_token}"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["role"] == "system_admin"
        assert body["nickname"] == "系统管理员张三"

    def test_admin_register_all_three_roles(self, client, superuser_token):
        for role in ("system_admin", "security_admin", "audit_admin"):
            r = client.post(
                "/api/v1/accounts/auth/admin-register",
                json={"username": f"u_{role}_t", "password": "pw1234", "role": role},
                headers={"Authorization": f"Bearer {superuser_token}"},
            )
            assert r.status_code == 201, r.text
            assert r.json()["role"] == role

    def test_admin_register_rejects_invalid_role(self, client, superuser_token):
        r = client.post(
            "/api/v1/accounts/auth/admin-register",
            json={"username": "bad_role_xx", "password": "pw1234", "role": "super_hero"},
            headers={"Authorization": f"Bearer {superuser_token}"},
        )
        assert r.status_code == 400

    def test_admin_register_rejects_non_superuser(self, client, db):
        # 公开注册一个普通用户
        client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "regular_xx", "password": "pw1234"},
        )
        token = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": "regular_xx", "password": "pw1234"},
        ).json()["access_token"]

        r = client.post(
            "/api/v1/accounts/auth/admin-register",
            json={"username": "new_admin", "password": "pw1234", "role": "system_admin"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403, r.text

    def test_admin_register_auto_nickname(self, client, superuser_token):
        """不传 nickname 时，自动用角色 display_name 填充."""
        r = client.post(
            "/api/v1/accounts/auth/admin-register",
            json={"username": "anon_sec", "password": "pw1234", "role": "security_admin"},
            headers={"Authorization": f"Bearer {superuser_token}"},
        )
        assert r.status_code == 201
        assert r.json()["nickname"] == "安全管理员"

    def test_public_register_rejects_role(self, client):
        """公开注册入口收窄：携带 role 字段触发 422（不再静默降级）."""
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "tricky_x", "password": "pw1234", "role": "system_admin"},
        )
        assert r.status_code == 422

    def test_list_users_requires_superuser(self, client, superuser_token):
        for u in ("a1_x", "a2_x", "a3_x"):
            client.post(
                "/api/v1/accounts/auth/admin-register",
                json={"username": u, "password": "pw1234", "role": "user"},
                headers={"Authorization": f"Bearer {superuser_token}"},
            )

        r = client.get(
            "/api/v1/accounts/auth/users",
            headers={"Authorization": f"Bearer {superuser_token}"},
        )
        assert r.status_code == 200
        assert len(r.json()) >= 3

    def test_list_users_role_filter(self, client, superuser_token):
        client.post(
            "/api/v1/accounts/auth/admin-register",
            json={"username": "sec_filter_xx", "password": "pw1234", "role": "security_admin"},
            headers={"Authorization": f"Bearer {superuser_token}"},
        )

        r = client.get(
            "/api/v1/accounts/auth/users?role_filter=security_admin",
            headers={"Authorization": f"Bearer {superuser_token}"},
        )
        assert r.status_code == 200
        for item in r.json():
            assert item["role"] == "security_admin"

    def test_update_user_role(self, client, superuser_token):
        r = client.post(
            "/api/v1/accounts/auth/admin-register",
            json={"username": "to_upgrade_x", "password": "pw1234", "role": "user"},
            headers={"Authorization": f"Bearer {superuser_token}"},
        )
        uid = r.json()["id"]

        r = client.patch(
            f"/api/v1/accounts/auth/users/{uid}/role?new_role=audit_admin",
            headers={"Authorization": f"Bearer {superuser_token}"},
        )
        assert r.status_code == 200
        assert r.json()["role"] == "audit_admin"

    def test_update_user_role_404(self, client, superuser_token):
        r = client.patch(
            "/api/v1/accounts/auth/users/99999/role?new_role=audit_admin",
            headers={"Authorization": f"Bearer {superuser_token}"},
        )
        assert r.status_code == 404

    def test_update_user_role_forbidden(self, client):
        """非 superuser 尝试修改用户角色应 403."""
        client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "plain_user", "password": "pw1234"},
        )
        token = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": "plain_user", "password": "pw1234"},
        ).json()["access_token"]
        r = client.patch(
            "/api/v1/accounts/auth/users/1/role?new_role=audit_admin",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    def test_list_users_rejects_non_superuser(self, client):
        client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "reg2_xx", "password": "pw1234"},
        )
        token = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": "reg2_xx", "password": "pw1234"},
        ).json()["access_token"]

        r = client.get(
            "/api/v1/accounts/auth/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403
