"""文档修改申请（双轨制写入）测试.

覆盖：保存路径分派（owner/editor 直编、viewer 与关闭直编的 editor 转申请、非成员 403）、
申请列表与详情（含内容 DIFF）、merge 生效生成新版本、基准漂移与刷新基准、
驳回/关闭、草稿删除、并发申请置 stale、回收站文档拒绝合并。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
DCR = "/api/v1/workspaces/{ws}/document-change-requests"

BASE_CONTENT = "# 标题\n\n原文\n"


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
    return _make_user(db, "dcr_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    w = Workspace(name="DcrWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def editor(db, ws) -> User:
    return _add_member(db, ws, "dcr_editor", WorkspaceRole.EDITOR)


@pytest.fixture
def viewer(db, ws) -> User:
    return _add_member(db, ws, "dcr_viewer", WorkspaceRole.VIEWER)


@pytest.fixture
def outsider(db) -> User:
    return _make_user(db, "dcr_outsider")


def _create_doc(
    client: TestClient, ws_id: int, owner_auth: dict[str, str], *, title="文档", content=BASE_CONTENT
) -> dict:
    r = client.post(DOCS.format(ws=ws_id), json={"title": title, "content": content}, headers=owner_auth)
    assert r.status_code == 201, r.text
    return r.json()


def _save(client: TestClient, ws_id: int, doc_id: int, auth: dict[str, str], content: str, **extra):
    return client.put(DOCS.format(ws=ws_id) + f"/{doc_id}/content", json={"content": content, **extra}, headers=auth)


def _get_content(client: TestClient, ws_id: int, doc_id: int, auth: dict[str, str]) -> dict:
    r = client.get(DOCS.format(ws=ws_id) + f"/{doc_id}/content", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


# ── 保存路径分派 ──────────────────────────────────────


class TestSaveDispatch:
    def test_owner_saves_directly(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws.id, auth)

        r = _save(client, ws.id, doc["id"], auth, "# 标题\n\n已直编\n")

        assert r.status_code == 200, r.text
        assert r.json()["version_number"] == 2
        assert _get_content(client, ws.id, doc["id"], auth)["content"] == "# 标题\n\n已直编\n"
        # 直编不产生申请
        assert client.get(DCR.format(ws=ws.id), headers=auth).json()["total"] == 0

    def test_editor_saves_directly_when_allow_edit(self, client, ws, owner, editor, db):
        auth_owner = _login(client, owner.username)
        auth_editor = _login(client, editor.username)
        doc = _create_doc(client, ws.id, auth_owner)

        r = _save(client, ws.id, doc["id"], auth_editor, "# 标题\n\n编辑者直编\n")

        assert r.status_code == 200, r.text
        assert r.json()["version_number"] == 2

    def test_editor_turns_into_request_when_allow_edit_off(self, client, ws, owner, editor, db):
        ws.allow_edit = False
        db.commit()
        auth_owner = _login(client, owner.username)
        auth_editor = _login(client, editor.username)
        doc = _create_doc(client, ws.id, auth_owner)

        r = _save(client, ws.id, doc["id"], auth_editor, "# 标题\n\n关闭直编后的改动\n")

        assert r.status_code == 202, r.text
        assert r.json()["change_request"]["status"] == "open"
        # 正文未落库，仍是 v1
        assert _get_content(client, ws.id, doc["id"], auth_editor)["version_number"] == 1

    def test_viewer_save_creates_request(self, client, ws, owner, viewer, db):
        auth_owner = _login(client, owner.username)
        auth_viewer = _login(client, viewer.username)
        doc = _create_doc(client, ws.id, auth_owner)

        r = _save(client, ws.id, doc["id"], auth_viewer, "# 标题\n\n查看者的改动\n", base_version_number=1)

        assert r.status_code == 202, r.text
        body = r.json()
        assert body["message"].startswith("已提交修改申请 #")
        cr = body["change_request"]
        assert cr["status"] == "open"
        assert cr["document_id"] == doc["id"]
        assert cr["base_version_number"] == 1
        assert cr["current_version_number"] == 1
        assert cr["submitted_by_id"] == viewer.id
        # 待审正文不写入版本表
        current = _get_content(client, ws.id, doc["id"], auth_owner)
        assert current["version_number"] == 1
        assert current["content"] == BASE_CONTENT

    def test_outsider_save_denied(self, client, ws, owner, outsider, db):
        auth_owner = _login(client, owner.username)
        auth_outsider = _login(client, outsider.username)
        doc = _create_doc(client, ws.id, auth_owner)

        r = _save(client, ws.id, doc["id"], auth_outsider, "x")

        assert r.status_code == 403

    def test_folder_save_rejected(self, client, ws, owner, viewer, db):
        auth_owner = _login(client, owner.username)
        auth_viewer = _login(client, viewer.username)
        r = client.post(
            DOCS.format(ws=ws.id),
            json={"title": "目录", "content": "", "is_folder": True},
            headers=auth_owner,
        )
        folder = r.json()

        assert _save(client, ws.id, folder["id"], auth_owner, "x").status_code == 409
        assert _save(client, ws.id, folder["id"], auth_viewer, "x").status_code == 409


# ── 列表与详情 ────────────────────────────────────────


class TestListAndDetail:
    def _seed_request(self, client, ws, owner, viewer) -> tuple[dict, dict]:
        auth_owner = _login(client, owner.username)
        auth_viewer = _login(client, viewer.username)
        doc = _create_doc(client, ws.id, auth_owner)
        r = _save(
            client,
            ws.id,
            doc["id"],
            auth_viewer,
            "# 标题\n\n改后的原文\n新增行\n",
            base_version_number=1,
        )
        return doc, r.json()["change_request"]

    def test_list_filters(self, client, ws, owner, viewer, db):
        doc, cr = self._seed_request(client, ws, owner, viewer)
        auth_owner = _login(client, owner.username)
        auth_viewer = _login(client, viewer.username)

        open_list = client.get(DCR.format(ws=ws.id), headers=auth_owner).json()
        assert open_list["total"] == 1
        assert open_list["items"][0]["id"] == cr["id"]

        by_doc = client.get(DCR.format(ws=ws.id), params={"document_id": doc["id"]}, headers=auth_owner).json()
        assert by_doc["total"] == 1
        by_other_doc = client.get(DCR.format(ws=ws.id), params={"document_id": 999999}, headers=auth_owner).json()
        assert by_other_doc["total"] == 0

        mine = client.get(DCR.format(ws=ws.id), params={"scope": "mine"}, headers=auth_viewer).json()
        assert mine["total"] == 1
        assert mine["items"][0]["document_title"] == "文档"

        # 非法 scope → 400
        assert client.get(DCR.format(ws=ws.id), params={"scope": "bogus"}, headers=auth_owner).status_code == 400

    def test_detail_contains_diff_and_proposed_content(self, client, ws, owner, viewer, db):
        _doc, cr = self._seed_request(client, ws, owner, viewer)
        auth_owner = _login(client, owner.username)

        r = client.get(DCR.format(ws=ws.id) + f"/{cr['id']}", headers=auth_owner)

        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["proposed_content"] == "# 标题\n\n改后的原文\n新增行\n"
        assert detail["diff"]["added"] == 2
        assert detail["diff"]["removed"] == 1
        assert "-原文" in detail["diff"]["diff"]
        assert "+改后的原文" in detail["diff"]["diff"]

    def test_detail_not_found_and_outsider_denied(self, client, ws, owner, viewer, outsider, db):
        _, cr = self._seed_request(client, ws, owner, viewer)
        auth_owner = _login(client, owner.username)
        auth_outsider = _login(client, outsider.username)

        assert client.get(DCR.format(ws=ws.id) + "/999999", headers=auth_owner).status_code == 404
        assert client.get(DCR.format(ws=ws.id) + f"/{cr['id']}", headers=auth_outsider).status_code == 403
        assert client.get(DCR.format(ws=ws.id), headers=auth_outsider).status_code == 403

    def test_manual_create_endpoint(self, client, ws, owner, viewer, db):
        auth_owner = _login(client, owner.username)
        auth_viewer = _login(client, viewer.username)
        doc = _create_doc(client, ws.id, auth_owner)

        r = client.post(
            DCR.format(ws=ws.id),
            json={
                "document_id": doc["id"],
                "content": "# 标题\n\n手动发起\n",
                "title": "补充说明章节",
                "description": "补充第三节",
                "base_version_number": 1,
            },
            headers=auth_viewer,
        )

        assert r.status_code == 201, r.text
        body = r.json()
        assert body["title"] == "补充说明章节"
        assert body["description"] == "补充第三节"
        assert body["diff"]["added"] == 1


# ── 合并（通过并生效） ────────────────────────────────


class TestMerge:
    def _seed_request(self, client, ws, owner, viewer):
        auth_owner = _login(client, owner.username)
        auth_viewer = _login(client, viewer.username)
        doc = _create_doc(client, ws.id, auth_owner)
        r = _save(client, ws.id, doc["id"], auth_viewer, "# 标题\n\n生效后的正文\n", base_version_number=1)
        return doc, r.json()["change_request"]

    def test_owner_merges_request_into_new_version(self, client, ws, owner, viewer, db):
        doc, cr = self._seed_request(client, ws, owner, viewer)
        auth_owner = _login(client, owner.username)

        r = client.post(
            DCR.format(ws=ws.id) + f"/{cr['id']}/merge",
            json={"review_comment": "内容无误"},
            headers=auth_owner,
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["version_number"] == 2
        assert body["request"]["status"] == "merged"
        assert body["request"]["review_comment"] == "内容无误"
        assert body["request"]["reviewed_by_id"] == owner.id

        current = _get_content(client, ws.id, doc["id"], auth_owner)
        assert current["version_number"] == 2
        assert current["content"] == "# 标题\n\n生效后的正文\n"

    def test_merge_requires_reviewer_role(self, client, ws, owner, viewer, db):
        _, cr = self._seed_request(client, ws, owner, viewer)
        auth_viewer = _login(client, viewer.username)

        r = client.post(DCR.format(ws=ws.id) + f"/{cr['id']}/merge", headers=auth_viewer)

        assert r.status_code == 403

    def test_merge_twice_conflicts(self, client, ws, owner, viewer, db):
        _, cr = self._seed_request(client, ws, owner, viewer)
        auth_owner = _login(client, owner.username)
        url = DCR.format(ws=ws.id) + f"/{cr['id']}/merge"

        assert client.post(url, headers=auth_owner).status_code == 200
        assert client.post(url, headers=auth_owner).status_code == 409

    def test_stale_request_blocks_merge_and_update_base_recovers(self, client, ws, owner, viewer, db):
        doc, cr = self._seed_request(client, ws, owner, viewer)
        auth_owner = _login(client, owner.username)
        auth_viewer = _login(client, viewer.username)
        merge_url = DCR.format(ws=ws.id) + f"/{cr['id']}/merge"

        # 提交后 owner 直编推进版本 → 申请基准过期
        assert _save(client, ws.id, doc["id"], auth_owner, "# 标题\n\n别人先改了\n").status_code == 200
        detail = client.get(DCR.format(ws=ws.id) + f"/{cr['id']}", headers=auth_owner).json()
        assert detail["stale"] is True
        assert detail["current_version_number"] == 2

        conflict = client.post(merge_url, headers=auth_owner)
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "document_change_request_stale"

        # 提交人刷新基准 → 可合并
        rebased = client.post(DCR.format(ws=ws.id) + f"/{cr['id']}/update-base", headers=auth_viewer)
        assert rebased.status_code == 200, rebased.text
        assert rebased.json()["stale"] is False
        assert rebased.json()["base_version_number"] == 2

        merged = client.post(merge_url, headers=auth_owner)
        assert merged.status_code == 200, merged.text
        assert merged.json()["version_number"] == 3

    def test_update_base_requires_submitter(self, client, ws, owner, viewer, db):
        _, cr = self._seed_request(client, ws, owner, viewer)
        auth_owner = _login(client, owner.username)

        r = client.post(DCR.format(ws=ws.id) + f"/{cr['id']}/update-base", headers=auth_owner)

        assert r.status_code == 403

    def test_merge_rejected_when_document_trashed(self, client, ws, owner, viewer, db):
        doc, cr = self._seed_request(client, ws, owner, viewer)
        auth_owner = _login(client, owner.username)

        assert client.delete(DOCS.format(ws=ws.id) + f"/{doc['id']}", headers=auth_owner).status_code == 200

        r = client.post(DCR.format(ws=ws.id) + f"/{cr['id']}/merge", headers=auth_owner)
        assert r.status_code == 409
        assert "回收站" in r.json()["detail"]

    def test_other_open_request_becomes_stale_after_merge(self, client, ws, owner, viewer, db):
        auth_owner = _login(client, owner.username)
        auth_viewer = _login(client, viewer.username)
        doc = _create_doc(client, ws.id, auth_owner)
        first = _save(client, ws.id, doc["id"], auth_viewer, "# 标题\n\n方案 A\n").json()["change_request"]
        second = _save(client, ws.id, doc["id"], auth_viewer, "# 标题\n\n方案 B\n").json()["change_request"]

        assert client.post(DCR.format(ws=ws.id) + f"/{first['id']}/merge", headers=auth_owner).status_code == 200

        detail = client.get(DCR.format(ws=ws.id) + f"/{second['id']}", headers=auth_owner).json()
        assert detail["stale"] is True
        assert detail["status"] == "open"


# ── 关闭 / 删除草稿 ───────────────────────────────────


class TestCloseAndDelete:
    def _seed_request(self, client, ws, owner, viewer) -> tuple[dict, dict]:
        auth_owner = _login(client, owner.username)
        auth_viewer = _login(client, viewer.username)
        doc = _create_doc(client, ws.id, auth_owner)
        r = _save(client, ws.id, doc["id"], auth_viewer, "# 标题\n\n提案内容\n")
        return doc, r.json()["change_request"]

    def test_owner_closes_request(self, client, ws, owner, viewer, db):
        _, cr = self._seed_request(client, ws, owner, viewer)
        auth_owner = _login(client, owner.username)

        r = client.post(
            DCR.format(ws=ws.id) + f"/{cr['id']}/close",
            json={"review_comment": "暂不采纳"},
            headers=auth_owner,
        )

        assert r.status_code == 200, r.text
        assert r.json()["status"] == "closed"
        assert r.json()["review_comment"] == "暂不采纳"

    def test_submitter_can_close_own_request(self, client, ws, owner, viewer, db):
        _, cr = self._seed_request(client, ws, owner, viewer)
        auth_viewer = _login(client, viewer.username)

        r = client.post(DCR.format(ws=ws.id) + f"/{cr['id']}/close", headers=auth_viewer)

        assert r.status_code == 200
        assert r.json()["status"] == "closed"

    def test_unrelated_viewer_cannot_close(self, client, ws, owner, viewer, db):
        _, cr = self._seed_request(client, ws, owner, viewer)
        other = _add_member(db, ws, "dcr_viewer2", WorkspaceRole.VIEWER)
        auth_other = _login(client, other.username)

        assert client.post(DCR.format(ws=ws.id) + f"/{cr['id']}/close", headers=auth_other).status_code == 403

    def test_submitter_deletes_draft(self, client, ws, owner, viewer, db):
        _, cr = self._seed_request(client, ws, owner, viewer)
        auth_viewer = _login(client, viewer.username)
        url = DCR.format(ws=ws.id) + f"/{cr['id']}"

        assert client.delete(url, headers=auth_viewer).status_code == 204
        assert client.get(url, headers=auth_viewer).status_code == 404
        # 草稿删除不影响文档版本
        assert client.get(DCR.format(ws=ws.id), headers=auth_viewer).json()["total"] == 0

    def test_owner_can_delete_others_draft(self, client, ws, owner, viewer, db):
        _, cr = self._seed_request(client, ws, owner, viewer)
        auth_owner = _login(client, owner.username)

        assert client.delete(DCR.format(ws=ws.id) + f"/{cr['id']}", headers=auth_owner).status_code == 204

    def test_unrelated_viewer_cannot_delete_draft(self, client, ws, owner, viewer, db):
        _, cr = self._seed_request(client, ws, owner, viewer)
        other = _add_member(db, ws, "dcr_viewer3", WorkspaceRole.VIEWER)
        auth_other = _login(client, other.username)

        assert client.delete(DCR.format(ws=ws.id) + f"/{cr['id']}", headers=auth_other).status_code == 403

    def test_merged_request_cannot_be_deleted(self, client, ws, owner, viewer, db):
        _, cr = self._seed_request(client, ws, owner, viewer)
        auth_owner = _login(client, owner.username)
        merge_url = DCR.format(ws=ws.id) + f"/{cr['id']}/merge"

        assert client.post(merge_url, headers=auth_owner).status_code == 200
        r = client.delete(DCR.format(ws=ws.id) + f"/{cr['id']}", headers=auth_owner)

        assert r.status_code == 409
        assert "草稿" in r.json()["detail"]
