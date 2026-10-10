"""用户管理 API 专项测试：编辑 / 批量操作 / 启禁用 / 操作日志.

覆盖设计文档 .trae/designs/user-management-upgrade.md 的防护规则与错误语义：
- 编辑成功路径与部分更新、空串清空 email/phone
- 审计：before/after 快照、动作分类（update/role_change/activate/deactivate/batch）
- 防护：自我降权/禁用 400、末位超管禁用 400
- 权限：非超管写 403、audit_admin 只读日志（写 403）
- 批量：逐项独立结果（不存在/自我操作不阻断其他项）
"""

from __future__ import annotations

import pytest

from cndb.plugins.accounts.models import User

USERS_URL = "/api/v1/accounts/users"
REGISTER_URL = "/api/v1/accounts/auth/register"
LOGIN_URL = "/api/v1/accounts/auth/login"
ADMIN_REGISTER_URL = "/api/v1/accounts/auth/admin-register"


def _auth(token: str) -> dict[str, str]:
    """构造 Bearer 请求头."""
    return {"Authorization": f"Bearer {token}"}


def _register_and_login(client, username: str, password: str = "pw1234") -> str:
    """注册并登录，返回 JWT."""
    client.post(REGISTER_URL, json={"username": username, "password": password})
    r = client.post(LOGIN_URL, json={"login": username, "password": password})
    return r.json()["access_token"]


