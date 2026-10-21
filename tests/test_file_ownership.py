"""上传文件的归属校验：附件跟随宿主（表 / 行 / 文档）的权限.

**为什么需要**：附件此前只是"工作区内的 UUID 文件名"，下载仅校验工作区成员身份 ——
持有 file_key 即可读（capability URL）。键本身不可猜、无目录列举，所以不算严重，
但它无法表达"这个文件属于某张受限表 / 某份未发布文档 / 某个被行级过滤挡掉的行"：

- 受限表（``read_role`` 高于普通成员）里的附件，任何成员拿到键即可下载；
- 未发布文档里的图片同理；
- 被 ``row_filters`` 挡掉的行，其附件仍对有表读权限的人可下载。

现在上传时登记归属（``files_fileowner``），下载与删除按归属对象的权限校验；
历史无归属记录的文件保持原行为（工作区成员 + 不可猜键），不做回填。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.files.models import FileOwner
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

TABLES = "/api/v1/workspaces/{ws}/tables"
DOCS = "/api/v1/workspaces/{ws}/documents"
FILES = "/api/v1/workspaces/{ws}/files"


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
        self.owner = _user(db, "fo_owner")
        self.ws = Workspace(name="FileOwnerWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        self.viewer = _user(db, "fo_viewer")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()


def _upload(
    client: TestClient,
    env: Env,
    username: str,
    *,
    name: str = "a.txt",
    content: bytes = b"hello",
    table_id: int | None = None,
    row_id: int | None = None,
    document_id: int | None = None,
) -> tuple[int, dict]:
    data: dict[str, object] = {}
    if table_id is not None:
        data["table_id"] = table_id
    if row_id is not None:
        data["row_id"] = row_id
    if document_id is not None:
        data["document_id"] = document_id
    r = client.post(
        FILES.format(ws=env.ws.id),
        files={"file": (name, content, "text/plain")},
        data=data,
        headers=_login(client, username),
    )
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, body


def _download(client: TestClient, env: Env, username: str, file_key: str) -> int:
    return client.get(f"{FILES.format(ws=env.ws.id)}/{file_key}", headers=_login(client, username)).status_code


def _table(client: TestClient, env: Env, name: str) -> int:
    auth = _login(client, env.owner.username)
    r = client.post(TABLES.format(ws=env.ws.id), json={"name": name, "description": ""}, headers=auth)
    assert r.status_code == 201, r.text
    tid = int(r.json()["id"])
    client.post(
        f"{TABLES.format(ws=env.ws.id)}/{tid}/fields",
        json={"name": "status", "field_type": "text", "order": 0},
        headers=auth,
    )
    return tid


def _row(client: TestClient, env: Env, tid: int, value: str) -> int:
    r = client.post(
        f"{TABLES.format(ws=env.ws.id)}/{tid}/records",
        json={"values": {"status": value}},
        headers=_login(client, env.owner.username),
    )
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _set_permission(client: TestClient, env: Env, tid: int, payload: dict) -> None:
    r = client.put(
        f"{TABLES.format(ws=env.ws.id)}/{tid}/permissions",
        json=payload,
        headers=_login(client, env.owner.username),
    )
    assert r.status_code in (200, 201), r.text


def _doc(client: TestClient, env: Env, *, status: str) -> int:
    r = client.post(
        DOCS.format(ws=env.ws.id),
        json={"title": f"附件宿主-{status}", "content": "x", "status": status},
        headers=_login(client, env.owner.username),
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


class TestLegacyFilesKeepBehaviour:
    def test_unbound_file_is_workspace_level(self, client, db):
        """无归属记录（历史文件）：仍是"工作区成员 + 不可猜键"（兼容既有行为）."""
        env = Env(db)
        status, body = _upload(client, env, env.owner.username)
        assert status == 201, body
        key = body["file_key"]

        assert _download(client, env, env.viewer.username, key) == 200
        # 有 workspace 级归属记录，但没有绑定表/行/文档 → 仍按工作区成员校验
        row = db.query(FileOwner).filter(FileOwner.file_key == key).first()
        assert row is not None
        assert row.workspace_id == env.ws.id
        assert (row.table_id, row.row_id, row.document_id) == (None, None, None)
        assert row.uploaded_by_id == env.owner.id


class TestTableBoundFiles:
    def test_restricted_table_attachment_not_readable_by_members(self, client, db):
        env = Env(db)
        tid = _table(client, env, "仅所有者表")
        _set_permission(client, env, tid, {"read_role": "owner"})

        status, body = _upload(client, env, env.owner.username, table_id=tid)
        assert status == 201, body
        key = body["file_key"]

        assert _download(client, env, env.viewer.username, key) == 403
        assert _download(client, env, env.owner.username, key) == 200

    def test_readable_table_attachment_readable_by_members(self, client, db):
        env = Env(db)
        tid = _table(client, env, "普通表")
        _set_permission(client, env, tid, {"read_role": "viewer"})

        status, body = _upload(client, env, env.owner.username, table_id=tid)
        assert status == 201, body
        assert _download(client, env, env.viewer.username, body["file_key"]) == 200

    def test_row_filter_hides_attachment_of_out_of_scope_row(self, client, db):
        env = Env(db)
        tid = _table(client, env, "行过滤表")
        secret_row = _row(client, env, tid, "secret")
        public_row = _row(client, env, tid, "public")
        _set_permission(
            client,
            env,
            tid,
            {"read_role": "viewer", "row_filters": [{"field_name": "status", "op": "=", "value": "public"}]},
        )

        _s1, secret_file = _upload(client, env, env.owner.username, table_id=tid, row_id=secret_row)
        _s2, public_file = _upload(client, env, env.owner.username, table_id=tid, row_id=public_row)

        # 越界行的附件：普通成员 404（等价于"行不可见"），所有者豁免 → 200
        assert _download(client, env, env.viewer.username, secret_file["file_key"]) == 404
        assert _download(client, env, env.owner.username, secret_file["file_key"]) == 200
        # 命中行的附件正常可读
        assert _download(client, env, env.viewer.username, public_file["file_key"]) == 200

    def test_upload_requires_edit_permission_on_target_table(self, client, db):
        env = Env(db)
        tid = _table(client, env, "仅所有者表2")
        _set_permission(client, env, tid, {"read_role": "owner"})

        status, _body = _upload(client, env, env.viewer.username, table_id=tid)
        assert status in (403, 404), f"无写权限不应能绑定到该表：{status}"


class TestDocumentBoundFiles:
    def test_draft_attachment_hidden_from_members(self, client, db):
        env = Env(db)
        doc_id = _doc(client, env, status="draft")

        status, body = _upload(client, env, env.owner.username, document_id=doc_id, name="img.png")
        assert status == 201, body
        key = body["file_key"]

        assert _download(client, env, env.viewer.username, key) == 404
        assert _download(client, env, env.owner.username, key) == 200

    def test_cannot_attach_to_invisible_draft(self, client, db):
        env = Env(db)
        doc_id = _doc(client, env, status="draft")
        status, _body = _upload(client, env, env.viewer.username, document_id=doc_id)
        assert status == 404, f"不可见草稿不应能上传附件：{status}"

    def test_published_attachment_readable_by_members(self, client, db):
        env = Env(db)
        doc_id = _doc(client, env, status="published")
        status, body = _upload(client, env, env.owner.username, document_id=doc_id)
        assert status == 201, body
        assert _download(client, env, env.viewer.username, body["file_key"]) == 200


class TestDeleteFollowsOwnership:
    def test_member_cannot_delete_restricted_attachment(self, client, db):
        env = Env(db)
        tid = _table(client, env, "仅所有者表3")
        _set_permission(client, env, tid, {"read_role": "owner"})
        _s, body = _upload(client, env, env.owner.username, table_id=tid)
        key = body["file_key"]

        r = client.delete(f"{FILES.format(ws=env.ws.id)}/{key}", headers=_login(client, env.viewer.username))
        assert r.status_code == 403, r.text

        # 所有者可删；删除同时清理归属记录
        r2 = client.delete(f"{FILES.format(ws=env.ws.id)}/{key}", headers=_login(client, env.owner.username))
        assert r2.status_code == 204, r2.text
        assert db.query(FileOwner).filter(FileOwner.file_key == key).first() is None
