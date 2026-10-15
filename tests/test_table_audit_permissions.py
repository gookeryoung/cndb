"""表审计日志不得泄露受限表的行数据.

**修复背景**：`AuditLog.detail` 在 create/update 时写入**整行数据快照**（`detail=row`），
而 `GET /workspaces/{wid}/tables/{tid}/audit` 原先只校验工作区 EDITOR、未校验 `TableAction.READ`：
- 受限表（`read_role = owner/editor`）的行数据可被任何编辑者通过审计日志读到；
- 也未按 `row_filters` 裁剪（被行级规则挡住的行仍出现在审计里）；
- 也未按角色的 `hidden_fields` 剔除字段。

修法：审计与记录读取保持同一口径 —— READ 权限 + 行级过滤 + 字段隐藏。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

TABLES = "/api/v1/workspaces/{ws}/tables"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class Env:
    def __init__(self, db: Session) -> None:
        self.owner = _user(db, "aud_owner")
        self.ws = Workspace(name="AuditWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        self.editor = _user(db, "aud_editor")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.editor.id, role=WorkspaceRole.EDITOR))
        self.viewer = _user(db, "aud_viewer")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()


def _table_with_rows(
    client: TestClient, env: Env, *, name: str, rows: list[dict], fields: list[str] | None = None
) -> int:
    auth = _login(client, env.owner.username)
    r = client.post(TABLES.format(ws=env.ws.id), json={"name": name, "description": ""}, headers=auth)
    assert r.status_code == 201, r.text
    tid = int(r.json()["id"])
    for idx, fname in enumerate(fields or ["名称"]):
        r = client.post(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/fields",
            json={"name": fname, "field_type": "text", "order": idx},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text
    for values in rows:
        r = client.post(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/records",
            json={"values": values},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text
    return tid


def _set_permission(client: TestClient, env: Env, tid: int, payload: dict) -> None:
    r = client.put(
        f"{TABLES.format(ws=env.ws.id)}/{tid}/permissions",
        json=payload,
        headers=_login(client, env.owner.username),
    )
    assert r.status_code in (200, 201), r.text


def _audit(client: TestClient, env: Env, tid: int, username: str) -> tuple[int, list]:
    r = client.get(f"{TABLES.format(ws=env.ws.id)}/{tid}/audit", headers=_login(client, username))
    try:
        body = r.json()
    except Exception:
        body = []
    return r.status_code, body if isinstance(body, list) else []


class TestAuditRequiresTableRead:
    def test_viewer_forbidden(self, client, db):
        env = Env(db)
        tid = _table_with_rows(client, env, name="普通表", rows=[{"名称": "A"}])
        status, _ = _audit(client, env, tid, env.viewer.username)
        assert status == 403

    def test_editor_cannot_read_audit_of_restricted_table(self, client, db):
        """核心回归：受限表的审计含整行数据快照，编辑者不得读取."""
        env = Env(db)
        tid = _table_with_rows(client, env, name="仅所有者表", rows=[{"名称": "SECRET-AUDIT"}])
        _set_permission(client, env, tid, {"read_role": "owner"})

        status, body = _audit(client, env, tid, env.editor.username)
        assert status == 403, f"编辑者不应能读受限表审计：{status} {body}"
        assert "SECRET-AUDIT" not in str(body)

    def test_owner_can_read_restricted_table_audit(self, client, db):
        env = Env(db)
        tid = _table_with_rows(client, env, name="仅所有者表2", rows=[{"名称": "OWNER-SEES"}])
        _set_permission(client, env, tid, {"read_role": "owner"})

        status, body = _audit(client, env, tid, env.owner.username)
        assert status == 200, status
        assert "OWNER-SEES" in str(body)

    def test_editor_can_read_audit_of_readable_table(self, client, db):
        env = Env(db)
        tid = _table_with_rows(client, env, name="可读表", rows=[{"名称": "VISIBLE-ROW"}])
        status, body = _audit(client, env, tid, env.editor.username)
        assert status == 200, status
        assert "VISIBLE-ROW" in str(body)


class TestAuditHonoursRowAndFieldPolicy:
    def test_row_filters_hide_out_of_scope_audit_entries(self, client, db):
        env = Env(db)
        tid = _table_with_rows(client, env, name="行过滤表", rows=[{"名称": "KEEP"}, {"名称": "DROP"}])
        _set_permission(
            client,
            env,
            tid,
            {"read_role": "viewer", "row_filters": [{"field_name": "名称", "op": "=", "value": "KEEP"}]},
        )

        status, body = _audit(client, env, tid, env.editor.username)
        assert status == 200, status
        raw = str(body)
        assert "KEEP" in raw
        assert "DROP" not in raw, "行级过滤未在审计日志中生效"

        # 所有者同样受行级过滤限制（与记录读取一致：row_filters 无角色维度）
        owner_status, owner_body = _audit(client, env, tid, env.owner.username)
        assert owner_status == 200
        assert "DROP" not in str(owner_body)

    def test_hidden_fields_are_stripped_from_audit_detail(self, client, db):
        env = Env(db)
        tid = _table_with_rows(
            client,
            env,
            name="字段隐藏表",
            fields=["名称", "机密"],
            rows=[{"名称": "ROW-1", "机密": "SECRET-FIELD"}],
        )
        _set_permission(client, env, tid, {"hidden_fields": {"editor": ["机密"]}})

        status, body = _audit(client, env, tid, env.editor.username)
        assert status == 200, status
        assert "SECRET-FIELD" not in str(body), "隐藏字段出现在审计 detail 中"

        # 所有者未被隐藏 → 仍可见该字段
        owner_status, owner_body = _audit(client, env, tid, env.owner.username)
        assert owner_status == 200
        assert "SECRET-FIELD" in str(owner_body)