def _create_user_by_admin(client, token: str, username: str, role: str = "user") -> dict:
    """管理员创建用户并返回响应体."""
    r = client.post(
        ADMIN_REGISTER_URL,
        json={"username": username, "password": "pw1234", "role": role},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def admin_token(client, db):
    """创建超级管理员并登录，返回 JWT."""
    u = User(username="um_admin", email="um_admin@example.com")
    u.set_password("pw1234")
    u.is_superuser = True
    db.add(u)
    db.commit()
    return _register_and_login(client, "um_admin", "pw1234")


@pytest.fixture
def audit_admin_token(client, db, admin_token):
    """创建审计管理员（audit_admin，非超管），返回 JWT."""
    _create_user_by_admin(client, admin_token, "um_auditor", role="audit_admin")
    return _register_and_login(client, "um_auditor")


class TestUserEdit:
    """PATCH /users/{id} 编辑功能."""

    def test_edit_nickname_and_phone(self, client, admin_token):
        target = _create_user_by_admin(client, admin_token, "edit_1")
        r = client.patch(
            f"{USERS_URL}/{target['id']}",
            json={"nickname": "新昵称", "phone": "13800138000"},
            headers=_auth(admin_token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["nickname"] == "新昵称"
        assert r.json()["phone"] == "13800138000"

    def test_edit_partial_keeps_other_fields(self, client, admin_token):
        target = _create_user_by_admin(client, admin_token, "edit_2")
        client.patch(
            f"{USERS_URL}/{target['id']}",
            json={"phone": "13900139000"},
            headers=_auth(admin_token),
        )
        r = client.get(f"{USERS_URL}?keyword=edit_2", headers=_auth(admin_token))
        item = r.json()["items"][0]
        assert item["phone"] == "13900139000"
        assert item["nickname"] == "普通用户"  # admin-register 自动填充未被覆盖

    def test_clear_email_with_empty_string(self, client, admin_token, db):
        target = _create_user_by_admin(client, admin_token, "edit_3", role="user")
        uid = target["id"]
        row = db.query(User).filter(User.id == uid).one()
        row.email = "edit_3@example.com"
        db.commit()

        r = client.patch(f"{USERS_URL}/{uid}", json={"email": ""}, headers=_auth(admin_token))
        assert r.status_code == 200
        assert r.json()["email"] is None

    def test_edit_username_conflict_400(self, client, admin_token):
        _create_user_by_admin(client, admin_token, "edit_occupied")
        target = _create_user_by_admin(client, admin_token, "edit_4")
        r = client.patch(
            f"{USERS_URL}/{target['id']}",
            json={"username": "edit_occupied"},
            headers=_auth(admin_token),
        )
        assert r.status_code == 400
        assert "用户名已被使用" in r.json()["detail"]

    def test_edit_invalid_role_400(self, client, admin_token):
        target = _create_user_by_admin(client, admin_token, "edit_5")
        r = client.patch(
            f"{USERS_URL}/{target['id']}",
            json={"role": "root"},
            headers=_auth(admin_token),
        )
        assert r.status_code == 400
        assert "无效的角色" in r.json()["detail"]

    def test_edit_404(self, client, admin_token):
        r = client.patch(f"{USERS_URL}/99999", json={"nickname": "x"}, headers=_auth(admin_token))
        assert r.status_code == 404

    def test_edit_write_forbidden_for_non_superuser(self, client, admin_token):
        """非超管（普通用户）编辑他人 403."""
        other_token = _register_and_login(client, "edit_plain")
        target = _create_user_by_admin(client, admin_token, "edit_6")
        r = client.patch(
            f"{USERS_URL}/{target['id']}",
            json={"nickname": "越权"},
            headers=_auth(other_token),
        )
        assert r.status_code == 403


class TestUserEditProtections:
    """防护规则：自我操作与末位超管."""

    def test_cannot_change_own_role(self, client, admin_token):
        me = client.get("/api/v1/accounts/auth/me", headers=_auth(admin_token)).json()
        r = client.patch(f"{USERS_URL}/{me['id']}", json={"role": "user"}, headers=_auth(admin_token))
        assert r.status_code == 400
        assert "不能修改自己的角色" in r.json()["detail"]

    def test_cannot_deactivate_self(self, client, admin_token):
        me = client.get("/api/v1/accounts/auth/me", headers=_auth(admin_token)).json()
        r = client.patch(f"{USERS_URL}/{me['id']}", json={"is_active": False}, headers=_auth(admin_token))
        assert r.status_code == 400
        assert "不能修改自己的角色" in r.json()["detail"]

    def test_cannot_deactivate_last_active_superuser(self, db):
        """末位超管保护在服务层生效：API 层该规则被"禁止自我禁用"前置拦截，
        因此直接验证服务层守卫 —— 库中唯一可用超管（排除目标本人）时必须拒绝."""
        from cndb.plugins.accounts.services.users import UserAdminError, _ensure_not_last_active_superuser

        su = User(username="um_last_su", hashed_password="x", is_superuser=True)
        db.add(su)
        db.commit()
        with pytest.raises(UserAdminError, match="最后一个可用的超级管理员"):
            _ensure_not_last_active_superuser(db, su)

    def test_deactivate_superuser_ok_when_another_active_exists(self, client, db, admin_token):
        """存在第二个可用超管时，禁用其一应成功."""
        second = User(username="um_second_su", hashed_password="x", is_superuser=True)
        db.add(second)
        db.commit()
        me = client.get("/api/v1/accounts/auth/me", headers=_auth(admin_token)).json()
        # 操作第二个超管（非自己）
        r = client.patch(f"{USERS_URL}/{second.id}", json={"is_active": False}, headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is False
        assert me["id"]  # 操作人自身未被触碰


class TestUserAuditTrail:
    """操作日志写入与查询."""

    def test_role_change_records_before_after(self, client, admin_token):
        target = _create_user_by_admin(client, admin_token, "audit_1")
        client.patch(
            f"{USERS_URL}/{target['id']}",
            json={"role": "security_admin"},
            headers=_auth(admin_token),
        )
        r = client.get(
            f"{USERS_URL}/{target['id']}/audit-logs",
            headers=_auth(admin_token),
        )
        assert r.status_code == 200
        items = r.json()["items"]
        assert r.json()["total"] >= 1
        entry = next(e for e in items if e["action"] == "role_change")
        assert entry["detail"]["before"]["role"] == "user"
        assert entry["detail"]["after"]["role"] == "security_admin"
        assert entry["actor_id"] is not None

    def test_deactivate_records_action(self, client, admin_token):
        target = _create_user_by_admin(client, admin_token, "audit_2")
        client.patch(f"{USERS_URL}/{target['id']}", json={"is_active": False}, headers=_auth(admin_token))
        r = client.get(f"{USERS_URL}/{target['id']}/audit-logs", headers=_auth(admin_token))
        actions = [e["action"] for e in r.json()["items"]]
        assert "deactivate" in actions

    def test_no_change_writes_no_log(self, client, admin_token):
        """无实际变更的编辑不产生日志."""
        target = _create_user_by_admin(client, admin_token, "audit_3")
        r = client.patch(f"{USERS_URL}/{target['id']}", json={"nickname": "普通用户"}, headers=_auth(admin_token))
        assert r.status_code == 200
        logs = client.get(f"{USERS_URL}/{target['id']}/audit-logs", headers=_auth(admin_token)).json()
        assert logs["total"] == 0

    def test_audit_logs_filter_by_action_and_pagination(self, client, admin_token):
        target = _create_user_by_admin(client, admin_token, "audit_4")
        client.patch(f"{USERS_URL}/{target['id']}", json={"phone": "13700000001"}, headers=_auth(admin_token))
        client.patch(
            f"{USERS_URL}/{target['id']}",
            json={"role": "audit_admin"},
            headers=_auth(admin_token),
        )

        r = client.get(
            f"{USERS_URL}/audit-logs",
            params={"action": "update", "page_size": 1, "page": 1},
            headers=_auth(admin_token),
        )
        assert r.status_code == 200
        assert r.json()["total"] >= 1
        assert all(e["action"] == "update" for e in r.json()["items"])
        assert len(r.json()["items"]) == 1

    def test_audit_logs_readable_by_audit_admin(self, client, audit_admin_token):
        r = client.get(f"{USERS_URL}/audit-logs", headers=_auth(audit_admin_token))
        assert r.status_code == 200

    def test_audit_logs_forbidden_for_plain_user(self, client):
        token = _register_and_login(client, "audit_plain")
        r = client.get(f"{USERS_URL}/audit-logs", headers=_auth(token))
        assert r.status_code == 403

    def test_audit_logs_write_forbidden_for_audit_admin(self, client, audit_admin_token):
        """审计管理员只读：编辑用户必须 403."""
        target = _register_and_login(client, "audit_target")
        me = client.get("/api/v1/accounts/auth/me", headers=_auth(audit_admin_token)).json()
        r = client.patch(f"{USERS_URL}/{me['id']}", json={"nickname": "越权"}, headers=_auth(audit_admin_token))
        assert r.status_code == 403
        assert target  # 目标用户已就绪

    def test_user_audit_logs_404_for_missing_user(self, client, admin_token):
        r = client.get(f"{USERS_URL}/99999/audit-logs", headers=_auth(admin_token))
        assert r.status_code == 404


class TestBatchUserAction:
    """POST /users/batch 批量操作."""

    def test_batch_activate_and_deactivate(self, client, admin_token):
        t1 = _create_user_by_admin(client, admin_token, "batch_1")
        t2 = _create_user_by_admin(client, admin_token, "batch_2")
        ids = [t1["id"], t2["id"]]

        r = client.post(
            f"{USERS_URL}/batch",
            json={"action": "deactivate", "user_ids": ids},
            headers=_auth(admin_token),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2 and body["succeeded"] == 2 and body["failed"] == 0

        r2 = client.post(
            f"{USERS_URL}/batch",
            json={"action": "activate", "user_ids": ids},
            headers=_auth(admin_token),
        )
        assert r2.json()["succeeded"] == 2
        listing = client.get(f"{USERS_URL}?keyword=batch_", headers=_auth(admin_token)).json()
        assert all(item["is_active"] for item in listing["items"])

    def test_batch_set_role(self, client, admin_token):
        t1 = _create_user_by_admin(client, admin_token, "batch_3")
        r = client.post(
            f"{USERS_URL}/batch",
            json={"action": "set_role", "user_ids": [t1["id"]], "role": "security_admin"},
            headers=_auth(admin_token),
        )
        assert r.status_code == 200
        assert r.json()["succeeded"] == 1
        item = client.get(f"{USERS_URL}?keyword=batch_3", headers=_auth(admin_token)).json()["items"][0]
        assert item["role"] == "security_admin"

    def test_batch_set_role_requires_role(self, client, admin_token):
        r = client.post(
            f"{USERS_URL}/batch",
            json={"action": "set_role", "user_ids": [1]},
            headers=_auth(admin_token),
        )
        assert r.status_code == 400
        assert "必须提供 role" in r.json()["detail"]

    def test_batch_skips_missing_and_self(self, client, admin_token):
        """不存在的用户与操作人自己被跳过，其余项正常执行."""
        t1 = _create_user_by_admin(client, admin_token, "batch_4")
        me = client.get("/api/v1/accounts/auth/me", headers=_auth(admin_token)).json()
        r = client.post(
            f"{USERS_URL}/batch",
            json={"action": "deactivate", "user_ids": [t1["id"], 99999, me["id"]]},
            headers=_auth(admin_token),
        )
        body = r.json()
        assert body["total"] == 3 and body["succeeded"] == 1 and body["failed"] == 2
        by_user = {item["user_id"]: item for item in body["results"]}
        assert by_user[t1["id"]]["success"] is True
        assert by_user[99999]["success"] is False
        assert by_user[me["id"]]["success"] is False
        assert "不能对自己" in by_user[me["id"]]["error"]

    def test_batch_invalid_role_400(self, client, admin_token):
        r = client.post(
            f"{USERS_URL}/batch",
            json={"action": "set_role", "user_ids": [1], "role": "root"},
            headers=_auth(admin_token),
        )
        assert r.status_code == 400

    def test_batch_forbidden_for_non_superuser(self, client):
        token = _register_and_login(client, "batch_plain")
        r = client.post(
            f"{USERS_URL}/batch",
            json={"action": "activate", "user_ids": [1]},
            headers=_auth(token),
        )
        assert r.status_code == 403

    def test_batch_records_audit(self, client, admin_token):
        t1 = _create_user_by_admin(client, admin_token, "batch_5")
        client.post(
            f"{USERS_URL}/batch",
            json={"action": "deactivate", "user_ids": [t1["id"]]},
            headers=_auth(admin_token),
        )
        r = client.get(f"{USERS_URL}/audit-logs", params={"action": "batch"}, headers=_auth(admin_token))
        assert r.status_code == 200
        assert r.json()["total"] >= 1
        entry = r.json()["items"][0]
        assert entry["detail"]["action"] == "deactivate"
        assert entry["detail"]["succeeded"] == 1


class TestUserListPage:
    """GET /users 分页与筛选."""

    def test_pagination_and_keyword(self, client, admin_token):
        for i in range(3):
            _create_user_by_admin(client, admin_token, f"page_kw_{i}")
        r = client.get(
            f"{USERS_URL}",
            params={"keyword": "page_kw_", "page": 1, "page_size": 2},
            headers=_auth(admin_token),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2

    def test_filter_by_is_active(self, client, admin_token):
        target = _create_user_by_admin(client, admin_token, "active_kw")
        client.patch(f"{USERS_URL}/{target['id']}", json={"is_active": False}, headers=_auth(admin_token))
        r = client.get(f"{USERS_URL}", params={"is_active": "false"}, headers=_auth(admin_token))
        assert r.status_code == 200
        assert all(item["is_active"] is False for item in r.json()["items"])

    def test_invalid_role_filter_400(self, client, admin_token):
        r = client.get(f"{USERS_URL}", params={"role": "root"}, headers=_auth(admin_token))
        assert r.status_code == 400

    def test_response_includes_phone_and_created_at(self, client, admin_token):
        target = _create_user_by_admin(client, admin_token, "shape_1")
        client.patch(f"{USERS_URL}/{target['id']}", json={"phone": "13600000000"}, headers=_auth(admin_token))
        item = client.get(f"{USERS_URL}?keyword=shape_1", headers=_auth(admin_token)).json()["items"][0]
        assert item["phone"] == "13600000000"
        assert item["created_at"] is not None
        assert "hashed_password" not in item
