"""工作区附件管理（需求 0174）测试.

覆盖：列表分页/搜索与归属文档、体检引用计数与孤儿判定、回收 dry-run/实际删除、
被引用文件不误删、viewer 403。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

BASE = "/api/v1/workspaces/{wid}/documents"
ATT = BASE + "/attachments"


def _ws(client: TestClient, auth: dict[str, str], name: str) -> int:
    r = client.post("/api/v1/workspaces", json={"name": name}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _write_upload(wid: int, key: str, payload: bytes = b"0123456789") -> Path:
    from cndb.core.config import settings

    directory = Path(settings.UPLOAD_DIR) / str(wid)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / key
    path.write_bytes(payload)
    old = time.time() - 2 * 24 * 3600
    os.utime(path, (old, old))
    return path


class TestAttachments:
    def test_list_search_and_owner_title(self, client, auth_headers, db):
        from cndb.plugins.accounts.models import User
        from cndb.plugins.documents.services import content as content_service
        from cndb.plugins.files.services import record_owner

        wid = _ws(client, auth_headers, "附件-列表")
        _write_upload(wid, "aaa.png")
        _write_upload(wid, "bbb.pdf", b"x" * 20)
        owner = db.query(User).filter(User.username == "testuser").first()
        assert owner is not None
        doc = content_service.create_document(db, wid, owner, title="图片文档", content="![x](file:aaa.png)")
        record_owner(db, file_key="aaa.png", workspace_id=wid, document_id=doc.id, uploaded_by_id=owner.id)

        r = client.get(ATT.format(wid=wid), headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 2
        first = next(item for item in body["items"] if item["file_key"] == "aaa.png")
        assert first["document_title"] == "图片文档"
        assert first["has_owner"] is True

        r = client.get(ATT.format(wid=wid), params={"q": "bbb"}, headers=auth_headers)
        assert [item["file_key"] for item in r.json()["items"]] == ["bbb.pdf"]

    def test_scan_and_purge(self, client, auth_headers, db):
        from cndb.core.config import settings
        from cndb.plugins.accounts.models import User
        from cndb.plugins.documents.services import content as content_service

        wid = _ws(client, auth_headers, "附件-回收")
        _write_upload(wid, "used.png")
        orphan = _write_upload(wid, "orphan.png", b"o" * 30)
        owner = db.query(User).filter(User.username == "testuser").first()
        assert owner is not None
        content_service.create_document(db, wid, owner, title="引用文档", content="![x](file:used.png)")

        scan = client.post(f"{ATT.format(wid=wid)}/scan", headers=auth_headers)
        assert scan.status_code == 200, scan.text
        report = scan.json()
        by_key = {item["file_key"]: item for item in report["items"]}
        assert by_key["used.png"]["ref_count"] == 1
        assert by_key["used.png"]["orphan"] is False
        assert by_key["orphan.png"]["orphan"] is True
        assert report["orphan_count"] == 1

        dry = client.post(f"{ATT.format(wid=wid)}/purge", json={"dry_run": True}, headers=auth_headers)
        assert dry.status_code == 200, dry.text
        assert dry.json()["removed_files"] == 0
        assert orphan.is_file()

        apply = client.post(f"{ATT.format(wid=wid)}/purge", json={"dry_run": False}, headers=auth_headers)
        assert apply.status_code == 200, apply.text
        assert apply.json()["removed_files"] == 1
        assert not orphan.is_file()
        assert (Path(settings.UPLOAD_DIR) / str(wid) / "used.png").is_file()

    def test_viewer_forbidden(self, client, auth_headers, db):
        from cndb.plugins.accounts.models import User
        from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole

        wid = _ws(client, auth_headers, "附件-只读")
        viewer = User(username="att_viewer", nickname="att_viewer")
        viewer.set_password("passw0rd")
        db.add(viewer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        r = client.post("/api/v1/accounts/auth/login", json={"login": "att_viewer", "password": "passw0rd"})
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert client.get(ATT.format(wid=wid), headers=headers).status_code == 403
        assert client.post(f"{ATT.format(wid=wid)}/scan", headers=headers).status_code == 403
