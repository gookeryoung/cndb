"""行级过滤的口径统一：所有者/超管豁免，普通成员仍受限.

**统一前的口径冲突**：
- `check_action` 优先级链（表拥有者 → 工作区 OWNER → 表成员授权 → 角色阈值 → 工作区默认）
  与 `hidden_fields`（按角色键，未给 owner 键则不隐藏）都体现"所有者拥有全部权限"；
- 而 `TablePermission.row_filters` 没有角色维度，对所有人生效（含 OWNER），
  表现为"表所有者看不到自己表里的部分行"。

**统一后**：`row_filters_bypass()`（表所有者 / 工作区 OWNER / 超管）豁免行过滤；
其余成员仍受行级规则约束；``user is None`` 的内部/后台调用保持不变（过滤仍生效）。

本文件同时锁定：读取、写入（越界行不可改）、审计、导出四处口径一致。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

TABLES = "/api/v1/workspaces/{ws}/tables"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user(db: Session, username: str, *, superuser: bool = False) -> User:
    u = User(username=username, nickname=username, is_superuser=superuser)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class Env:
    """工作区：OWNER(wsowner) / EDITOR(editor) / VIEWER(viewer) / 超管成员(root，角色 VIEWER)."""

    def __init__(self, db: Session) -> None:
        self.ws_owner = _user(db, "rb_wsowner")
        self.ws = Workspace(name="RowBypassWS", created_by_id=self.ws_owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.ws_owner.id, role=WorkspaceRole.OWNER))
        self.editor = _user(db, "rb_editor")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.editor.id, role=WorkspaceRole.EDITOR))
        self.viewer = _user(db, "rb_viewer")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        self.root = _user(db, "rb_root", superuser=True)
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.root.id, role=WorkspaceRole.VIEWER))
        db.commit()


def _setup(client: TestClient, db: Session) -> tuple[Env, int, dict[str, int]]:
    """建表（含 2 行）+ 配置行过滤（只看 status=public），返回 (env, table_id, 行 id 映射)."""
    env = Env(db)
    auth = _login(client, env.ws_owner.username)
    r = client.post(TABLES.format(ws=env.ws.id), json={"name": "行过滤表", "description": ""}, headers=auth)
    assert r.status_code == 201, r.text
    tid = int(r.json()["id"])
    for idx, fname in enumerate(["status", "secret_note"]):
        client.post(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/fields",
            json={"name": fname, "field_type": "text", "order": idx},
            headers=auth,
        )
    row_ids: dict[str, int] = {}
    for values in (
        {"status": "secret", "secret_note": "SECRET-ROW"},
        {"status": "public", "secret_note": "PUBLIC-ROW"},
    ):
        r = client.post(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/records",
            json={"values": values},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text
        row_ids[values["status"]] = int(r.json()["id"])

    r = client.put(
        f"{TABLES.format(ws=env.ws.id)}/{tid}/permissions",
        json={"read_role": "viewer", "row_filters": [{"field_name": "status", "op": "=", "value": "public"}]},
        headers=auth,
    )
    assert r.status_code in (200, 201), r.text
    return env, tid, row_ids


def _list(client: TestClient, env: Env, tid: int, username: str) -> list[dict]:
    r = client.post(
        f"{TABLES.format(ws=env.ws.id)}/{tid}/records/list",
        json={"limit": 50, "offset": 0},
        headers=_login(client, username),
    )
    assert r.status_code == 200, r.text
    return r.json()["items"]


class TestOwnerBypass:
    def test_workspace_owner_sees_all_rows(self, client, db):
        env, tid, _rows = _setup(client, db)
        statuses = sorted(r["status"] for r in _list(client, env, tid, env.ws_owner.username))
        assert statuses == ["public", "secret"]

    def test_table_owner_without_workspace_owner_role_sees_all_rows(self, client, db):
        """表所有者（此处为 workspace EDITOR）同样豁免."""
        env, tid, _rows = _setup(client, db)
        table = db.get(DataTable, tid)
        table.owner_id = env.editor.id
        db.commit()

        statuses = sorted(r["status"] for r in _list(client, env, tid, env.editor.username))
        assert statuses == ["public", "secret"]

    def test_superuser_member_sees_all_rows(self, client, db):
        env, tid, _rows = _setup(client, db)
        statuses = sorted(r["status"] for r in _list(client, env, tid, env.root.username))
        assert statuses == ["public", "secret"]


class TestMembersStayFiltered:
    def test_plain_editor_and_viewer_filtered(self, client, db):
        env, tid, _rows = _setup(client, db)
        for username in (env.editor.username, env.viewer.username):
            rows = _list(client, env, tid, username)
            assert [r["status"] for r in rows] == ["public"], (username, rows)

    def test_out_of_scope_row_cannot_be_updated(self, client, db):
        env, tid, rows = _setup(client, db)
        r = client.patch(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/records/{rows['secret']}",
            json={"values": {"secret_note": "hacked"}},
            headers=_login(client, env.editor.username),
        )
        assert r.status_code in (403, 404), f"越界行不应可写：{r.status_code} {r.text[:120]}"

    def test_internal_call_without_user_still_filtered(self, client, db):
        """``user=None``（内部/后台）保持既有行为：行过滤仍生效."""
        _env, tid, _rows = _setup(client, db)
        table = db.get(DataTable, tid)
        items, total = rec.list_rows(db.get_bind(), table, db=db, user=None, limit=50)
        assert total == 1, (total, items)
        assert items[0]["status"] == "public"


class TestAuditAndExportConsistency:
    def test_audit_follows_same_bypass(self, client, db):
        env, tid, _rows = _setup(client, db)
        owner_audit = client.get(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/audit", headers=_login(client, env.ws_owner.username)
        )
        assert owner_audit.status_code == 200
        assert "SECRET-ROW" in str(owner_audit.json())

        editor_audit = client.get(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/audit", headers=_login(client, env.editor.username)
        )
        assert editor_audit.status_code == 200
        assert "SECRET-ROW" not in str(editor_audit.json())

    def test_export_follows_same_bypass(self, client, db):
        env, _tid, _rows = _setup(client, db)
        owner_export = client.get(
            f"/api/v1/workspaces/{env.ws.id}/export", headers=_login(client, env.ws_owner.username)
        )
        assert owner_export.status_code == 200
        assert "SECRET-ROW" in str(owner_export.json())

        # 非所有者的编辑者导出：受行过滤约束（第 9 轮引入的导出权限要求 EDITOR+）
        editor_export = client.get(
            f"/api/v1/workspaces/{env.ws.id}/export", headers=_login(client, env.editor.username)
        )
        assert editor_export.status_code == 200
        assert "SECRET-ROW" not in str(editor_export.json())
