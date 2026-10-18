"""文档个人草稿与显式提交（保存与提交解耦）测试.

覆盖：
- 保存草稿不生成版本、不产生修改申请；
- 草稿与最新正文一致时视为「无修改」，服务端清理草稿；
- 丢弃草稿幂等；
- 未修改内容提交被拒（409，code=no_changes），旧修改申请入口同样拦截；
- 显式提交：直编落库为新版本 / 无直编资格转修改申请（202）；
- 基准漂移时按段落三方合并，同段改动冲突；
- 草稿仅本人可见；旧「保存即提交」接口提交后清理草稿。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import DocumentDraft
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
DCR = "/api/v1/workspaces/{ws}/document-change-requests"

BASE_CONTENT = "标题\n\n第一段\n\n第二段\n"


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


def _add_member(db: Session, ws: Workspace, username: str, role: WorkspaceRole) -> User:
    u = _make_user(db, username)
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=role))
    db.commit()
    return u


@pytest.fixture
def owner(db) -> User:
    return _make_user(db, "draft_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    w = Workspace(name="DraftWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def editor(db, ws) -> User:
    return _add_member(db, ws, "draft_editor", WorkspaceRole.EDITOR)


@pytest.fixture
def viewer(db, ws) -> User:
    return _add_member(db, ws, "draft_viewer", WorkspaceRole.VIEWER)


def _create_doc(client: TestClient, ws_id: int, auth: dict[str, str], **overrides) -> dict:
    # 已发布：他人（editor/viewer）才能看到该文档并保存自己的草稿
    payload = {"title": "文档", "content": BASE_CONTENT, "status": "published", **overrides}
    r = client.post(DOCS.format(ws=ws_id), json=payload, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def _get_content(client: TestClient, ws_id: int, doc_id: int, auth: dict[str, str]) -> dict:
    r = client.get(DOCS.format(ws=ws_id) + f"/{doc_id}/content", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def _save_draft(client: TestClient, ws_id: int, doc_id: int, auth: dict[str, str], content: str, **extra):
    return client.put(DOCS.format(ws=ws_id) + f"/{doc_id}/draft", json={"content": content, **extra}, headers=auth)


def _submit(client: TestClient, ws_id: int, doc_id: int, auth: dict[str, str], **payload):
    return client.post(DOCS.format(ws=ws_id) + f"/{doc_id}/submit", json=payload, headers=auth)


def _versions_total(client: TestClient, ws_id: int, doc_id: int, auth: dict[str, str]) -> int:
    r = client.get(DOCS.format(ws=ws_id) + f"/{doc_id}/versions", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["total"]


# ── 保存草稿 ──────────────────────────────────────────


class TestSaveDraft:
    def test_save_draft_does_not_create_version_or_request(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws.id, auth)

        r = _save_draft(client, ws.id, doc["id"], auth, "标题\n\n改过的第一段\n\n第二段\n")

        assert r.status_code == 200, r.text
        draft = r.json()["draft"]
        assert draft["content"] == "标题\n\n改过的第一段\n\n第二段\n"
        assert draft["base_version_number"] == 1
        assert draft["stale"] is False
        assert draft["current_version_number"] == 1
        # 正式内容不受影响：仍是 v1，也没有修改申请
        assert _versions_total(client, ws.id, doc["id"], auth) == 1
        assert client.get(DCR.format(ws=ws.id), headers=auth).json()["total"] == 0
        assert _get_content(client, ws.id, doc["id"], auth)["content"] == BASE_CONTENT

    def test_content_endpoint_exposes_draft_and_write_mode(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws.id, auth)
        _save_draft(client, ws.id, doc["id"], auth, "标题\n\n草稿内容\n")

        data = _get_content(client, ws.id, doc["id"], auth)

        assert data["write_mode"] == "direct"
        assert data["draft"]["content"] == "标题\n\n草稿内容\n"
        # 正文仍是最新版本，草稿独立存在
        assert data["content"] == BASE_CONTENT
        assert data["version_number"] == 1

    def test_save_unchanged_content_clears_draft(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws.id, auth)
        _save_draft(client, ws.id, doc["id"], auth, "标题\n\n草稿内容\n")

        r = _save_draft(client, ws.id, doc["id"], auth, BASE_CONTENT)

        assert r.status_code == 200, r.text
        assert r.json()["draft"] is None
        assert _get_content(client, ws.id, doc["id"], auth)["draft"] is None

    def test_discard_draft_is_idempotent(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws.id, auth)
        _save_draft(client, ws.id, doc["id"], auth, "标题\n\n草稿内容\n")

        r = client.delete(DOCS.format(ws=ws.id) + f"/{doc['id']}/draft", headers=auth)
        assert r.status_code == 204

        r = client.delete(DOCS.format(ws=ws.id) + f"/{doc['id']}/draft", headers=auth)
        assert r.status_code == 204
        assert _get_content(client, ws.id, doc["id"], auth)["draft"] is None

    def test_base_version_ahead_is_rejected(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws.id, auth)

        r = _save_draft(client, ws.id, doc["id"], auth, "标题\n\n草稿\n", base_version_number=9)

        assert r.status_code == 400, r.text
        assert "基准版本" in r.json()["detail"]

    def test_folder_has_no_draft(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        folder = _create_doc(client, ws.id, auth, title="目录", content="", is_folder=True)

        r = _save_draft(client, ws.id, folder["id"], auth, "随便写")

        assert r.status_code == 409, r.text

    def test_draft_is_private(self, client, ws, owner, viewer, db):
        auth_owner = _login(client, owner.username)
        auth_viewer = _login(client, viewer.username)
        doc = _create_doc(client, ws.id, auth_owner)

        _save_draft(client, ws.id, doc["id"], auth_viewer, "标题\n\n查看者的草稿\n")

        # 草稿落库了，但只有本人读得到
        assert db.execute(select(DocumentDraft).where(DocumentDraft.document_id == doc["id"])).scalar_one()
        assert _get_content(client, ws.id, doc["id"], auth_owner)["draft"] is None
        r = client.get(DOCS.format(ws=ws.id) + f"/{doc['id']}/draft", headers=auth_owner)
        assert r.status_code == 200
        assert r.json()["draft"] is None


# ── 未修改不可提交 ────────────────────────────────────


class TestNoChangesGuard:
    def test_submit_without_draft_and_content_is_rejected(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws.id, auth)

        r = _submit(client, ws.id, doc["id"], auth)

        assert r.status_code == 409, r.text
        assert r.json()["code"] == "no_changes"

    def test_submit_unchanged_content_is_rejected(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws.id, auth)

        r = _submit(client, ws.id, doc["id"], auth, content=BASE_CONTENT)

        assert r.status_code == 409, r.text
        assert r.json()["code"] == "no_changes"
        assert _versions_total(client, ws.id, doc["id"], auth) == 1

    def test_change_request_endpoint_rejects_unchanged_content(self, client, ws, owner, viewer, db):
        auth_owner = _login(client, owner.username)
        auth_viewer = _login(client, viewer.username)
        doc = _create_doc(client, ws.id, auth_owner)

        r = client.post(
            DCR.format(ws=ws.id),
            json={"document_id": doc["id"], "content": BASE_CONTENT},
            headers=auth_viewer,
        )

        assert r.status_code == 409, r.text
        assert r.json()["code"] == "no_changes"
        assert client.get(DCR.format(ws=ws.id), headers=auth_owner).json()["total"] == 0

    def test_submit_clears_draft_when_unchanged(self, client, ws, owner, editor, db):
        """草稿在文档被他人推进后恰好与最新正文一致：提交应清草稿并 409."""
        auth_owner = _login(client, owner.username)
        auth_editor = _login(client, editor.username)
        doc = _create_doc(client, ws.id, auth_owner)
        _save_draft(client, ws.id, doc["id"], auth_editor, "标题\n\n稍后与正文一致\n")

        # 文档被 owner 推进到与 editor 草稿相同（只清 owner 自己的草稿）
        r = client.put(
            DOCS.format(ws=ws.id) + f"/{doc['id']}/content",
            json={"content": "标题\n\n稍后与正文一致\n"},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text

        r = _submit(client, ws.id, doc["id"], auth_editor)

        assert r.status_code == 409, r.text
        assert r.json()["code"] == "no_changes"
        assert _get_content(client, ws.id, doc["id"], auth_editor)["draft"] is None


# ── 显式提交 ──────────────────────────────────────────


class TestSubmit:
    def test_submit_saved_draft_creates_version(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws.id, auth)
        _save_draft(client, ws.id, doc["id"], auth, "标题\n\n提交后的正文\n")

        r = _submit(client, ws.id, doc["id"], auth, change_summary="改第一段")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mode"] == "direct"
        assert body["version_number"] == 2
        assert body["content"] == "标题\n\n提交后的正文\n"
        # 提交后草稿被消费
        data = _get_content(client, ws.id, doc["id"], auth)
        assert data["content"] == "标题\n\n提交后的正文\n"
        assert data["draft"] is None
        assert _versions_total(client, ws.id, doc["id"], auth) == 2

    def test_submit_with_explicit_content_without_saved_draft(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws.id, auth)

        r = _submit(client, ws.id, doc["id"], auth, content="标题\n\n直接提交\n")

        assert r.status_code == 200, r.text
        assert r.json()["version_number"] == 2

    def test_viewer_submit_becomes_change_request(self, client, ws, owner, viewer, db):
        auth_owner = _login(client, owner.username)
        auth_viewer = _login(client, viewer.username)
        doc = _create_doc(client, ws.id, auth_owner)

        r = _save_draft(client, ws.id, doc["id"], auth_viewer, "标题\n\n查看者的修改\n")
        assert r.status_code == 200, r.text
        assert _get_content(client, ws.id, doc["id"], auth_viewer)["write_mode"] == "change_request"

        r = _submit(client, ws.id, doc["id"], auth_viewer, change_summary="建议修改")

        assert r.status_code == 202, r.text
        body = r.json()
        assert body["mode"] == "change_request"
        assert body["change_request"]["status"] == "open"
        # 正文未落库，草稿已清，申请可见
        assert _get_content(client, ws.id, doc["id"], auth_viewer)["content"] == BASE_CONTENT
        assert _get_content(client, ws.id, doc["id"], auth_viewer)["draft"] is None
        requests = client.get(DCR.format(ws=ws.id), headers=auth_owner).json()
        assert requests["total"] == 1
        assert requests["items"][0]["document_id"] == doc["id"]

    def test_stale_draft_merges_other_paragraphs(self, client, ws, owner, editor, db):
        auth_owner = _login(client, owner.username)
        auth_editor = _login(client, editor.username)
        doc = _create_doc(client, ws.id, auth_owner)

        # editor 基于 v1 保存草稿（改第二段）
        _save_draft(client, ws.id, doc["id"], auth_editor, "标题\n\n第一段改\n\n第二段\n")
        # owner 同时推进到 v2（改第三段）
        r = client.put(
            DOCS.format(ws=ws.id) + f"/{doc['id']}/content",
            json={"content": "标题\n\n第一段\n\n第二段改\n"},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        assert _get_content(client, ws.id, doc["id"], auth_editor)["draft"]["stale"] is True

        r = _submit(client, ws.id, doc["id"], auth_editor)

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["version_number"] == 3
        assert "第一段改" in body["content"]
        assert "第二段改" in body["content"]

    def test_stale_draft_same_paragraph_conflicts(self, client, ws, owner, editor, db):
        auth_owner = _login(client, owner.username)
        auth_editor = _login(client, editor.username)
        doc = _create_doc(client, ws.id, auth_owner)

        _save_draft(client, ws.id, doc["id"], auth_editor, "标题\n\n第一段（编辑者）\n\n第二段\n")
        r = client.put(
            DOCS.format(ws=ws.id) + f"/{doc['id']}/content",
            json={"content": "标题\n\n第一段（所有者）\n\n第二段\n"},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text

        r = _submit(client, ws.id, doc["id"], auth_editor)

        assert r.status_code == 409, r.text
        assert r.json()["code"] == "paragraph_conflict"
        # 冲突不做任何写入，草稿保留
        assert _versions_total(client, ws.id, doc["id"], auth_owner) == 2
        assert _get_content(client, ws.id, doc["id"], auth_editor)["draft"] is not None


# ── 兼容旧路径 ────────────────────────────────────────


class TestLegacySaveClearsDraft:
    def test_legacy_content_put_consumes_draft(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws.id, auth)
        _save_draft(client, ws.id, doc["id"], auth, "标题\n\n草稿内容\n")

        r = client.put(
            DOCS.format(ws=ws.id) + f"/{doc['id']}/content",
            json={"content": "标题\n\n旧接口保存\n"},
            headers=auth,
        )

        assert r.status_code == 200, r.text
        assert _get_content(client, ws.id, doc["id"], auth)["draft"] is None
