"""用户认证核心模块单元测试.

覆盖"数据恢复后无法登录"问题涉及的认证全链路，防止未来迁移/恢复
改动引入回归：

1. 凭证验证（TestPasswordVerification）：
   bcrypt 往返、错误密码、**历史/异构哈希格式防御**——Django 移植数据
   （pbkdf2_sha256$ 前缀）、空串、乱码等非 bcrypt 输入必须返回 False
   而非抛异常（否则登录接口 500）；
2. 登录端点（TestLoginEndpoint）：
   用户名/邮箱双标识登录、401（不存在/密码错/停用账号）、
   LOCAL_MODE 下登录被禁用（403）；
3. 会话管理（TestSessionManagement）：
   JWT 签发与解析、伪造签名 / 过期令牌 / sub 非整数 → 401；
4. 权限检查（TestPermissionChecks）：
   非法 role 兜底为 user、三员判定、非超管访问管理端点 403；
5. 单机模式兜底用户（TestLocalModeUser）：
   恢复旧库（无 local 用户）后 _get_local_user 幂等 get-or-create，
   保证单机模式恢复后立即可用。

每个用例按 前置条件 → 执行步骤 → 预期结果 组织，复用 conftest 的
内存库 + TestClient fixtures，相互独立、可重复。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.core.security import create_access_token, decode_access_token, hash_password, verify_password
from cndb.plugins.accounts.models import User, UserRole

LOGIN_URL = "/api/v1/accounts/auth/login"
ME_URL = "/api/v1/accounts/auth/me"
USERS_URL = "/api/v1/accounts/auth/users"


# ── 1. 凭证验证 ──────────────────────────────────────


class TestPasswordVerification:
    """密码哈希与校验，重点覆盖历史数据格式防御."""

    def test_hash_verify_roundtrip(self) -> None:
        """前置：无；步骤：hash 后 verify 相同明文；预期：True 且哈希为 bcrypt 格式."""
        hashed = hash_password("admin1234")
        assert hashed.startswith("$2")
        assert verify_password("admin1234", hashed) is True

    def test_wrong_password_returns_false(self) -> None:
        """前置：合法 bcrypt 哈希；步骤：verify 错误明文；预期：False."""
        hashed = hash_password("admin1234")
        assert verify_password("wrong-password", hashed) is False

    @pytest.mark.parametrize(
        "legacy_hash",
        [
            "pbkdf2_sha256$260000$AbCdEfGh$0123456789abcdef",  # Django 移植数据格式
            "md5$d41d8cd98f00b204e9800998ecf8427e",
            "",
            "not-a-hash-at-all",
            "$2b$12$truncated",  # 截断的 bcrypt 串
            "中文字符串",  # 非 ASCII 乱数据
        ],
        ids=["django-pbkdf2", "legacy-md5", "empty", "garbage", "truncated-bcrypt", "non-ascii"],
    )
    def test_non_bcrypt_hash_formats_return_false_not_raise(self, legacy_hash: str) -> None:
        """前置：库中存有历史/异构格式哈希（如旧版本程序或手工导入数据）；
        步骤：verify 任意明文；预期：返回 False（登录 401），绝不上抛异常导致 500."""
        assert verify_password("any-password", legacy_hash) is False

    def test_user_check_password_with_legacy_hash(self, db: Session) -> None:
        """前置：User 行的 hashed_password 为 Django 旧格式（模拟旧版备份恢复）；
        步骤：user.check_password；预期：False，不抛异常（恢复后登录得 401 而非 500）."""
        user = User(username="legacy-user", hashed_password="pbkdf2_sha256$260000$salt$hash")
        assert user.check_password("whatever") is False

    def test_unicode_password_roundtrip(self) -> None:
        """前置：无；步骤：中文+emoji 密码 hash/verify；预期：往返一致（utf-8 编码无失真）."""
        hashed = hash_password("密码🎉安全")
        assert verify_password("密码🎉安全", hashed) is True
        assert verify_password("密码安全", hashed) is False


# ── 2. 登录端点 ──────────────────────────────────────


class TestLoginEndpoint:
    """登录接口的认证分支."""

    def test_login_by_username_success(self, client: TestClient, db: Session) -> None:
        """前置：已注册用户；步骤：用户名+密码登录；预期：200 且返回 JWT."""
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "login-u1", "email": "login-u1@example.com", "password": "passw0rd"},
        )
        assert r.status_code == 201, r.text
        r = client.post(LOGIN_URL, json={"login": "login-u1", "password": "passw0rd"})
        assert r.status_code == 200, r.text
        assert r.json()["access_token"]

    def test_login_by_email_success(self, client: TestClient, db: Session) -> None:
        """前置：已注册用户；步骤：邮箱+密码登录；预期：200（邮箱标识可用）."""
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "login-u2", "email": "login-u2@example.com", "password": "passw0rd"},
        )
        assert r.status_code == 201, r.text
        r = client.post(LOGIN_URL, json={"login": "login-u2@example.com", "password": "passw0rd"})
        assert r.status_code == 200, r.text

    def test_login_unknown_user_401(self, client: TestClient) -> None:
        """前置：无对应用户；步骤：登录；预期：401，错误信息统一（不泄露用户是否存在）."""
        r = client.post(LOGIN_URL, json={"login": "no-such-user", "password": "passw0rd"})
        assert r.status_code == 401
        assert "用户名/邮箱或密码错误" in r.json()["detail"]

    def test_login_wrong_password_401(self, client: TestClient, db: Session) -> None:
        """前置：已注册用户；步骤：错误密码登录；预期：401."""
        client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "login-u3", "email": "login-u3@example.com", "password": "passw0rd"},
        )
        r = client.post(LOGIN_URL, json={"login": "login-u3", "password": "bad-password"})
        assert r.status_code == 401

    def test_login_deactivated_user_401(self, client: TestClient, db: Session) -> None:
        """前置：已注册且 is_active=False 的用户（如恢复的停用账号）；
        步骤：正确密码登录；预期：401（停用账号不可登录）."""
        user = User(username="deactivated", email="deact@example.com", is_active=False)
        user.set_password("passw0rd")
        db.add(user)
        db.commit()
        r = client.post(LOGIN_URL, json={"login": "deactivated", "password": "passw0rd"})
        assert r.status_code == 401

    def test_login_disabled_in_local_mode(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """前置：LOCAL_MODE=True（单机模式）；步骤：登录；预期：403「单机模式已禁用登录」."""
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "LOCAL_MODE", True)
        r = client.post(LOGIN_URL, json={"login": "anyone", "password": "passw0rd"})
        assert r.status_code == 403
        assert "单机模式已禁用登录" in r.json()["detail"]


# ── 3. 会话管理 ──────────────────────────────────────


class TestSessionManagement:
    """JWT 会话：签发、解析、失效场景."""

    def test_token_roundtrip(self) -> None:
        """前置：无；步骤：签发含 extra 的令牌并解析；预期：sub/username 原样还原."""
        token = create_access_token(subject=42, extra={"username": "alice"})
        payload = decode_access_token(token)
        assert payload["sub"] == "42"
        assert payload["username"] == "alice"

    def test_forged_signature_rejected(self, client: TestClient) -> None:
        """前置：用错误 secret 签发的令牌；步骤：带令牌访问 /me；预期：401."""
        from jose import jwt

        forged = jwt.encode({"sub": "1"}, "attacker-secret", algorithm="HS256")
        r = client.get(ME_URL, headers={"Authorization": f"Bearer {forged}"})
        assert r.status_code == 401

    def test_expired_token_rejected(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """前置：JWT_EXPIRE_MINUTES=-1（签发即过期）+ 已注册用户；步骤：登录后立即用该令牌访问 /me；
        预期：登录成功但 /me 401（过期会话失效）."""
        from cndb.core.config import settings

        client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "login-u4", "email": "login-u4@example.com", "password": "passw0rd"},
        )
        monkeypatch.setattr(settings, "JWT_EXPIRE_MINUTES", -1)
        r = client.post(LOGIN_URL, json={"login": "login-u4", "password": "passw0rd"})
        assert r.status_code == 200
        token = r.json()["access_token"]
        r = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_non_integer_sub_rejected(self, client: TestClient) -> None:
        """前置：sub 为非整数（伪造/损坏令牌）；步骤：访问 /me；
        预期：401，且不产生 500（deps 对非法 sub 的防御分支）."""
        token = create_access_token(subject="not-an-int")
        r = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_token_of_deleted_user_rejected(self, client: TestClient, db: Session) -> None:
        """前置：用户登录后其行被删除（如恢复备份覆盖了用户表）；
        步骤：用旧令牌访问 /me；预期：401（会话随用户数据失效，不悬挂）."""
        user = User(username="vanishing", email="vanish@example.com")
        user.set_password("passw0rd")
        db.add(user)
        db.commit()
        token = create_access_token(subject=user.id)
        db.delete(user)
        db.commit()
        r = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401


# ── 4. 权限检查 ──────────────────────────────────────


class TestPermissionChecks:
    """角色枚举兜底与三员权限判定（恢复后 role 字段正确性直接影响权限）."""

    def test_invalid_role_string_falls_back_to_user(self, db: Session) -> None:
        """前置：role 存了枚举外的值（旧版本数据或恢复的脏数据）；步骤：读 role_enum；
        预期：兜底为普通用户 user（不抛 ValueError）."""
        user = User(username="dirty-role", role="super_admin_legacy", hashed_password="x")
        assert user.role_enum == UserRole.USER
        assert user.is_system_admin is False

    def test_role_admin_flags(self, db: Session) -> None:
        """前置：三员各一行；步骤：读判定属性；预期：互斥且精确命中."""
        for role, flag in [
            (UserRole.SYSTEM_ADMIN, "is_system_admin"),
            (UserRole.SECURITY_ADMIN, "is_security_admin"),
            (UserRole.AUDIT_ADMIN, "is_audit_admin"),
        ]:
            user = User(username=f"flag-{role.value}", role=role.value, hashed_password="x")
            assert getattr(user, flag) is True
            assert user.is_system_admin == (role == UserRole.SYSTEM_ADMIN)

    def test_non_admin_cannot_list_users(self, client: TestClient, auth_headers: dict) -> None:
        """前置：普通用户 testuser（auth_headers）；步骤：GET /auth/users；预期：403."""
        r = client.get(USERS_URL, headers=auth_headers)
        assert r.status_code == 403

    def test_admin_can_list_users_with_role(self, client: TestClient, db: Session, auth_headers: dict) -> None:
        """前置：testuser 提升为超管；步骤：GET /auth/users?role_filter=user；
        预期：200 且角色过滤生效（权限配置数据在库中可正确查询）."""
        me = client.get(ME_URL, headers=auth_headers).json()
        row = db.query(User).filter(User.id == me["id"]).one()
        row.is_superuser = True
        db.commit()
        r = client.get(USERS_URL, headers=auth_headers, params={"role_filter": "user"})
        assert r.status_code == 200, r.text
        assert all(u["role"] == "user" for u in r.json())


# ── 5. 单机模式兜底用户（恢复场景关联） ──────────────


class TestLocalModeUser:
    """LOCAL_MODE 兜底用户的幂等创建 —— 恢复旧库后单机模式立即可用的保证."""

    def test_get_local_user_creates_once(self, db: Session) -> None:
        """前置：库中无 local 用户（如刚恢复的旧备份）；步骤：两次调用 _get_local_user；
        预期：首次创建（超管、随机不可知密码），第二次返回同一行（幂等）."""
        from cndb.api.deps import _get_local_user

        first = _get_local_user(db)
        assert first.username == "local"
        assert first.is_superuser is True
        second = _get_local_user(db)
        assert second.id == first.id

    def test_local_user_survives_with_existing_users(self, db: Session) -> None:
        """前置：库中已有其他用户（恢复的业务用户）；步骤：_get_local_user；
        预期：不影响既有用户，local 用户独立创建."""
        from cndb.api.deps import _get_local_user

        biz = User(username="biz-user", email="biz@example.com")
        biz.set_password("passw0rd")
        db.add(biz)
        db.commit()

        local = _get_local_user(db)
        assert local.username == "local"
        assert db.query(User).filter(User.username == "biz-user").one_or_none() is not None

    def test_local_mode_requests_map_to_local_user(
        self, client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """前置：LOCAL_MODE=True 且库中无 local 用户；步骤：无令牌访问 /me；
        预期：200 且归属内置本地用户（恢复后免登录立即可用）."""
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "LOCAL_MODE", True)
        r = client.get(ME_URL)
        assert r.status_code == 200, r.text
        assert r.json()["username"] == "local"
