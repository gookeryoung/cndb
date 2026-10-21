"""文档修改申请的可见性收口测试 —— 未发布内容不能通过"修改申请"旁路泄露.

**修复背景**：修改申请携带**待审正文全文**与 DIFF，但此前所有读写只校验"工作区成员"，
未按文档可见性过滤。后果（均为真实可利用的泄露）：
- `GET /document-change-requests?document_id=<他人草稿>` 能列出该草稿的修改申请；
- `GET /document-change-requests/{id}` 能读到他人草稿的**待审正文**；
- `POST /document-change-requests` 能对不可见文档发起申请并拿到 DIFF；
- 工作区 editor/owner 可对**看不见的草稿** merge/close/delete/update-base，
  其中 merge 还会把待审正文写成该草稿的新版本。

修法与文档接口一致：不可见 → **404**（不泄露存在性）；可见性判定复用
`services.visibility`（已发布全员可见、草稿仅创建者/所有者/协作者可见）。
本文件锁定修复后的行为，并防止"收得过紧"（已发布文档的申请必须对所有成员可见）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import Document
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
CRS = "/api/v1/workspaces/{ws}/document-change-requests"


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
        self.owner = _user(db, "crv_owner")
        self.ws = Workspace(name="CRVisWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        self.editor = _user(db, "crv_editor")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.editor.id, role=WorkspaceRole.EDITOR))
        self.viewer = _user(db, "crv_viewer")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()


def _create_doc(client: TestClient, env: Env, *, status: str, title: str = "修改申请可见性") -> dict:
    r = client.post(
        DOCS.format(ws=env.ws.id),
        json={"title": title, "content": "# v1\n", "status": status},
        headers=_login(client, env.owner.username),
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_cr(client: TestClient, env: Env, doc_id: int, *, username: str, content: str = "# 待审正文\n") -> dict:
    r = client.post(
        CRS.format(ws=env.ws.id),
        json={"document_id": doc_id, "content": content, "title": "草稿修改", "change_summary": "测试"},
        headers=_login(client, username),
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestDraftChangeRequestIsPrivate:
    def test_member_cannot_read_or_list_draft_change_request(self, client, db):
        env = Env(db)
        draft = _create_doc(client, env, status="draft")
        cr = _create_cr(client, env, draft["id"], username=env.owner.username)

        auth_viewer = _login(client, env.viewer.username)
        # 指定 document_id 列表 → 空（不泄露"存在这样一份草稿"）
        r = client.get(
            f"{CRS.format(ws=env.ws.id)}?document_id={draft['id']}&scope=all",
            headers=auth_viewer,
        )
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 0, r.text
        # 不带过滤的列表：不应包含该草稿的申请
        r = client.get(f"{CRS.format(ws=env.ws.id)}?scope=all", headers=auth_viewer)
        assert r.status_code == 200, r.text
        assert all(item["document_id"] != draft["id"] for item in r.json()["items"])
        # 按 id 直读（含待审正文）→ 404
        assert client.get(f"{CRS.format(ws=env.ws.id)}/{cr['id']}", headers=auth_viewer).status_code == 404

    def test_creator_still_reads_own_draft_change_request(self, client, db):
        env = Env(db)
        draft = _create_doc(client, env, status="draft")
        cr = _create_cr(client, env, draft["id"], username=env.owner.username, content="# 仅创建者可见\n")

        auth = _login(client, env.owner.username)
        r = client.get(f"{CRS.format(ws=env.ws.id)}/{cr['id']}", headers=auth)
        assert r.status_code == 200, r.text
        assert "仅创建者可见" in r.text or "仅创建者可见" in str(r.json())
        items = client.get(f"{CRS.format(ws=env.ws.id)}?scope=all", headers=auth).json()["items"]
        assert cr["id"] in [i["id"] for i in items]

    def test_cannot_create_change_request_on_invisible_draft(self, client, db):
        env = Env(db)
        draft = _create_doc(client, env, status="draft")
        r = client.post(
            CRS.format(ws=env.ws.id),
            json={"document_id": draft["id"], "content": "# 窥探\n"},
            headers=_login(client, env.viewer.username),
        )
        assert r.status_code == 404, r.text

    def test_workspace_editor_cannot_merge_or_close_draft_change_request(self, client, db):
        """editor 虽是 reviewer，但看不见该草稿 → 不能通过/关闭（merge 会写入草稿正文）."""
        env = Env(db)
        draft = _create_doc(client, env, status="draft")
        cr = _create_cr(client, env, draft["id"], username=env.owner.username)

        auth_editor = _login(client, env.editor.username)
        base = f"{CRS.format(ws=env.ws.id)}/{cr['id']}"
        assert client.post(f"{base}/merge", json={"review_comment": ""}, headers=auth_editor).status_code == 404
        assert client.post(f"{base}/close", json={"review_comment": ""}, headers=auth_editor).status_code == 404
        assert client.delete(base, headers=auth_editor).status_code == 404

        # merge 才是写入口，被 404 拦住 → 版本数不增长、正文保持原文
        from cndb.plugins.documents.models import DocumentVersion

        doc = db.get(Document, draft["id"])
        assert doc is not None
        versions = (
            db.query(DocumentVersion)
            .filter(DocumentVersion.document_id == draft["id"])
            .order_by(DocumentVersion.version_number.desc())
            .all()
        )
        assert len(versions) == 1  # 仅建文档时的那一版
        assert "v1" in (versions[0].content or "")


class TestPublishedChangeRequestStaysVisible:
    def test_published_document_change_request_visible_to_all_members(self, client, db):
        """不要收得过紧：已发布文档的修改申请对所有工作区成员可见（协作流程依赖它）."""
        env = Env(db)
        published = _create_doc(client, env, status="published", title="已发布文档")
        cr = _create_cr(client, env, published["id"], username=env.owner.username)

        url = f"{CRS.format(ws=env.ws.id)}/{cr['id']}"
        assert client.get(url, headers=_login(client, env.viewer.username)).status_code == 200
        assert client.get(url, headers=_login(client, env.editor.username)).status_code == 200

        listed = client.get(f"{CRS.format(ws=env.ws.id)}?scope=all", headers=_login(client, env.viewer.username)).json()
        assert cr["id"] in [i["id"] for i in listed["items"]]

    def test_editor_can_merge_published_change_request(self, client, db):
        env = Env(db)
        published = _create_doc(client, env, status="published", title="可合并文档")
        cr = _create_cr(client, env, published["id"], username=env.owner.username, content="# 新版本\n")

        r = client.post(
            f"{CRS.format(ws=env.ws.id)}/{cr['id']}/merge",
            json={"review_comment": "同意"},
            headers=_login(client, env.editor.username),
        )
        assert r.status_code == 200, r.text
        body = client.get(
            f"{DOCS.format(ws=env.ws.id)}/{published['id']}/content",
            headers=_login(client, env.viewer.username),
        )
        assert body.status_code == 200
        assert "新版本" in str(body.json().get("content", ""))
