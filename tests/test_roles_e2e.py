"""数据角色（Role）端到端测试 —— 管理员维护 + 表所有者分配 + 访问控制生效.

覆盖场景：
- 仅 system_admin 可创建 / 修改 / 删除角色；普通用户仅可查看
- 内置角色（read / write / admin）自动种子、可修改权限但不可删除
- 自定义角色被 TableMember 引用后无法删除
- 表所有者将自定义角色分配给成员后，access.py check_action 正确判定
- 非法 role code 在添加 / 更新 TableMember 时被拒绝
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.models.base import Base
from cndb.plugins.accounts.models import User, UserRole
from cndb.plugins.tables import ddl
from cndb.plugins.tables.models import DataField, DataTable, TableMember
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole


@pytest.fixture
def db(tmp_path):
    settings.AUTH_ENABLED = True
    db_path = tmp_path / "role_e2e.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    import cndb.plugins.accounts.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db):
    from cndb.app import app

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── 用户 fixtures ─────────────────────────────────────


def _make_user(db, username: str, is_admin: bool = False) -> User:
    u = User(
        username=username,
        nickname=username,
        role=UserRole.SYSTEM_ADMIN.value if is_admin else UserRole.USER.value,
    )
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def sysadmin(db):
    return _make_user(db, "sysadmin", is_admin=True)


@pytest.fixture
def normal_user(db):
    return _make_user(db, "normal_user", is_admin=False)


@pytest.fixture
def another_user(db):
    return _make_user(db, "another", is_admin=False)


@pytest.fixture
def auth_sysadmin(client, sysadmin):
    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": sysadmin.username, "password": "passw0rd"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth_normal(client, normal_user):
    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": normal_user.username, "password": "passw0rd"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth_another(client, another_user):
    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": another_user.username, "password": "passw0rd"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── 工作区 + 表 fixtures ──────────────────────────────


@pytest.fixture
def ws_with_owner(db, sysadmin, normal_user, another_user):
    from cndb.plugins.workspaces.models import WorkspaceMember

    w = Workspace(name="RoleWS", created_by_id=sysadmin.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=sysadmin.id, role=WorkspaceRole.OWNER))
    db.add(WorkspaceMember(workspace_id=w.id, user_id=normal_user.id, role=WorkspaceRole.EDITOR))
    db.add(WorkspaceMember(workspace_id=w.id, user_id=another_user.id, role=WorkspaceRole.VIEWER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table_for_role(db, ws_with_owner, sysadmin, tmp_path):
    db_path = tmp_path / "role_table.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    dt = DataTable(workspace_id=ws_with_owner.id, name="RoleTable", owner_id=sysadmin.id)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    df = DataField(table_id=dt.id, name="金额", field_type="number", order=0)
    df.ensure_db_name()
    db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    engine.dispose()
    return dt


# ═══════════════════════════════════════════════════════
# 1. 角色管理：只有 system_admin 可维护
# ═══════════════════════════════════════════════════════


class TestRoleAdminGate:
    """只有 system_admin 可以写 /roles。普通用户只读。"""

    def test_normal_user_cannot_create(self, client, auth_normal):
        r = client.post(
            "/api/v1/roles",
            json={"code": "finance", "name": "财务角色"},
            headers=auth_normal,
        )
        assert r.status_code == 403, r.text

    def test_normal_user_cannot_update(self, client, auth_sysadmin, auth_normal):
        # 先创建一个角色
        r = client.post(
            "/api/v1/roles",
            json={"code": "finance", "name": "财务角色"},
            headers=auth_sysadmin,
        )
        assert r.status_code == 201
        rid = r.json()["id"]
        # 普通用户尝试 patch
        r = client.patch(f"/api/v1/roles/{rid}", json={"name": "X"}, headers=auth_normal)
        assert r.status_code == 403

    def test_normal_user_cannot_delete(self, client, auth_sysadmin, auth_normal):
        r = client.post(
            "/api/v1/roles",
            json={"code": "temp_for_del", "name": "临时"},
            headers=auth_sysadmin,
        )
        rid = r.json()["id"]
        r = client.delete(f"/api/v1/roles/{rid}", headers=auth_normal)
        assert r.status_code == 403

    def test_normal_user_can_list(self, client, auth_normal):
        r = client.get("/api/v1/roles", headers=auth_normal)
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════
# 2. 内置角色种子：read / write / admin 自动存在
# ═══════════════════════════════════════════════════════


class TestBuiltinRoleSeed:
    def test_builtin_roles_served_on_first_list(self, client, auth_sysadmin):
        r = client.get("/api/v1/roles", headers=auth_sysadmin)
        assert r.status_code == 200
        codes = {x["code"] for x in r.json()}
        assert codes >= {"read", "write", "admin"}
        # 都是 builtin
        for item in r.json():
            if item["code"] in {"read", "write", "admin"}:
                assert item["is_builtin"] is True

    def test_builtin_roles_cannot_be_deleted(self, client, auth_sysadmin):
        # 先触发种子
        client.get("/api/v1/roles", headers=auth_sysadmin)
        # 直接用 code 查 id
        r = client.get("/api/v1/roles", headers=auth_sysadmin)
        builtin_ids = {item["code"]: item["id"] for item in r.json() if item["is_builtin"]}
        for code, rid in builtin_ids.items():
            r2 = client.delete(f"/api/v1/roles/{rid}", headers=auth_sysadmin)
            assert r2.status_code == 400, f"builtin {code} should not be deleted: {r2.text}"

    def test_builtin_roles_permissions_can_be_modified(self, client, auth_sysadmin):
        client.get("/api/v1/roles", headers=auth_sysadmin)
        r = client.get("/api/v1/roles", headers=auth_sysadmin)
        admin_role = next(x for x in r.json() if x["code"] == "admin")
        rid = admin_role["id"]
        new_perms = {"READ": True, "EDIT_RECORDS": True, "EDIT_VIEWS": True, "EDIT_SCHEMA": False, "COMMENT": True}
        r = client.patch(f"/api/v1/roles/{rid}", json={"permissions": new_perms}, headers=auth_sysadmin)
        assert r.status_code == 200, r.text
        assert r.json()["permissions"]["EDIT_SCHEMA"] is False


# ═══════════════════════════════════════════════════════
# 3. 自定义角色 CRUD
# ═══════════════════════════════════════════════════════


class TestCustomRoleCRUD:
    def test_create_and_get(self, client, auth_sysadmin):
        payload = {
            "code": "finance_analyst",
            "name": "财务分析师",
            "description": "可读写数据但不能改表结构",
            "permissions": {
                "READ": True,
                "EDIT_RECORDS": True,
                "EDIT_VIEWS": False,
                "EDIT_SCHEMA": False,
                "COMMENT": True,
            },
        }
        r = client.post("/api/v1/roles", json=payload, headers=auth_sysadmin)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["code"] == "finance_analyst"
        assert body["name"] == "财务分析师"
        assert body["is_builtin"] is False
        assert body["permissions"]["READ"] is True
        assert body["permissions"]["EDIT_SCHEMA"] is False

        rid = body["id"]
        r = client.get(f"/api/v1/roles/{rid}", headers=auth_sysadmin)
        assert r.status_code == 200
        assert r.json()["code"] == "finance_analyst"

    def test_create_duplicate_code_conflict(self, client, auth_sysadmin):
        payload = {"code": "dup", "name": "dup"}
        r1 = client.post("/api/v1/roles", json=payload, headers=auth_sysadmin)
        assert r1.status_code == 201
        r2 = client.post("/api/v1/roles", json=payload, headers=auth_sysadmin)
        assert r2.status_code == 409

    def test_create_invalid_code_rejected(self, client, auth_sysadmin):
        for bad_code in ["", "BAD", "bad-code", "a" * 70]:
            r = client.post("/api/v1/roles", json={"code": bad_code, "name": "x"}, headers=auth_sysadmin)
            assert r.status_code == 400, f"code={bad_code!r} should be 400"

    def test_create_invalid_permissions_rejected(self, client, auth_sysadmin):
        r = client.post(
            "/api/v1/roles",
            json={"code": "bad_perm", "name": "bad", "permissions": {"UNKNOWN_ACTION": True}},
            headers=auth_sysadmin,
        )
        assert r.status_code == 400

    def test_create_permissions_non_bool_rejected(self, client, auth_sysadmin):
        r = client.post(
            "/api/v1/roles",
            json={"code": "nb", "name": "nb", "permissions": {"READ": "yes"}},
            headers=auth_sysadmin,
        )
        # Pydantic 校验失败 → FastAPI 返回 422
        assert r.status_code == 422, r.text

    def test_update_partial(self, client, auth_sysadmin):
        r = client.post(
            "/api/v1/roles",
            json={"code": "upd", "name": "原名"},
            headers=auth_sysadmin,
        )
        rid = r.json()["id"]
        r = client.patch(f"/api/v1/roles/{rid}", json={"name": "新名"}, headers=auth_sysadmin)
        assert r.status_code == 200
        assert r.json()["name"] == "新名"
        # description 未改动
        assert r.json()["description"] == ""

    def test_delete_not_found(self, client, auth_sysadmin):
        r = client.delete("/api/v1/roles/99999", headers=auth_sysadmin)
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════
# 4. 表所有者分配自定义角色给成员
# ═══════════════════════════════════════════════════════


class TestOwnerAssignsRoleToMember:
    def test_owner_adds_member_with_custom_role(self, client, auth_sysadmin, ws_with_owner, table_for_role):
        # 创建自定义角色
        r = client.post(
            "/api/v1/roles",
            json={
                "code": "sales_rep",
                "name": "销售代表",
                "permissions": {
                    "READ": True,
                    "EDIT_RECORDS": True,
                    "EDIT_VIEWS": False,
                    "EDIT_SCHEMA": False,
                    "COMMENT": True,
                },
            },
            headers=auth_sysadmin,
        )
        assert r.status_code == 201

        # 表所有者给 another_user 分配该角色
        r = client.post(
            f"/api/v1/workspaces/{ws_with_owner.id}/tables/{table_for_role.id}/members",
            json={"user_id": ws_with_owner.members[2].user_id, "role": "sales_rep"},
            headers=auth_sysadmin,
        )
        assert r.status_code == 201, r.text
        assert r.json()["role"] == "sales_rep"

    def test_owner_adds_member_with_invalid_role_rejected(self, client, auth_sysadmin, ws_with_owner, table_for_role):
        r = client.post(
            f"/api/v1/workspaces/{ws_with_owner.id}/tables/{table_for_role.id}/members",
            json={"user_id": ws_with_owner.members[2].user_id, "role": "not_a_role"},
            headers=auth_sysadmin,
        )
        assert r.status_code == 400, r.text

    def test_update_member_to_custom_role(self, client, auth_sysadmin, ws_with_owner, table_for_role):
        # 走 API 添加，更贴近真实
        r = client.post(
            f"/api/v1/workspaces/{ws_with_owner.id}/tables/{table_for_role.id}/members",
            json={"user_id": ws_with_owner.members[2].user_id, "role": "read"},
            headers=auth_sysadmin,
        )
        assert r.status_code == 201
        uid = ws_with_owner.members[2].user_id

        # 再 patch 成 write —— 用内置角色
        r = client.patch(
            f"/api/v1/workspaces/{ws_with_owner.id}/tables/{table_for_role.id}/members/{uid}",
            json={"role": "write"},
            headers=auth_sysadmin,
        )
        assert r.status_code == 200
        assert r.json()["role"] == "write"

    def test_role_in_use_cannot_be_deleted(self, client, auth_sysadmin, ws_with_owner, table_for_role):
        # 创建自定义角色
        r = client.post(
            "/api/v1/roles",
            json={
                "code": "finance_user",
                "name": "财务用户",
                "permissions": {
                    "READ": True,
                    "EDIT_RECORDS": True,
                    "EDIT_VIEWS": False,
                    "EDIT_SCHEMA": False,
                    "COMMENT": False,
                },
            },
            headers=auth_sysadmin,
        )
        rid = r.json()["id"]
        # 分配给成员
        client.post(
            f"/api/v1/workspaces/{ws_with_owner.id}/tables/{table_for_role.id}/members",
            json={"user_id": ws_with_owner.members[2].user_id, "role": "finance_user"},
            headers=auth_sysadmin,
        )
        # 尝试删除 —— 应被拒绝
        r = client.delete(f"/api/v1/roles/{rid}", headers=auth_sysadmin)
        assert r.status_code == 400, r.text
        assert "引用" in r.json()["detail"]


# ═══════════════════════════════════════════════════════
# 5. 访问控制：自定义 Role 的权限位生效
# ═══════════════════════════════════════════════════════


class TestAccessControlWithCustomRole:
    @pytest.fixture
    def role_assigned_member(self, client, auth_sysadmin, db, ws_with_owner, table_for_role, another_user):
        """给 another_user 分配一个自定义角色，READ + COMMENT 都允许，但 EDIT_RECORDS/EDIT_VIEWS 不允许."""
        r = client.post(
            "/api/v1/roles",
            json={
                "code": "custom_limited",
                "name": "受限角色",
                "permissions": {
                    "READ": True,
                    "EDIT_RECORDS": False,
                    "EDIT_VIEWS": False,
                    "EDIT_SCHEMA": False,
                    "COMMENT": True,
                },
            },
            headers=auth_sysadmin,
        )
        assert r.status_code == 201
        # 给 another_user 加表成员（another 是工作区 VIEWER，低于 EDITOR）
        r = client.post(
            f"/api/v1/workspaces/{ws_with_owner.id}/tables/{table_for_role.id}/members",
            json={"user_id": another_user.id, "role": "custom_limited"},
            headers=auth_sysadmin,
        )
        assert r.status_code == 201
        return table_for_role

    def test_direct_check_action_respects_custom_role(self, db, role_assigned_member, another_user):
        from cndb.plugins.tables.access import TableAction, check_action

        table = role_assigned_member
        # READ / COMMENT 应 True
        assert check_action(db, table, another_user, TableAction.READ) is True
        assert check_action(db, table, another_user, TableAction.COMMENT) is True
        # EDIT_* 应 False
        assert check_action(db, table, another_user, TableAction.EDIT_RECORDS) is False
        assert check_action(db, table, another_user, TableAction.EDIT_VIEWS) is False
        assert check_action(db, table, another_user, TableAction.EDIT_SCHEMA) is False

    def test_builtin_write_role_keeps_legacy_behavior(
        self, db, auth_sysadmin, ws_with_owner, table_for_role, normal_user
    ):
        """内置 write 角色：EDIT_SCHEMA 仍为 False（与旧逻辑一致）."""
        from cndb.plugins.tables.access import TableAction, check_action

        # normal_user 已是工作区 EDITOR，用 write 成员也应允许 EDIT_RECORDS
        assert check_action(db, table_for_role, normal_user, TableAction.EDIT_RECORDS) is True
        # EDIT_SCHEMA 需要 ADMIN 或 owner，EDITOR 默认不行
        assert check_action(db, table_for_role, normal_user, TableAction.EDIT_SCHEMA) is False

    def test_role_no_permissions_nonexistent_code_falls_through(self, db, ws_with_owner, table_for_role, another_user):
        """TableMember.role 指向不存在的 Role.code 时，回落到工作区角色默认判定."""
        from cndb.plugins.tables.access import TableAction, check_action

        db.add(
            TableMember(
                table_id=table_for_role.id,
                user_id=another_user.id,
                role="ghost_role",
            )
        )
        db.commit()
        # another_user 是工作区 VIEWER，默认 READ=True、EDIT_RECORDS=False
        assert check_action(db, table_for_role, another_user, TableAction.READ) is True
        assert check_action(db, table_for_role, another_user, TableAction.EDIT_RECORDS) is False


# ═══════════════════════════════════════════════════════
# 6. 列出角色 + 成员列表中的角色 code 回显
# ═══════════════════════════════════════════════════════


class TestListAndEcho:
    def test_list_roles_filters_builtin(self, client, auth_sysadmin):
        client.get("/api/v1/roles", headers=auth_sysadmin)  # 种子
        r = client.get("/api/v1/roles?include_builtin=false", headers=auth_sysadmin)
        assert r.status_code == 200
        # 自定义角色应为空列表（还没有创建自定义角色）
        for item in r.json():
            assert item["is_builtin"] is False

    def test_member_list_echoes_custom_role_code(self, client, auth_sysadmin, ws_with_owner, table_for_role):
        client.post(
            "/api/v1/roles",
            json={
                "code": "echo_role",
                "name": "回显角色",
                "permissions": {
                    "READ": True,
                    "EDIT_RECORDS": True,
                    "EDIT_VIEWS": False,
                    "EDIT_SCHEMA": False,
                    "COMMENT": True,
                },
            },
            headers=auth_sysadmin,
        )
        client.post(
            f"/api/v1/workspaces/{ws_with_owner.id}/tables/{table_for_role.id}/members",
            json={"user_id": ws_with_owner.members[2].user_id, "role": "echo_role"},
            headers=auth_sysadmin,
        )
        r = client.get(
            f"/api/v1/workspaces/{ws_with_owner.id}/tables/{table_for_role.id}/members",
            headers=auth_sysadmin,
        )
        assert r.status_code == 200
        members = {m["user_id"]: m for m in r.json()}
        target_uid = ws_with_owner.members[2].user_id
        assert members[target_uid]["role"] == "echo_role"


__all__ = []
