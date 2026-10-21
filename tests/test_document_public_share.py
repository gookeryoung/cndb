"""游客级只读分享（ADR 0017）判定、响应白名单与匿名图片端点.

覆盖：
- ``resolve_public_share`` 单一判定：未知 / 撤销 / 过期 / 草稿 / 归档 / 软删一律 404；
- 公开响应白名单（不含工作区 / 目录 / 成员 / 标签等内部字段）；
- 密码分享语义、访问计数原子递增、``no-store``；
- 匿名只读（无写方法）；
- 免登录图片端点：按归属收口、仅栅格图片、路径校验；
- 表 / 视图匿名分享仍 404（ADR 0003 D5 不复活）。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.core.errors import BadRequestError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import Document, DocumentShare
from cndb.plugins.files import services as files_service
from cndb.plugins.files.models import FileOwner
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
SHARE_API = "/api/v1/documents/share"


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


@pytest.fixture
def owner(db) -> User:
    return _make_user(db, "guest_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    w = Workspace(name="GuestWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def auth(client, owner) -> dict[str, str]:
    return _login(client, owner.username)


def _create_doc(
    client: TestClient,
    ws: Workspace,
    auth: dict[str, str],
    *,
    title: str = "分享文档",
    status: str = "published",
    content: str = "# 正文\n\nshare-body\n",
    is_folder: bool = False,
) -> dict:
    r = client.post(
        DOCS.format(ws=ws.id),
        json={"title": title, "content": content, "status": status, "is_folder": is_folder},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _share_token(client: TestClient, ws: Workspace, auth: dict[str, str], doc_id: int) -> str:
    r = client.post(f"{DOCS.format(ws=ws.id)}/{doc_id}/share", json={"permission": "viewer"}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _add_share(db: Session, doc_id: int, token: str, **kwargs) -> DocumentShare:
    share = DocumentShare(document_id=doc_id, token=token, is_active=True, **kwargs)
    db.add(share)
    db.commit()
    return share


def _upload(client: TestClient, ws: Workspace, auth: dict[str, str], *, document_id: int | None, name: str) -> str:
    data = {"document_id": str(document_id)} if document_id is not None else {}
    r = client.post(
        f"/api/v1/workspaces/{ws.id}/files",
        files={"file": (name, b"\x89PNG\r\n\x1a\nfake", "image/png")},
        data=data,
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()["file_key"]


def _count(db: Session, share_id: int) -> int:
    return db.execute(select(DocumentShare.view_count).where(DocumentShare.id == share_id)).scalar_one()


class TestResolvePublicShare:
    def test_valid_published_document(self, client, db, ws, auth):
        doc = _create_doc(client, ws, auth)
        token = _share_token(client, ws, auth, doc["id"])

        r = client.get(f"{SHARE_API}/{token}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {"title", "content", "updated_at"}
        assert body["title"] == "分享文档"
        assert "share-body" in body["content"]
        assert r.headers["cache-control"] == "no-store"

    @pytest.mark.parametrize("status", ["draft", "archived"])
    def test_unpublished_document_404(self, client, db, ws, auth, status):
        doc = _create_doc(client, ws, auth, status=status)
        _add_share(db, doc["id"], f"token-{status}")
        assert client.get(f"{SHARE_API}/token-{status}").status_code == 404

    def test_unknown_token_404(self, client):
        r = client.get(f"{SHARE_API}/nope")
        assert r.status_code == 404
        assert r.json()["detail"] == "分享链接不存在或已失效"

    def test_revoked_share_404(self, client, db, ws, auth):
        doc = _create_doc(client, ws, auth)
        share = client.post(f"{DOCS.format(ws=ws.id)}/{doc['id']}/share", json={}, headers=auth).json()
        assert client.delete(f"{DOCS.format(ws=ws.id)}/{doc['id']}/share/{share['id']}", headers=auth).status_code == 200
        assert client.get(f"{SHARE_API}/{share['token']}").status_code == 404

    def test_expired_share_404(self, client, db, ws, auth):
        doc = _create_doc(client, ws, auth)
        _add_share(db, doc["id"], "expired", expires_at=dt.datetime(2000, 1, 1))
        assert client.get(f"{SHARE_API}/expired").status_code == 404

    def test_soft_deleted_document_404(self, client, db, ws, auth):
        doc = _create_doc(client, ws, auth)
        token = _share_token(client, ws, auth, doc["id"])
        row = db.get(Document, doc["id"])
        row.is_deleted = True
        db.commit()
        assert client.get(f"{SHARE_API}/{token}").status_code == 404

    def test_unpublish_after_share_404(self, client, db, ws, auth):
        doc = _create_doc(client, ws, auth)
        token = _share_token(client, ws, auth, doc["id"])
        r = client.patch(
            f"{DOCS.format(ws=ws.id)}/{doc['id']}",
            json={"status": "draft"},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert client.get(f"{SHARE_API}/{token}").status_code == 404

    def test_folder_share_has_no_content(self, client, db, ws, auth):
        folder = _create_doc(client, ws, auth, title="分享文件夹", content="", is_folder=True)
        _add_share(db, folder["id"], "folder-token")
        r = client.get(f"{SHARE_API}/folder-token")
        assert r.status_code == 200, r.text
        assert set(r.json()) == {"title", "updated_at"}

    def test_folder_cannot_be_created_for_draft(self, client, ws, auth):
        draft = _create_doc(client, ws, auth, status="draft")
        r = client.post(f"{DOCS.format(ws=ws.id)}/{draft['id']}/share", json={}, headers=auth)
        assert r.status_code == 409


class TestPasswordShare:
    def test_password_flow_and_masked_hash(self, client, db, ws, auth):
        doc = _create_doc(client, ws, auth, content="secret-password-body")
        r = client.post(
            f"{DOCS.format(ws=ws.id)}/{doc['id']}/share",
            json={"password": "abc123"},
            headers=auth,
        )
        assert r.status_code == 201, r.text
        share = r.json()
        assert "password_hash" not in share and share["has_password"] is True
        token = share["token"]

        r = client.get(f"{SHARE_API}/{token}")
        assert r.status_code == 403
        assert r.json()["code"] == "share_password_required"

        assert client.post(f"{SHARE_API}/{token}", json={"password": "wrong"}).status_code == 403
        r = client.post(f"{SHARE_API}/{token}", json={"password": "abc123"})
        assert r.status_code == 200, r.text
        assert "secret-password-body" in r.json()["content"]
        assert "password_hash" not in r.text and "$2b$" not in r.text

    def test_password_on_open_share_400(self, client, ws, auth):
        doc = _create_doc(client, ws, auth)
        token = _share_token(client, ws, auth, doc["id"])
        assert client.post(f"{SHARE_API}/{token}", json={"password": "x"}).status_code == 400

    def test_password_share_of_unpublished_doc_404(self, client, db, ws, auth):
        doc = _create_doc(client, ws, auth, status="draft")
        pwd_hash = bcrypt.hashpw(b"secret", bcrypt.gensalt(4)).decode()
        _add_share(db, doc["id"], "draft-pwd", password_hash=pwd_hash)
        assert client.post(f"{SHARE_API}/draft-pwd", json={"password": "secret"}).status_code == 404


class TestViewCount:
    def test_content_access_counts_once_per_request(self, client, db, ws, auth):
        doc = _create_doc(client, ws, auth)
        token = _share_token(client, ws, auth, doc["id"])
        share = db.execute(select(DocumentShare).where(DocumentShare.token == token)).scalar_one()

        client.get(f"{SHARE_API}/{token}/meta")
        assert _count(db, share.id) == 0

        client.get(f"{SHARE_API}/{token}")
        client.get(f"{SHARE_API}/{token}")
        assert _count(db, share.id) == 2

    def test_failed_password_does_not_count(self, client, db, ws, auth):
        doc = _create_doc(client, ws, auth)
        r = client.post(
            f"{DOCS.format(ws=ws.id)}/{doc['id']}/share",
            json={"password": "abc123"},
            headers=auth,
        )
        token = r.json()["token"]
        share = db.execute(select(DocumentShare).where(DocumentShare.token == token)).scalar_one()

        client.post(f"{SHARE_API}/{token}", json={"password": "wrong"})
        assert _count(db, share.id) == 0
        client.post(f"{SHARE_API}/{token}", json={"password": "abc123"})
        assert _count(db, share.id) == 1


class TestAnonymousReadOnly:
    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_write_methods_not_allowed(self, client, ws, auth, method):
        doc = _create_doc(client, ws, auth)
        token = _share_token(client, ws, auth, doc["id"])
        kwargs = {} if method == "delete" else {"json": {}}
        r = getattr(client, method)(f"{SHARE_API}/{token}", **kwargs)
        assert r.status_code in (404, 405)


class TestPublicFile:
    def test_owner_document_image(self, client, ws, auth):
        doc = _create_doc(client, ws, auth)
        token = _share_token(client, ws, auth, doc["id"])
        key = _upload(client, ws, auth, document_id=doc["id"], name="pic.png")

        r = client.get(f"{SHARE_API}/{token}/files/{key}")
        assert r.status_code == 200, r.text
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["cache-control"] == "no-store"

    def test_other_document_image_404(self, client, ws, auth):
        doc = _create_doc(client, ws, auth)
        other = _create_doc(client, ws, auth, title="另一篇")
        token = _share_token(client, ws, auth, doc["id"])
        key = _upload(client, ws, auth, document_id=other["id"], name="other.png")

        assert client.get(f"{SHARE_API}/{token}/files/{key}").status_code == 404

    def test_table_attachment_404(self, client, db, ws, auth):
        doc = _create_doc(client, ws, auth)
        token = _share_token(client, ws, auth, doc["id"])
        key = _upload(client, ws, auth, document_id=None, name="plain.png")
        # 归属工作区但不属于该文档
        assert client.get(f"{SHARE_API}/{token}/files/{key}").status_code == 404

    def test_unowned_file_404(self, client, ws, auth):
        doc = _create_doc(client, ws, auth)
        token = _share_token(client, ws, auth, doc["id"])
        key = "deadbeefdeadbeef.png"
        (Path(settings.UPLOAD_DIR) / str(ws.id)).mkdir(parents=True, exist_ok=True)
        (Path(settings.UPLOAD_DIR) / str(ws.id) / key).write_bytes(b"x")

        assert client.get(f"{SHARE_API}/{token}/files/{key}").status_code == 404

    def test_scriptable_extension_404(self, client, ws, auth, db):
        doc = _create_doc(client, ws, auth)
        token = _share_token(client, ws, auth, doc["id"])
        key = _upload(client, ws, auth, document_id=doc["id"], name="x.svg")
        assert client.get(f"{SHARE_API}/{token}/files/{key}").status_code == 404

    def test_missing_physical_file_404(self, client, db, ws, auth):
        doc = _create_doc(client, ws, auth)
        token = _share_token(client, ws, auth, doc["id"])
        db.add(FileOwner(file_key="missing.png", workspace_id=ws.id, document_id=doc["id"]))
        db.commit()
        assert client.get(f"{SHARE_API}/{token}/files/missing.png").status_code == 404

    def test_revoked_share_blocks_image(self, client, db, ws, auth):
        doc = _create_doc(client, ws, auth)
        share = client.post(f"{DOCS.format(ws=ws.id)}/{doc['id']}/share", json={}, headers=auth).json()
        key = _upload(client, ws, auth, document_id=doc["id"], name="pic.png")
        client.delete(f"{DOCS.format(ws=ws.id)}/{doc['id']}/share/{share['id']}", headers=auth)
        assert client.get(f"{SHARE_API}/{share['token']}/files/{key}").status_code == 404


class TestResolveWorkspaceFile:
    @pytest.mark.parametrize("key", ["../x.png", "a/b.png", "a\\b.png", ".hidden", "", "x" * 300])
    def test_illegal_key_rejected(self, key):
        with pytest.raises(BadRequestError):
            files_service.resolve_workspace_file(1, key)

    def test_legal_key_inside_workspace(self):
        p = files_service.resolve_workspace_file(7, "abc123.png")
        assert p.parent.name == "7"


def test_table_public_share_still_gone(client):
    """ADR 0003 D5：表 / 视图匿名分享不随文档游客能力复活."""
    assert client.get("/api/v1/public/share/any-slug").status_code == 404
