"""Obsidian 文档库（vault）导入 / 导出测试.

覆盖：
- analyze 只读预览（计数 / 冲突 / 标签 / 忽略项），不落任何数据；
- import：目录 → 文件夹、front-matter 标题与标签、附件落盘与站内引用改写、双链规范化；
- 冲突三策略（skip / rename / overwrite）与导入到指定文件夹；
- 安全边界：非 zip、zip 路径穿越条目、viewer 无权限；
- export：库结构、front-matter、附件、可回环再导入。
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.plugins.accounts.models import User
from cndb.plugins.files.models import FileOwner
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
ANALYZE = DOCS + "/import/analyze"
IMPORT = DOCS + "/import"
EXPORT = DOCS + "/export/vault"

PNG_BYTES = b"\x89PNG\r\n\x1a\nFAKE"

INDEX_MD = """---
title: 索引页
tags: [项目, 研究/方法]
---

# 索引页

参见 [[笔记/设计稿#架构|设计]]，另有 [[不存在笔记]]。

![[图.png]]

![](attachments/photo.jpg)
"""

DESIGN_MD = """---
tags:
  - 项目
---

设计稿正文，回链 [[索引页]]。
"""


def _login(client, username: str, password: str = "passw0rd") -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_user(db: Session, username: str) -> User:
    user = User(username=username, nickname=username)
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def owner(db) -> User:
    return _make_user(db, "ob_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    workspace = Workspace(name="我的知识库", created_by_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(workspace)
    return workspace


@pytest.fixture
def auth(client, owner) -> dict[str, str]:
    return _login(client, owner.username)


def _build_zip(files: dict[str, bytes | str], root: str = "MyVault") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            payload = data.encode("utf-8") if isinstance(data, str) else data
            archive.writestr(f"{root}/{name}" if root else name, payload)
    return buffer.getvalue()


def _vault_zip() -> bytes:
    return _build_zip(
        {
            "索引页.md": INDEX_MD,
            "笔记/设计稿.md": DESIGN_MD,
            "图.png": PNG_BYTES,
            "attachments/photo.jpg": b"JPEG",
            ".obsidian/app.json": "{}",
            ".trash/deleted.md": "# 已删除",
        }
    )


def _post_zip(client, url: str, data: bytes, auth: dict[str, str], **form):
    return client.post(url, files={"file": ("vault.zip", data, "application/zip")}, data=form, headers=auth)


def _tree(client, ws_id: int, auth: dict[str, str]) -> list[dict]:
    r = client.get(DOCS.format(ws=ws_id) + "/tree", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _content(client, ws_id: int, doc_id: int, auth: dict[str, str]) -> str:
    r = client.get(f"{DOCS.format(ws=ws_id)}/{doc_id}/content", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["content"]


class TestAnalyze:
    def test_analyze_counts_without_writing(self, client, db, ws, auth):
        r = _post_zip(client, ANALYZE.format(ws=ws.id), _vault_zip(), auth)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["total_notes"] == 2
        assert data["total_folders"] == 1  # 笔记/
        assert data["total_attachments"] == 2
        assert data["conflicts"] == 0
        assert set(data["tags"]) == {"项目", "研究/方法"}
        # .obsidian / .trash 被忽略
        assert data["ignored_files"] == 2
        assert data["root_dir"] == "MyVault"
        statuses = {item["path"]: item["status"] for item in data["items"]}
        assert statuses == {"索引页.md": "new", "笔记/设计稿.md": "new"}
        # 只读：库里没有新增文档
        assert _tree(client, ws.id, auth) == []

    def test_analyze_detects_conflicts(self, client, ws, auth):
        assert _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth).status_code == 200
        r = _post_zip(client, ANALYZE.format(ws=ws.id), _vault_zip(), auth)
        assert r.status_code == 200, r.text
        assert r.json()["conflicts"] == 2

    def test_analyze_rejects_non_zip(self, client, ws, auth):
        r = client.post(
            ANALYZE.format(ws=ws.id),
            files={"file": ("vault.zip", b"not a zip", "application/zip")},
            headers=auth,
        )
        assert r.status_code == 400
        assert "zip" in r.json()["detail"].lower()

    def test_analyze_rejects_other_extension(self, client, ws, auth):
        r = client.post(
            ANALYZE.format(ws=ws.id),
            files={"file": ("vault.tar", b"anything", "application/x-tar")},
            headers=auth,
        )
        assert r.status_code == 400

    def test_zip_slip_entries_are_dropped(self, client, ws, auth):
        data = _build_zip({"ok.md": "# OK\n", "../evil.md": "# Evil\n"}, root="")
        r = _post_zip(client, ANALYZE.format(ws=ws.id), data, auth)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["total_notes"] == 1
        assert any(".." in item["path"] for item in payload["skipped"])


class TestImport:
    def test_import_creates_tree_tags_and_attachments(self, client, db, ws, auth):
        r = _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth)
        assert r.status_code == 200, r.text
        stats = r.json()
        assert stats["created"] == 2
        assert stats["folders_created"] == 1
        assert stats["attachments"] == 2
        assert set(stats["tags_created"]) == {"项目", "研究/方法"}

        titles = {item["title"]: item for item in _tree(client, ws.id, auth)}
        assert set(titles) == {"笔记", "索引页", "设计稿"}
        assert titles["笔记"]["is_folder"] is True
        assert titles["设计稿"]["parent_id"] == titles["笔记"]["id"]

        # front-matter 标题生效，正文里的双链被规范化，附件改为站内引用
        body = _content(client, ws.id, titles["索引页"]["id"], auth)
        assert "[[设计稿]]" in body
        assert "[[不存在笔记]]" in body
        assert "[[笔记/设计稿#架构|设计]]" not in body
        assert "[[图.png]]" not in body

        keys = re.findall(r"!\[[^\]]*\]\(file:([^)\s]+)\)", body)
        assert len(keys) == 2
        for key in keys:
            assert (Path(settings.UPLOAD_DIR) / str(ws.id) / key).is_file()
            owner_row = db.query(FileOwner).filter(FileOwner.file_key == key).one()
            assert owner_row.document_id == titles["索引页"]["id"]

        # front-matter 标签落到工作区标签并关联到文档
        tags = client.get(DOCS.format(ws=ws.id) + "/tags", headers=auth).json()["items"]
        assert {tag["name"] for tag in tags} == {"项目", "研究/方法"}
        detail = client.get(f"{DOCS.format(ws=ws.id)}/{titles['索引页']['id']}", headers=auth).json()
        assert len(detail["tag_ids"]) == 2

    def test_import_into_folder(self, client, ws, auth):
        folder = client.post(
            DOCS.format(ws=ws.id),
            json={"title": "收件箱", "content": "", "is_folder": True},
            headers=auth,
        ).json()
        r = _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth, parent_id=str(folder["id"]))
        assert r.status_code == 200, r.text
        root_level = [item for item in _tree(client, ws.id, auth) if item["parent_id"] == folder["id"]]
        assert {item["title"] for item in root_level} == {"笔记", "索引页"}

    def test_import_into_non_folder_is_rejected(self, client, ws, auth):
        doc = client.post(DOCS.format(ws=ws.id), json={"title": "普通文档", "content": ""}, headers=auth).json()
        r = _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth, parent_id=str(doc["id"]))
        assert r.status_code == 409

    def test_conflict_skip_keeps_original(self, client, ws, auth):
        assert _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth).status_code == 200
        r = _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth, conflict="skip")
        assert r.status_code == 200, r.text
        stats = r.json()
        assert stats["created"] == 0
        assert stats["skipped"] == 2
        assert len([item for item in _tree(client, ws.id, auth) if not item["is_folder"]]) == 2

    def test_conflict_rename_appends_suffix(self, client, ws, auth):
        assert _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth).status_code == 200
        r = _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth, conflict="rename")
        assert r.status_code == 200, r.text
        titles = {item["title"] for item in _tree(client, ws.id, auth)}
        assert {"索引页", "索引页 (2)", "设计稿", "设计稿 (2)"} <= titles

    def test_conflict_overwrite_creates_new_version(self, client, ws, auth):
        assert _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth).status_code == 200
        target = next(item for item in _tree(client, ws.id, auth) if item["title"] == "索引页")
        assert target["version_count"] == 1

        changed = _build_zip({"索引页.md": "---\ntitle: 索引页\n---\n改过的正文\n"})
        r = _post_zip(client, IMPORT.format(ws=ws.id), changed, auth, conflict="overwrite")
        assert r.status_code == 200, r.text
        assert r.json()["updated"] == 1

        detail = client.get(f"{DOCS.format(ws=ws.id)}/{target['id']}/content", headers=auth).json()
        assert detail["content"].strip() == "改过的正文"
        assert detail["version_count"] == 2

    def test_import_attachments_can_be_skipped(self, client, ws, auth):
        r = _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth, import_attachments="false")
        assert r.status_code == 200, r.text
        stats = r.json()
        assert stats["attachments"] == 0
        assert any(w["code"] == "attachments_not_imported" for w in stats["warnings"])

    def test_tags_can_be_skipped(self, client, ws, auth):
        r = _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth, import_tags="false")
        assert r.status_code == 200, r.text
        assert client.get(DOCS.format(ws=ws.id) + "/tags", headers=auth).json()["items"] == []

    def test_documents_imported_as_published(self, client, ws, auth):
        r = _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth, status="published")
        assert r.status_code == 200, r.text
        items = _tree(client, ws.id, auth)
        assert all(item["status"] == "published" for item in items if not item["is_folder"])

    def test_viewer_cannot_import(self, client, db, ws, auth):
        viewer = _make_user(db, "ob_viewer")
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        viewer_auth = _login(client, viewer.username)
        r = _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), viewer_auth)
        assert r.status_code == 403

    def test_bad_conflict_policy(self, client, ws, auth):
        r = _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth, conflict="replace")
        assert r.status_code == 400


class TestExport:
    def test_export_structure(self, client, ws, auth):
        assert _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth).status_code == 200

        r = client.get(EXPORT.format(ws=ws.id), headers=auth)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"

        with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
            names = set(archive.namelist())
            assert "我的知识库/索引页.md" in names
            assert "我的知识库/笔记/设计稿.md" in names
            assert "我的知识库/.obsidian/app.json" in names
            assert any(name.startswith("我的知识库/attachments/") for name in names)
            note = archive.read("我的知识库/索引页.md").decode("utf-8")
            assert note.startswith("---")
            assert "title: 索引页" in note
            assert "项目" in note
            assert "![[attachments/" in note

    def test_export_roundtrip_reimport(self, client, ws, auth):
        assert _post_zip(client, IMPORT.format(ws=ws.id), _vault_zip(), auth).status_code == 200
        exported = client.get(EXPORT.format(ws=ws.id), headers=auth).content

        target = client.post("/api/v1/workspaces", json={"name": "回环库"}, headers=auth).json()
        r = _post_zip(client, IMPORT.format(ws=target["id"]), exported, auth)
        assert r.status_code == 200, r.text
        assert r.json()["created"] == 2
        titles = {item["title"] for item in _tree(client, target["id"], auth)}
        assert {"索引页", "设计稿"} <= titles

    def test_export_empty_workspace(self, client, ws, auth):
        r = client.get(EXPORT.format(ws=ws.id), headers=auth)
        assert r.status_code == 400
