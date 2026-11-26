"""文档复制副本（需求 0172）测试.

覆盖：最新正文 / 标签复制、版本仅 v1、标题递增、文件夹子树、原件族文件复制、
viewer 403 与跨工作区 404。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

API = "/api/v1/workspaces/{wid}/documents"
TAGS = "/api/v1/workspaces/{wid}/document-tags"


def _ws(client: TestClient, auth: dict[str, str], name: str) -> int:
    r = client.post("/api/v1/workspaces", json={"name": name}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create(client: TestClient, auth: dict[str, str], wid: int, title: str, content: str = "", **extra) -> dict:
    r = client.post(API.format(wid=wid), json={"title": title, "content": content, **extra}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def _duplicate(client: TestClient, auth: dict[str, str], wid: int, doc_id: int, **body) -> dict:
    r = client.post(f"{API.format(wid=wid)}/{doc_id}/duplicate", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


class TestDuplicateDocument:
    def test_copies_latest_content_tags_and_single_version(self, client, auth_headers):
        wid = _ws(client, auth_headers, "副本-单文档")
        doc = _create(client, auth_headers, wid, "需求说明", "第一版")
        r = client.put(
            f"{API.format(wid=wid)}/{doc['id']}/content",
            json={"content": "第二版正文"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        tag = client.post(TAGS.format(wid=wid), json={"name": "重要", "color": "#ff0000"}, headers=auth_headers).json()
        assert (
            client.post(
                f"{API.format(wid=wid)}/{doc['id']}/tags",
                json={"tag_ids": [tag["id"]]},
                headers=auth_headers,
            ).status_code
            == 200
        )

        copy = _duplicate(client, auth_headers, wid, doc["id"])
        assert copy["title"] == "需求说明 副本"
        assert copy["version_count"] == 1
        assert copy["tag_ids"] == [tag["id"]]

        detail = client.get(f"{API.format(wid=wid)}/{copy['id']}/content", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["content"] == "第二版正文"

    def test_title_increments(self, client, auth_headers):
        wid = _ws(client, auth_headers, "副本-标题")
        doc = _create(client, auth_headers, wid, "周报", "正文")
        first = _duplicate(client, auth_headers, wid, doc["id"])
        second = _duplicate(client, auth_headers, wid, doc["id"])
        third = _duplicate(client, auth_headers, wid, doc["id"])
        assert [first["title"], second["title"], third["title"]] == ["周报 副本", "周报 副本 2", "周报 副本 3"]

    def test_folder_subtree(self, client, auth_headers):
        wid = _ws(client, auth_headers, "副本-文件夹")
        root = _create(client, auth_headers, wid, "资料", is_folder=True)
        sub = _create(client, auth_headers, wid, "子目录", is_folder=True, parent_id=root["id"])
        leaf = _create(client, auth_headers, wid, "说明", "叶子正文", parent_id=sub["id"])

        copy_root = _duplicate(client, auth_headers, wid, root["id"])
        assert copy_root["title"] == "资料 副本"

        tree = client.get(f"{API.format(wid=wid)}/tree", headers=auth_headers).json()["items"]
        copy_sub = next(item for item in tree if item["parent_id"] == copy_root["id"])
        assert copy_sub["title"] == "子目录"
        copy_leaf = next(item for item in tree if item["parent_id"] == copy_sub["id"])
        assert copy_leaf["title"] == "说明"
        assert copy_leaf["id"] != leaf["id"]

    def test_cross_workspace_is_404(self, client, auth_headers):
        wid = _ws(client, auth_headers, "副本-本区")
        other = _ws(client, auth_headers, "副本-他区")
        doc = _create(client, auth_headers, wid, "本区文档", "正文")
        r = client.post(f"{API.format(wid=other)}/{doc['id']}/duplicate", json={}, headers=auth_headers)
        assert r.status_code == 404, r.text

    def test_viewer_forbidden(self, client, auth_headers, db: Session):
        from cndb.plugins.accounts.models import User
        from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole

        wid = _ws(client, auth_headers, "副本-只读")
        doc = _create(client, auth_headers, wid, "只读区文档", "正文", status="published")
        viewer = User(username="dup_viewer", nickname="dup_viewer")
        viewer.set_password("passw0rd")
        db.add(viewer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        r = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": "dup_viewer", "password": "passw0rd"},
        )
        assert r.status_code == 200, r.text
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = client.post(f"{API.format(wid=wid)}/{doc['id']}/duplicate", json={}, headers=headers)
        assert r.status_code == 403, r.text

    def test_asset_file_copied_with_new_key(self, db: Session, client, auth_headers):
        from cndb.core.config import settings
        from cndb.plugins.accounts.models import User
        from cndb.plugins.documents.services import content as content_service

        wid = _ws(client, auth_headers, "副本-原件")
        owner = db.query(User).filter(User.username == "testuser").first()
        assert owner is not None
        upload_dir = Path(settings.UPLOAD_DIR) / str(wid)
        upload_dir.mkdir(parents=True, exist_ok=True)
        key = "dup-source.pdf"
        (upload_dir / key).write_bytes(b"%PDF-1.4 duplicate test")

        doc = content_service.create_document(
            db,
            wid,
            owner,
            title="原件文档",
            content="",
            content_type="pdf",
            asset_file_key=key,
            asset_mime="application/pdf",
            content_size=23,
        )
        copy = content_service.duplicate_document(db, wid, doc.id, owner)
        assert copy.asset_file_key and copy.asset_file_key != key
        assert (upload_dir / copy.asset_file_key).read_bytes() == b"%PDF-1.4 duplicate test"
