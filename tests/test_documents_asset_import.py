"""原件族导入测试（ADR 0025）：PDF / Office / 图片原样存档 + 原件端点 + 只读守卫.

判定层（格式注册表 / 分派）与接口层（导入 / 预览 / 覆盖 / 权限 / 下载 / 彻底删除）分开写，
与 ADR 0025 §7 的测试清单一一对应。
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.services.importers import formats, reader
from cndb.plugins.documents.services.importers.errors import UnsupportedImport
from cndb.plugins.files.models import FileOwner
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
ANALYZE = DOCS + "/import/files/analyze"
IMPORT = DOCS + "/import/files"

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"
XLSX_BYTES = b"PK\x03\x04fake-xlsx-payload"
PPTX_BYTES = b"PK\x03\x04fake-pptx-payload"


def _png_bytes() -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        head = struct.pack(">I", len(payload)) + kind + payload
        return head + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )


PNG_BYTES = _png_bytes()


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
    return _make_user(db, "asset_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    workspace = Workspace(name="原件库", created_by_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(workspace)
    return workspace


@pytest.fixture
def auth(client, owner) -> dict[str, str]:
    return _login(client, owner.username)


def _files(*entries: tuple[str, bytes, str]) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (name, data, ctype)) for name, data, ctype in entries]


def _tree(client, ws_id: int, auth) -> list[dict]:
    r = client.get(DOCS.format(ws=ws_id) + "/tree", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _flat(nodes: list[dict], out: list[dict] | None = None) -> list[dict]:
    out = [] if out is None else out
    for node in nodes:
        out.append(node)
        _flat(node.get("children") or [], out)
    return out


def _import_one(client, ws_id: int, auth, name: str, data: bytes, ctype: str, **form) -> dict:
    r = client.post(
        IMPORT.format(ws=ws_id),
        files=_files((name, data, ctype)),
        data={"paths": name, **form},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _doc(client, ws_id: int, auth) -> dict:
    nodes = [node for node in _flat(_tree(client, ws_id, auth)) if not node["is_folder"]]
    assert len(nodes) == 1, nodes
    return nodes[0]


# ── 判定层：格式注册表 / 分派 ──


class TestFormats:
    def test_registry_covers_required_formats(self):
        assert formats.asset_format("a.pdf").content_type == "pdf"  # type: ignore[union-attr]
        assert formats.asset_format("A.PDF").mime == "application/pdf"  # type: ignore[union-attr]
        assert formats.asset_format("a.PNG").content_type == "image"  # type: ignore[union-attr]
        assert formats.asset_format("a.jpg").mime == "image/jpeg"  # type: ignore[union-attr]
        assert formats.asset_format("a.svg").mime == "image/svg+xml"  # type: ignore[union-attr]
        assert formats.asset_format("a.xlsx").content_type == "xlsx"  # type: ignore[union-attr]
        assert formats.asset_format("a.ppt").content_type == "pptx"  # type: ignore[union-attr]

    def test_registry_rejects_unknown(self):
        assert formats.asset_format("a.txt") is None
        assert formats.asset_format("a") is None
        assert not formats.is_supported("a.zip")
        assert formats.is_convertible("a.docx")
        assert not formats.is_convertible("a.pdf")

    def test_convertible_formats_stay_markdown(self):
        doc = reader.convert_file(reader.UploadedItem("a.md", b"# T\n\nbody\n"))
        assert doc.asset is False
        assert doc.content_type == "markdown"

    def test_asset_dispatch(self):
        doc = reader.convert_file(reader.UploadedItem("dir/报告.pdf", PDF_BYTES))
        assert doc.asset is True
        assert doc.body == ""
        assert doc.title == "报告"
        assert doc.content_type == "pdf"
        assert doc.mime == "application/pdf"

    def test_asset_oversize_rejected(self, monkeypatch):
        monkeypatch.setattr(formats, "MAX_ASSET_BYTES", 2)
        monkeypatch.setattr(reader, "MAX_ASSET_BYTES", 2)
        with pytest.raises(UnsupportedImport):
            reader.convert_file(reader.UploadedItem("a.pdf", PDF_BYTES))

    def test_empty_asset_rejected(self):
        with pytest.raises(UnsupportedImport):
            reader.convert_file(reader.UploadedItem("a.png", b""))


# ── 接口层 ──


class TestAnalyzeAssets:
    def test_preview_marks_asset_and_writes_nothing(self, client, ws, auth):
        r = client.post(
            ANALYZE.format(ws=ws.id),
            files=_files(
                ("报告.pdf", PDF_BYTES, "application/pdf"),
                ("封面.png", PNG_BYTES, "image/png"),
            ),
            data={"paths": ["报告.pdf", "封面.png"]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["assets"] == 2
        assert data["total_documents"] == 2
        items = {item["title"]: item for item in data["items"]}
        assert items["报告"]["is_asset"] is True
        assert items["报告"]["format"] == "pdf"
        assert items["封面"]["format"] == "image"
        assert _tree(client, ws.id, auth) == []


class TestImportAssets:
    def test_import_pdf_and_read_back(self, client, ws, auth):
        stats = _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        assert stats["created"] == 1
        assert stats["assets"] == 1
        doc = _doc(client, ws.id, auth)
        assert doc["content_type"] == "pdf"
        assert doc["asset_mime"] == "application/pdf"
        assert doc["content_size"] == len(PDF_BYTES)

        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=auth)
        assert r.status_code == 200, r.text
        assert r.content == PDF_BYTES
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.headers["content-disposition"].startswith("inline")

    def test_import_image_and_office(self, client, ws, auth):
        r = client.post(
            IMPORT.format(ws=ws.id),
            files=_files(
                ("封面.png", PNG_BYTES, "image/png"),
                ("数据.xlsx", XLSX_BYTES, "application/vnd.ms-excel"),
                ("胶片.pptx", PPTX_BYTES, "application/vnd.ms-powerpoint"),
            ),
            data={"paths": ["封面.png", "数据.xlsx", "胶片.pptx"]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        stats = r.json()
        assert stats["created"] == 3
        assert stats["assets"] == 3
        assert stats["attachments"] == 0
        types = {node["title"]: node["content_type"] for node in _flat(_tree(client, ws.id, auth))}
        assert types == {"封面": "image", "数据": "xlsx", "胶片": "pptx"}

    def test_binds_file_owner_to_document(self, client, db, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        owners = db.execute(select(FileOwner).where(FileOwner.workspace_id == ws.id)).scalars().all()
        assert len(owners) == 1
        assert owners[0].document_id == doc["id"]

    def test_folder_mode_keeps_asset_in_folder(self, client, ws, auth):
        r = client.post(
            IMPORT.format(ws=ws.id),
            files=_files(("资料/报告.pdf", PDF_BYTES, "application/pdf")),
            data={"paths": ["资料/报告.pdf"]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        nodes = _flat(_tree(client, ws.id, auth))
        folder = next(node for node in nodes if node["is_folder"])
        doc = next(node for node in nodes if not node["is_folder"])
        assert doc["parent_id"] == folder["id"]

    def test_overwrite_replaces_asset_and_drops_old_file(self, client, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        old_keys = [path.name for path in (Path(settings.UPLOAD_DIR) / str(ws.id)).iterdir()]
        assert len(old_keys) == 1

        new_bytes = PDF_BYTES + b"REV2\n"
        stats = _import_one(client, ws.id, auth, "报告.pdf", new_bytes, "application/pdf", conflict="overwrite")
        assert stats["updated"] == 1
        assert stats["created"] == 0

        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=auth)
        assert r.content == new_bytes
        remaining = [path.name for path in (Path(settings.UPLOAD_DIR) / str(ws.id)).iterdir()]
        assert len(remaining) == 1
        assert remaining != old_keys

    def test_skip_keeps_first_asset(self, client, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        stats = _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES + b"X", "application/pdf", conflict="skip")
        assert stats["skipped"] == 1
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=auth)
        assert r.content == PDF_BYTES

    def test_asset_does_not_replace_markdown_document(self, client, ws, auth):
        """同名 Markdown 文档不被只读原件覆盖（改名保留两份）."""
        client.post(
            IMPORT.format(ws=ws.id),
            files=_files(("报告.md", b"# x\n\nbody\n", "text/markdown")),
            data={"paths": "报告.md"},
            headers=auth,
        )
        stats = _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf", conflict="overwrite")
        assert stats["created"] == 1
        assert stats["updated"] == 0
        kinds = {node["title"]: node["content_type"] for node in _flat(_tree(client, ws.id, auth))}
        assert kinds == {"x": "markdown", "报告": "pdf"}

    def test_oversize_asset_only_skips_itself(self, client, ws, auth, monkeypatch):
        monkeypatch.setattr(reader, "MAX_ASSET_BYTES", 4)
        r = client.post(
            IMPORT.format(ws=ws.id),
            files=_files(
                ("ok.md", b"# ok\n\nbody\n", "text/markdown"),
                ("big.pdf", PDF_BYTES, "application/pdf"),
            ),
            data={"paths": ["ok.md", "big.pdf"]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        stats = r.json()
        assert stats["created"] == 1
        assert stats["skipped"] == 1
        assert stats["skipped_files"][0]["path"] == "big.pdf"

    def test_viewer_cannot_import_asset(self, client, db, ws):
        viewer = _make_user(db, "asset_viewer")
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        r = client.post(
            IMPORT.format(ws=ws.id),
            files=_files(("报告.pdf", PDF_BYTES, "application/pdf")),
            data={"paths": "报告.pdf"},
            headers=_login(client, viewer.username),
        )
        assert r.status_code == 403

    def test_non_member_cannot_import_asset(self, client, db, ws):
        outsider = _make_user(db, "asset_outsider")
        r = client.post(
            IMPORT.format(ws=ws.id),
            files=_files(("报告.pdf", PDF_BYTES, "application/pdf")),
            data={"paths": "报告.pdf"},
            headers=_login(client, outsider.username),
        )
        assert r.status_code == 403


class TestAssetEndpoint:
    def test_markdown_document_has_no_asset(self, client, ws, auth):
        client.post(DOCS.format(ws=ws.id), json={"title": "普通文档", "content": "正文"}, headers=auth)
        doc = _doc(client, ws.id, auth)
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=auth)
        assert r.status_code == 404

    def test_download_disposition(self, client, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset?download=true", headers=auth)
        assert r.status_code == 200
        assert r.headers["content-disposition"].startswith("attachment")

    def test_svg_gets_sandbox_header(self, client, ws, auth):
        _import_one(client, ws.id, auth, "图标.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")
        doc = _doc(client, ws.id, auth)
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=auth)
        assert r.status_code == 200
        assert r.headers["content-security-policy"] == "sandbox"
        assert r.headers["x-content-type-options"] == "nosniff"

    def test_unpublished_asset_hidden_from_other_member(self, client, db, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        member = _make_user(db, "asset_member")
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=member.id, role=WorkspaceRole.EDITOR))
        db.commit()
        member_auth = _login(client, member.username)
        # 草稿态文档对非创建者不可见 → 原件同样 404
        assert client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=member_auth).status_code == 404

        published = client.patch(DOCS.format(ws=ws.id) + f"/{doc['id']}", json={"status": "published"}, headers=auth)
        assert published.status_code == 200, published.text
        assert client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=member_auth).status_code == 200

    def test_missing_file_returns_404(self, client, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        for path in (Path(settings.UPLOAD_DIR) / str(ws.id)).iterdir():
            path.unlink()
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=auth)
        assert r.status_code == 404


class TestAssetReadOnly:
    def test_content_draft_submit_rejected(self, client, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        base = DOCS.format(ws=ws.id) + f"/{doc['id']}"

        r = client.put(f"{base}/content", json={"content": "# 改写"}, headers=auth)
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "doc_read_only"

        r = client.put(f"{base}/draft", json={"content": "# 草稿"}, headers=auth)
        assert r.status_code == 409

        r = client.post(f"{base}/submit", json={"content": "# 提交"}, headers=auth)
        assert r.status_code == 409

    def test_rollback_rejected(self, client, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        r = client.post(f"{DOCS.format(ws=ws.id)}/{doc['id']}/rollback", json={"target_version": 1}, headers=auth)
        assert r.status_code == 409


class TestAssetPurge:
    def test_purge_removes_original_and_owner(self, client, db, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        directory = Path(settings.UPLOAD_DIR) / str(ws.id)
        assert len(list(directory.iterdir())) == 1

        base = DOCS.format(ws=ws.id) + f"/{doc['id']}"
        assert client.delete(base, headers=auth).status_code == 200
        purged = client.delete(f"{base}/purge", headers=auth)
        assert purged.status_code == 200, purged.text
        assert list(directory.iterdir()) == []
        owners = db.execute(select(FileOwner).where(FileOwner.workspace_id == ws.id)).scalars().all()
        assert owners == []


class TestAssetServiceGuards:
    """服务层分支（接口层不易触达的防御口径）."""

    def test_replace_requires_asset_document(self, db, ws, owner):
        from cndb.core.errors import ConflictError
        from cndb.plugins.documents.services import content as content_service

        markdown_doc = content_service.create_document(db, ws.id, owner, title="普通文档", content="正文")
        with pytest.raises(ConflictError):
            content_service.replace_document_asset(
                db,
                ws.id,
                markdown_doc.id,
                owner,
                asset_file_key="x.pdf",
                asset_mime="application/pdf",
                content_size=10,
            )

    def test_replace_rejects_folder(self, db, ws, owner):
        from cndb.core.errors import ConflictError
        from cndb.plugins.documents.services import content as content_service

        folder = content_service.create_document(db, ws.id, owner, title="目录", is_folder=True)
        with pytest.raises(ConflictError):
            content_service.replace_document_asset(
                db,
                ws.id,
                folder.id,
                owner,
                asset_file_key="x.pdf",
                asset_mime="application/pdf",
                content_size=10,
            )

    def test_remove_workspace_file_tolerates_bad_key(self, ws):
        from cndb.plugins.files.services import remove_workspace_file

        assert remove_workspace_file(ws.id, "../escape.pdf") is False
        assert remove_workspace_file(ws.id, "not-exists.pdf") is False
