"""行级权限规则写入面（ADR 0004 P2）—— CRUD / subjects / preview / 审计 / 缓存 / 备份.

覆盖：
1. CRUD 需 ``EDIT_SCHEMA``（viewer → 403）；
2. 创建 / 列表 / 改 / 删 + 主体展示名；
3. 授权校验：member_role 档位、user 成员范围、不得给自己配规则、重复 → 400；
4. ``subjects``：含固定档位 + 本工作区有 READ 的成员，排除操作者本人；
5. ``preview``：命中行数 + 样例；
6. 规则变更写 ``tables_auditlog``（``row_rule_*``）；
7. 规则变更失效表列表 + 记录列表缓存（ADR §7-7）；
8. 备份导出含 ``row_permissions``，导入按新表 id 还原（旧版备份缺键 → 无规则）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.core.cache import cache_key, list_cache
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import AuditLog, DataTable, RowPermission
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

TABLES = "/api/v1/workspaces/{ws}/tables"
RULES = "/api/v1/workspaces/{ws}/tables/{tid}/row-permissions"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class Env:
    def __init__(self, db: Session) -> None:
        self.owner = _make_user(db, "rowperm_owner")
        self.ws = Workspace(name="RowPermWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        self.editor = _make_user(db, "rowperm_editor")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.editor.id, role=WorkspaceRole.EDITOR))
        self.viewer = _make_user(db, "rowperm_viewer")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()


def _setup(client: TestClient, db: Session) -> tuple[Env, int]:
    env = Env(db)
    auth = _login(client, env.owner.username)
    r = client.post(TABLES.format(ws=env.ws.id), json={"name": "行规则表"}, headers=auth)
    assert r.status_code == 201, r.text
    tid = int(r.json()["id"])
    for order, name in enumerate(["status", "tag"]):
        rr = client.post(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/fields",
            json={"name": name, "field_type": "text", "order": order},
            headers=auth,
        )
        assert rr.status_code in (200, 201), rr.text
    for status in ("public", "secret", "draft"):
        rr = client.post(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/records",
            json={"values": {"status": status, "tag": "t"}},
            headers=auth,
        )
        assert rr.status_code in (200, 201), rr.text
    return env, tid


class TestCrud:
    def test_member_role_rule_lifecycle(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.owner.username)
        url = RULES.format(ws=env.ws.id, tid=tid)

        r = client.post(
            url,
            json={
                "subject_type": "member_role",
                "subject_id": "read",
                "action": "view",
                "filters": [{"field_name": "status", "op": "=", "value": "public"}],
                "filter_type": "AND",
            },
            headers=auth,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["subject_type"] == "member_role"
        assert body["subject_name"] == "查看者"
        rule_id = body["id"]

        r = client.get(url, headers=auth)
        assert r.status_code == 200
        assert len(r.json()) == 1

        r = client.patch(
            f"{url}/{rule_id}",
            json={"filters": [{"field_name": "status", "op": "=", "value": "secret"}], "filter_type": "OR"},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert r.json()["filters"][0]["value"] == "secret"
        assert r.json()["filter_type"] == "OR"

        r = client.delete(f"{url}/{rule_id}", headers=auth)
        assert r.status_code == 204
        assert client.get(url, headers=auth).json() == []

    def test_user_rule_subject_name(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.owner.username)
        r = client.post(
            RULES.format(ws=env.ws.id, tid=tid),
            json={
                "subject_type": "user",
                "subject_id": str(env.viewer.id),
                "action": "edit",
                "filters": [{"field_name": "status", "op": "=", "value": "secret"}],
            },
            headers=auth,
        )
        assert r.status_code == 201, r.text
        assert r.json()["subject_name"] == env.viewer.username

    def test_duplicate_subject_action_rejected(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.owner.username)
        url = RULES.format(ws=env.ws.id, tid=tid)
        payload = {"subject_type": "member_role", "subject_id": "write", "action": "edit", "filters": []}
        assert client.post(url, json=payload, headers=auth).status_code == 201
        r = client.post(url, json=payload, headers=auth)
        assert r.status_code == 400
        assert "已存在" in r.json()["detail"]

    def test_delete_missing_rule_404(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.owner.username)
        assert client.delete(f"{RULES.format(ws=env.ws.id, tid=tid)}/99999", headers=auth).status_code == 404


class TestAuthorization:
    def test_viewer_cannot_read_rules(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.viewer.username)
        r = client.get(RULES.format(ws=env.ws.id, tid=tid), headers=auth)
        assert r.status_code == 403

    def test_viewer_cannot_create_rule(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.viewer.username)
        r = client.post(
            RULES.format(ws=env.ws.id, tid=tid),
            json={"subject_type": "member_role", "subject_id": "read", "action": "view", "filters": []},
            headers=auth,
        )
        assert r.status_code == 403

    def test_viewer_cannot_read_subjects(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.viewer.username)
        assert client.get(f"{RULES.format(ws=env.ws.id, tid=tid)}/subjects", headers=auth).status_code == 403


class TestValidation:
    def test_bad_member_role_tier(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.owner.username)
        r = client.post(
            RULES.format(ws=env.ws.id, tid=tid),
            json={"subject_type": "member_role", "subject_id": "boss", "action": "view", "filters": []},
            headers=auth,
        )
        assert r.status_code == 422

    def test_user_not_in_workspace(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.owner.username)
        r = client.post(
            RULES.format(ws=env.ws.id, tid=tid),
            json={"subject_type": "user", "subject_id": "99999", "action": "view", "filters": []},
            headers=auth,
        )
        assert r.status_code == 422

    def test_cannot_rule_for_self(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.owner.username)
        r = client.post(
            RULES.format(ws=env.ws.id, tid=tid),
            json={"subject_type": "user", "subject_id": str(env.owner.id), "action": "view", "filters": []},
            headers=auth,
        )
        assert r.status_code == 400


class TestSubjects:
    def test_subjects_include_tiers_and_members_exclude_operator(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.owner.username)
        r = client.get(f"{RULES.format(ws=env.ws.id, tid=tid)}/subjects", headers=auth)
        assert r.status_code == 200
        rows = r.json()
        keys = {(row["subject_type"], row["subject_id"]) for row in rows}
        assert ("member_role", "read") in keys
        assert ("member_role", "write") in keys
        assert ("user", str(env.editor.id)) in keys
        assert ("user", str(env.viewer.id)) in keys
        # 操作者本人不在候选里
        assert ("user", str(env.owner.id)) not in keys


class TestPreview:
    def test_preview_matches_filtered_rows(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{RULES.format(ws=env.ws.id, tid=tid)}/preview",
            json={"filters": [{"field_name": "status", "op": "=", "value": "public"}], "filter_type": "AND"},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert r.json()["matched"] == 1
        assert len(r.json()["sample"]) == 1
        assert r.json()["sample"][0]["status"] == "public"

    def test_preview_empty_filters_matches_all(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{RULES.format(ws=env.ws.id, tid=tid)}/preview",
            json={"filters": [], "filter_type": "AND"},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert r.json()["matched"] == 3


class TestAuditAndCache:
    def test_rule_change_writes_audit(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.owner.username)
        client.post(
            RULES.format(ws=env.ws.id, tid=tid),
            json={"subject_type": "member_role", "subject_id": "read", "action": "view", "filters": []},
            headers=auth,
        )
        entry = db.query(AuditLog).filter(AuditLog.table_id == tid, AuditLog.action == "row_rule_create").first()
        assert entry is not None
        assert entry.detail["subject_id"] == "read"

    def test_rule_change_invalidates_caches(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.owner.username)
        list_cache.set(cache_key("tables", env.ws.id), {"stale": True}, 60)
        list_cache.set(cache_key("records", env.ws.id), {"stale": True}, 60)
        r = client.post(
            RULES.format(ws=env.ws.id, tid=tid),
            json={"subject_type": "member_role", "subject_id": "write", "action": "view", "filters": []},
            headers=auth,
        )
        assert r.status_code == 201, r.text
        assert list_cache.get(cache_key("tables", env.ws.id)) is None
        assert list_cache.get(cache_key("records", env.ws.id)) is None


class TestBackupRoundtrip:
    def test_export_and_import_row_rules(self, client, db):
        env, tid = _setup(client, db)
        auth = _login(client, env.owner.username)
        client.post(
            RULES.format(ws=env.ws.id, tid=tid),
            json={
                "subject_type": "member_role",
                "subject_id": "read",
                "action": "view",
                "filters": [{"field_name": "status", "op": "=", "value": "public"}],
            },
            headers=auth,
        )
        client.post(
            RULES.format(ws=env.ws.id, tid=tid),
            json={"subject_type": "user", "subject_id": str(env.viewer.id), "action": "edit", "filters": []},
            headers=auth,
        )

        backup = client.get(f"/api/v1/workspaces/{env.ws.id}/export", headers=auth).json()
        exported = backup["tables"][0]["row_permissions"]
        assert len(exported) == 2
        assert {r["subject_id"] for r in exported} == {"read", str(env.viewer.id)}

        r = client.post("/api/v1/workspaces/import", json={"json_data": backup}, headers=auth)
        assert r.status_code == 201, r.text
        new_ws_id = int(r.json()["workspace"]["id"])
        new_table = db.query(DataTable).filter(DataTable.workspace_id == new_ws_id).first()
        assert new_table is not None
        restored = db.query(RowPermission).filter(RowPermission.table_id == new_table.id).all()
        assert len(restored) == 2
        assert {(r.subject_type, r.subject_id, r.action) for r in restored} == {
            ("member_role", "read", "view"),
            ("user", str(env.viewer.id), "edit"),
        }

    def test_legacy_backup_without_row_rules_restores_none(self, client, db):
        env, _tid = _setup(client, db)
        auth = _login(client, env.owner.username)
        backup = client.get(f"/api/v1/workspaces/{env.ws.id}/export", headers=auth).json()
        # 模拟旧版备份：去掉 row_permissions 键
        for tbl in backup["tables"]:
            tbl.pop("row_permissions", None)
        r = client.post("/api/v1/workspaces/import", json={"json_data": backup}, headers=auth)
        assert r.status_code == 201, r.text
        new_ws_id = int(r.json()["workspace"]["id"])
        new_table = db.query(DataTable).filter(DataTable.workspace_id == new_ws_id).first()
        assert db.query(RowPermission).filter(RowPermission.table_id == new_table.id).count() == 0


__all__ = []
