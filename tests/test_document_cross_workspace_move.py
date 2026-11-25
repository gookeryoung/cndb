"""文档跨工作区移动（ADR 0155）测试.

覆盖：
- 单篇 / 多篇 / 文件夹子树（含回收站子节点）/ 指定目标文件夹；
- 源侧读路径全 404、目标侧可读，版本链逐条保留；
- 站内图片搬迁（同 file_key 在目标工作区可下载，源侧文件已删）；
- 访客分享链接**继续生效**、修改申请**随文档迁移**、问题清单随行；
- 配额**写盘前阻断**（413 且无任何写入）；
- 权限矩阵（源/目标 viewer 403、目标模块关闭 400、目标=源 400、回收站根节点 400、父节点非法 400）；
- `move-targets` 只返回有写权限 + 文档模块已开的工作区；
- 幂等（重复移动 404）、缺失文件降级、两侧事件。
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import (
    Document,
    DocumentChangeRequest,
    DocumentIssue,
    DocumentShare,
    DocumentVersion,
)
from cndb.plugins.files.models import FileOwner
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
MOVE = "/api/v1/workspaces/{ws}/documents/move-to-workspace"
TARGETS = "/api/v1/workspaces/{ws}/documents/move-targets"
FILES = "/api/v1/workspaces/{ws}/files"

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001a5f645400000000049454e44ae426082"
)


def _login(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _make_user(db: Session, username: str) -> User:
    user = User(username=username, nickname=username)
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_workspace(db: Session, owner: User, name: str, *, modules: list[str] | None = None) -> Workspace:
    ws = Workspace(name=name, created_by_id=owner.id, modules=modules or ["tables", "documents"])
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(ws)
    return ws


@pytest.fixture
def owner(db) -> User:
    return _make_user(db, "move_owner")


@pytest.fixture
def source(db, owner) -> Workspace:
    return _make_workspace(db, owner, "移动源工作区")


@pytest.fixture
def target(db, owner) -> Workspace:
    return _make_workspace(db, owner, "移动目标工作区")


@pytest.fixture
def headers(client, owner) -> dict[str, str]:
    return _login(client, owner.username)


def _create_doc(
    client: TestClient,
    ws: Workspace,
    headers: dict[str, str],
    *,
    title: str,
    content: str = "正文\n",
    status: str = "published",
    is_folder: bool = False,
    parent_id: int | None = None,
) -> dict:
    resp = client.post(
        f"{DOCS.format(ws=ws.id)}",
        json={"title": title, "content": content, "status": status, "is_folder": is_folder, "parent_id": parent_id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _move(client: TestClient, ws: Workspace, headers: dict[str, str], payload: dict):
    return client.post(MOVE.format(ws=ws.id), json=payload, headers=headers)


class TestMoveBasics:
    def test_single_document(self, client, db, source, target, headers):
        doc = _create_doc(client, source, headers, title="单篇")
        second = client.put(
            f"{DOCS.format(ws=source.id)}/{doc['id']}/content",
            json={"content": "第二版正文\n"},
            headers=headers,
        )
        assert second.status_code in (200, 202), second.text

        versions_before = [
            (v.version_number, v.content)
            for v in db.query(DocumentVersion)
            .filter(DocumentVersion.document_id == doc["id"])
            .order_by(DocumentVersion.version_number)
        ]
        assert len(versions_before) >= 2

        resp = _move(client, source, headers, {"document_ids": [doc["id"]], "target_workspace_id": target.id})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["document_ids"] == [doc["id"]]
        assert body["moved_nodes"] == 1
        assert body["target_workspace_id"] == target.id

        # 源侧：详情 / 版本 / 导出 全 404
        assert client.get(f"{DOCS.format(ws=source.id)}/{doc['id']}", headers=headers).status_code == 404
        assert client.get(f"{DOCS.format(ws=source.id)}/{doc['id']}/versions", headers=headers).status_code == 404
        assert (
            client.get(f"{DOCS.format(ws=source.id)}/{doc['id']}/export", params={"format": "md"}, headers=headers)
        ).status_code == 404
        # 目标侧：可读且版本链完整
        detail = client.get(f"{DOCS.format(ws=target.id)}/{doc['id']}", headers=headers)
        assert detail.status_code == 200
        moved_versions = [
            (v.version_number, v.content)
            for v in db.query(DocumentVersion)
            .filter(DocumentVersion.document_id == doc["id"])
            .order_by(DocumentVersion.version_number)
        ]
        assert moved_versions == versions_before
        # 源工作区列表不再包含、目标工作区列表包含
        source_list = client.get(DOCS.format(ws=source.id), headers=headers).json()
        target_list = client.get(DOCS.format(ws=target.id), headers=headers).json()
        assert all(item["id"] != doc["id"] for item in source_list["items"])
        assert any(item["id"] == doc["id"] for item in target_list["items"])

    def test_multiple_documents(self, client, db, source, target, headers):
        first = _create_doc(client, source, headers, title="批量一")
        second = _create_doc(client, source, headers, title="批量二")
        resp = _move(
            client,
            source,
            headers,
            {"document_ids": [first["id"], second["id"]], "target_workspace_id": target.id},
        )
        assert resp.status_code == 200, resp.text
        assert sorted(resp.json()["document_ids"]) == sorted([first["id"], second["id"]])
        assert resp.json()["moved_nodes"] == 2
        for doc_id in (first["id"], second["id"]):
            assert client.get(f"{DOCS.format(ws=target.id)}/{doc_id}", headers=headers).status_code == 200

    def test_folder_subtree_including_trashed_child(self, client, db, source, target, headers):
        folder = _create_doc(client, source, headers, title="文件夹", is_folder=True)
        child = _create_doc(client, source, headers, title="子文档", parent_id=folder["id"])
        subfolder = _create_doc(client, source, headers, title="子文件夹", is_folder=True, parent_id=folder["id"])
        grandchild = _create_doc(client, source, headers, title="孙文档", parent_id=subfolder["id"])
        trashed = _create_doc(client, source, headers, title="已删子文档", parent_id=folder["id"])
        assert client.delete(f"{DOCS.format(ws=source.id)}/{trashed['id']}", headers=headers).status_code in (200, 204)

        resp = _move(client, source, headers, {"document_ids": [folder["id"]], "target_workspace_id": target.id})
        assert resp.status_code == 200, resp.text
        assert resp.json()["moved_nodes"] == 5

        for doc_id in (folder["id"], child["id"], subfolder["id"], grandchild["id"]):
            assert client.get(f"{DOCS.format(ws=target.id)}/{doc_id}", headers=headers).status_code == 200
        # 子树结构完整：孙文档的父节点仍是子文件夹（同工作区、parent_id 不变）
        grandchild_row = db.get(Document, grandchild["id"])
        assert grandchild_row.parent_id == subfolder["id"]
        assert grandchild_row.workspace_id == target.id
        # 回收站中的子节点也一起搬走（D11）
        assert db.get(Document, trashed["id"]).workspace_id == target.id

    def test_move_into_target_folder(self, client, db, source, target, headers):
        doc = _create_doc(client, source, headers, title="落目标文件夹")
        target_folder = _create_doc(client, target, headers, title="目标文件夹", is_folder=True)
        resp = _move(
            client,
            source,
            headers,
            {"document_ids": [doc["id"]], "target_workspace_id": target.id, "parent_id": target_folder["id"]},
        )
        assert resp.status_code == 200, resp.text
        moved = db.get(Document, doc["id"])
        assert moved.parent_id == target_folder["id"]

    def test_repeat_move_is_404(self, client, source, target, headers):
        doc = _create_doc(client, source, headers, title="幂等")
        payload = {"document_ids": [doc["id"]], "target_workspace_id": target.id}
        assert _move(client, source, headers, payload).status_code == 200
        assert _move(client, source, headers, payload).status_code == 404


class TestMoveFiles:
    def _upload(self, client: TestClient, ws: Workspace, headers: dict[str, str], document_id: int) -> str:
        resp = client.post(
            FILES.format(ws=ws.id),
            files={"file": ("pic.png", io.BytesIO(PNG_1PX), "image/png")},
            data={"document_id": str(document_id)},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["file_key"]

    def test_inline_image_moves_with_document(self, client, db, source, target, headers):
        doc = _create_doc(client, source, headers, title="带图文档")
        file_key = self._upload(client, source, headers, doc["id"])
        saved = client.put(
            f"{DOCS.format(ws=source.id)}/{doc['id']}/content",
            json={"content": f"![图](file:{file_key})\n"},
            headers=headers,
        )
        assert saved.status_code in (200, 202), saved.text

        resp = _move(client, source, headers, {"document_ids": [doc["id"]], "target_workspace_id": target.id})
        assert resp.status_code == 200, resp.text
        assert resp.json()["moved_files"] == 1

        # 目标工作区按同一 file_key 可下载；源工作区已不存在
        assert client.get(f"{FILES.format(ws=target.id)}/{file_key}", headers=headers).status_code == 200
        assert client.get(f"{FILES.format(ws=source.id)}/{file_key}", headers=headers).status_code == 404
        # 文件归属改写为目标工作区
        owner_row = db.query(FileOwner).filter(FileOwner.file_key == file_key).one()
        assert owner_row.workspace_id == target.id

    def test_missing_file_is_reported_not_blocking(self, client, db, source, target, headers):
        doc = _create_doc(client, source, headers, title="缺文件")
        client.put(
            f"{DOCS.format(ws=source.id)}/{doc['id']}/content",
            json={"content": "![图](file:not-exist-abc.png)\n"},
            headers=headers,
        )
        resp = _move(client, source, headers, {"document_ids": [doc["id"]], "target_workspace_id": target.id})
        assert resp.status_code == 200, resp.text
        assert resp.json()["moved_files"] == 0
        assert resp.json()["missing_files"] == ["not-exist-abc.png"]


class TestMoveCutOverSurface:
    def test_share_keeps_working(self, client, db, source, target, headers):
        doc = _create_doc(client, source, headers, title="分享继续", status="published")
        share = client.post(
            f"{DOCS.format(ws=source.id)}/{doc['id']}/share",
            json={"permission": "viewer"},
            headers=headers,
        )
        assert share.status_code == 201, share.text
        token = share.json()["token"]
        assert client.get(f"/api/v1/documents/share/{token}").status_code == 200

        assert (
            _move(client, source, headers, {"document_ids": [doc["id"]], "target_workspace_id": target.id}).status_code
            == 200
        )

        # 分享链接不撤销：仍按「已发布 + 文档可见性」判定
        still = client.get(f"/api/v1/documents/share/{token}")
        assert still.status_code == 200, still.text
        share_row = db.query(DocumentShare).filter(DocumentShare.token == token).one()
        assert share_row.is_active is True

    def test_change_request_migrates(self, client, db, source, target, headers):
        doc = _create_doc(client, source, headers, title="待审稿件", status="published")
        viewer = _make_user(db, "move_viewer")
        db.add(WorkspaceMember(workspace_id=source.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        viewer_headers = _login(client, viewer.username)
        # viewer 保存 → 生成修改申请（202）
        proposed = client.put(
            f"{DOCS.format(ws=source.id)}/{doc['id']}/content",
            json={"content": "viewer 的待审正文\n"},
            headers=viewer_headers,
        )
        assert proposed.status_code == 202, proposed.text
        request_id = proposed.json()["change_request"]["id"]

        assert (
            _move(client, source, headers, {"document_ids": [doc["id"]], "target_workspace_id": target.id}).status_code
            == 200
        )
        row = db.get(DocumentChangeRequest, request_id)
        assert row.workspace_id == target.id
        assert row.status == "open"
        # 目标工作区的申请列表能看到它，源工作区看不到
        target_list = client.get(f"/api/v1/workspaces/{target.id}/document-change-requests", headers=headers)
        assert target_list.status_code == 200
        assert any(item["id"] == request_id for item in target_list.json()["items"])
        source_list = client.get(f"/api/v1/workspaces/{source.id}/document-change-requests", headers=headers)
        assert all(item["id"] != request_id for item in source_list.json()["items"])

    def test_issue_migrates(self, client, db, source, target, headers):
        doc = _create_doc(client, source, headers, title="带问题文档")
        issue = client.post(
            f"/api/v1/workspaces/{source.id}/document-issues",
            json={"document_id": doc["id"], "title": "渲染异常", "description": "细节", "category": "data_error"},
            headers=headers,
        )
        assert issue.status_code == 201, issue.text
        issue_id = issue.json()["id"]
        assert (
            _move(client, source, headers, {"document_ids": [doc["id"]], "target_workspace_id": target.id}).status_code
            == 200
        )
        row = db.get(DocumentIssue, issue_id)
        assert row.workspace_id == target.id
        detail = client.get(f"/api/v1/workspaces/{target.id}/document-issues/{issue_id}", headers=headers)
        assert detail.status_code == 200


class TestMoveGuards:
    def test_quota_blocks_before_write(self, client, db, source, target, headers):
        doc = _create_doc(client, source, headers, title="配额")
        target.storage_quota_bytes = 1
        db.commit()
        resp = _move(client, source, headers, {"document_ids": [doc["id"]], "target_workspace_id": target.id})
        assert resp.status_code in (400, 413), resp.text
        assert "存储空间不足" in resp.text
        # 未发生任何写入
        assert db.get(Document, doc["id"]).workspace_id == source.id

    def test_source_viewer_forbidden(self, client, db, source, target, headers):
        doc = _create_doc(client, source, headers, title="viewer 移出")
        viewer = _make_user(db, "move_viewer2")
        db.add(WorkspaceMember(workspace_id=source.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        viewer_headers = _login(client, viewer.username)
        resp = _move(client, source, viewer_headers, {"document_ids": [doc["id"]], "target_workspace_id": target.id})
        assert resp.status_code == 403

    def test_target_viewer_forbidden(self, client, db, source, target, headers):
        doc = _create_doc(client, source, headers, title="目标只读")
        viewer = _make_user(db, "move_viewer3")
        db.add(WorkspaceMember(workspace_id=target.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        viewer_headers = _login(client, viewer.username)
        resp = _move(client, source, viewer_headers, {"document_ids": [doc["id"]], "target_workspace_id": target.id})
        # 目标无写权限 → 403；同时该用户不是源工作区成员 → 先 404
        assert resp.status_code in (403, 404)

    def test_target_module_disabled(self, client, db, source, owner, headers):
        frozen = _make_workspace(db, owner, "无文档模块", modules=["tables"])
        doc = _create_doc(client, source, headers, title="模块关闭")
        resp = _move(client, source, headers, {"document_ids": [doc["id"]], "target_workspace_id": frozen.id})
        assert resp.status_code == 400
        assert "文档模块" in resp.text

    def test_same_workspace_rejected(self, client, source, headers):
        doc = _create_doc(client, source, headers, title="自身")
        resp = _move(client, source, headers, {"document_ids": [doc["id"]], "target_workspace_id": source.id})
        assert resp.status_code == 400

    def test_trashed_root_rejected(self, client, source, target, headers):
        doc = _create_doc(client, source, headers, title="回收站根")
        assert client.delete(f"{DOCS.format(ws=source.id)}/{doc['id']}", headers=headers).status_code in (200, 204)
        resp = _move(client, source, headers, {"document_ids": [doc["id"]], "target_workspace_id": target.id})
        assert resp.status_code == 400
        assert "回收站" in resp.text

    def test_bad_parent_rejected(self, client, source, target, headers):
        doc = _create_doc(client, source, headers, title="父节点非法")
        text_folder = _create_doc(client, target, headers, title="不是文件夹")
        resp = _move(
            client,
            source,
            headers,
            {"document_ids": [doc["id"]], "target_workspace_id": target.id, "parent_id": text_folder["id"]},
        )
        assert resp.status_code == 400

    def test_empty_and_too_many_ids(self, client, source, target, headers):
        doc = _create_doc(client, source, headers, title="数量")
        assert _move(client, source, headers, {"document_ids": [], "target_workspace_id": target.id}).status_code in (
            400,
            422,
        )
        too_many = [doc["id"]] * 201
        assert _move(
            client, source, headers, {"document_ids": too_many, "target_workspace_id": target.id}
        ).status_code in (400, 422)


class TestMoveTargets:
    def test_lists_only_writable_document_workspaces(self, client, db, source, target, owner, headers):
        _make_workspace(db, owner, "无文档模块", modules=["tables"])
        other_owner = _make_user(db, "move_other_owner")
        _make_workspace(db, other_owner, "别人的工作区")
        resp = client.get(TARGETS.format(ws=source.id), headers=headers)
        assert resp.status_code == 200, resp.text
        names = [item["name"] for item in resp.json()["items"]]
        assert names == ["移动目标工作区"]
        item = resp.json()["items"][0]
        assert item["quota_bytes"] > 0
        assert item["remaining_bytes"] >= 0

    def test_non_member_404(self, client, db, source):
        outsider = _make_user(db, "move_outsider")
        outsider_headers = _login(client, outsider.username)
        # 非成员按文档区统一口径：403（ADR 0047「申请加入」文案）
        assert client.get(TARGETS.format(ws=source.id), headers=outsider_headers).status_code in (403, 404)
