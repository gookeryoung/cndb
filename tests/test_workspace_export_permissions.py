"""工作区导出不得绕过表权限 / 行级过滤.

**修复背景**：`GET /workspaces/{id}/export` 原先只校验「工作区成员」，随后直接
`db.query(DataTable)` 导出**所有表的所有数据行**：
- 绕过 `check_action(TableAction.READ)`：`read_role = owner/editor` 的受限表也被导出；
- 绕过 `TablePermission.row_filters`：被行级规则挡住的行同样出现在导出里。

修法：守卫与导入端口对齐（EDITOR+），逐表按 READ 判定（复用批量预取），
导出数据行时叠加行级过滤条件 —— 与读取接口保持同一口径。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

TABLES = "/api/v1/workspaces/{ws}/tables"
EXPORT = "/api/v1/workspaces/{ws}/export"


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
        self.owner = _user(db, "exp_owner")
        self.ws = Workspace(name="ExportWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        self.editor = _user(db, "exp_editor")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.editor.id, role=WorkspaceRole.EDITOR))
        self.viewer = _user(db, "exp_viewer")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()


def _create_table_with_rows(client: TestClient, env: Env, *, name: str, values: list[str]) -> int:
    """建表 + 「名称」字段 + 若干数据行，返回表 id（全部走 API，兼容中文列名）."""
    auth = _login(client, env.owner.username)
    r = client.post(TABLES.format(ws=env.ws.id), json={"name": name, "description": ""}, headers=auth)
    assert r.status_code == 201, r.text
    tid = int(r.json()["id"])
    r = client.post(
        f"{TABLES.format(ws=env.ws.id)}/{tid}/fields",
        json={"name": "名称", "field_type": "text", "order": 0},
        headers=auth,
    )
    assert r.status_code in (200, 201), r.text
    for value in values:
        r = client.post(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/records",
            json={"values": {"名称": value}},
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


def _export(client: TestClient, env: Env, username: str) -> tuple[int, dict]:
    r = client.get(EXPORT.format(ws=env.ws.id), headers=_login(client, username))
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, body


def _table_names(body: dict) -> list[str]:
    return [t["name"] for t in body.get("tables", [])]


class TestExportRequiresEditor:
    def test_viewer_cannot_export_workspace(self, client, db):
        env = Env(db)
        status, _ = _export(client, env, env.viewer.username)
        assert status == 403, "普通成员不应能全量导出工作区"


class TestExportHonoursTablePermissions:
    def _setup(self, client, db):
        env = Env(db)
        _create_table_with_rows(client, env, name="开放表", values=["OPEN-1"])
        restricted = _create_table_with_rows(client, env, name="仅所有者表", values=["SECRET-1"])
        _set_permission(client, env, restricted, {"read_role": "owner"})
        return env, restricted

    def test_editor_export_excludes_restricted_table_data(self, client, db):
        env, _restricted = self._setup(client, db)
        status, body = _export(client, env, env.editor.username)
        assert status == 200, status

        names = _table_names(body)
        assert "开放表" in names, names
        assert "仅所有者表" not in names, f"受限表被导出：{names}"
        raw = str(body)
        assert "SECRET-1" not in raw, "受限表的数据行出现在导出内容里"
        assert "OPEN-1" in raw, "可读表的数据行应出现在导出里"

    def test_owner_export_includes_all_tables(self, client, db):
        env, _restricted = self._setup(client, db)
        status, body = _export(client, env, env.owner.username)
        assert status == 200, status
        names = _table_names(body)
        assert {"开放表", "仅所有者表"} <= set(names), names
        assert "SECRET-1" in str(body)

    def test_export_honours_row_filters(self, client, db):
        env = Env(db)
        tid = _create_table_with_rows(client, env, name="有行过滤表", values=["KEEP", "DROP"])
        _set_permission(
            client,
            env,
            tid,
            {"read_role": "viewer", "row_filters": [{"field_name": "名称", "op": "=", "value": "KEEP"}]},
        )

        status, body = _export(client, env, env.editor.username)
        assert status == 200, status
        raw = str(body)
        assert "KEEP" in raw
        assert "DROP" not in raw, "行级过滤未在导出中生效"
