"""文档树「导出 → 导入」回环测试（需求 0088）.

覆盖两种压缩方式（压缩文档 / Obsidian 库）的导出后再导入：
- Markdown 正文与嵌套文件夹结构保持不变；
- 原件族（PDF / Excel / Word 存档）按原件字节回环，不被转成空 Markdown；
- 站内图片随包导出（``attachments/``）并在导入时重新落盘为附件；
- 第二代回环（导入后再导出、再导入）仍然稳定。
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
FILE_IMPORT = DOCS + "/import/files"
ZIP_IMPORT = DOCS + "/import"
ZIP_ANALYZE = DOCS + "/import/analyze"
EXPORT = DOCS + "/export/vault"

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\nROUNDTRIP"


def _xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "数据"
    sheet.append(["月份", "金额"])
    sheet.append(["一月", 1200.5])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _docx_bytes() -> bytes:
    from docx import Document as DocxDocument

    document = DocxDocument()
    document.add_heading("封面", level=1)
    document.add_paragraph("正文段落")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


XLSX_BYTES = _xlsx_bytes()
DOCX_BYTES = _docx_bytes()
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
    return _make_user(db, "roundtrip_owner")


@pytest.fixture
def auth(client, owner) -> dict[str, str]:
    return _login(client, owner.username)


def _workspace(db: Session, owner: User, name: str) -> Workspace:
    workspace = Workspace(name=name, created_by_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(workspace)
    return workspace


@pytest.fixture
def ws(db, owner) -> Workspace:
    return _workspace(db, owner, "回环源")


def _flat(nodes: list[dict], out: list[dict] | None = None) -> list[dict]:
    out = [] if out is None else out
    for node in nodes:
        out.append(node)
        _flat(node.get("children") or [], out)
    return out


def _tree(client, ws_id: int, auth) -> list[dict]:
    r = client.get(DOCS.format(ws=ws_id) + "/tree", headers=auth)
    assert r.status_code == 200, r.text
    return _flat(r.json()["items"])


def _content(client, ws_id: int, doc_id: int, auth) -> str:
    r = client.get(f"{DOCS.format(ws=ws_id)}/{doc_id}/content", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["content"]


def _seed(client, db, ws: Workspace, owner: User, auth) -> None:
    """源工作区：嵌套 Markdown（带站内图片）+ PDF + xlsx + docx（存档）."""
    # 站内图片：正文引用 file:<key>，导出应进入 attachments/
    updir = Path(settings.UPLOAD_DIR) / str(ws.id)
    updir.mkdir(parents=True, exist_ok=True)
    (updir / "roundtrip.png").write_bytes(PNG_BYTES)
    assert client.post(
        DOCS.format(ws=ws.id),
        json={
            "title": "说明",
            "content": "# 说明\n\n正文第一段。\n\n![图](file:roundtrip.png)\n",
            "status": "published",
        },
        headers=auth,
    ).status_code in (200, 201)

    r = client.post(
        FILE_IMPORT.format(ws=ws.id),
        files=[
            ("files", ("报告.pdf", PDF_BYTES, "application/pdf")),
            ("files", ("数据.xlsx", XLSX_BYTES, XLSX_MIME)),
            ("files", ("说明书.docx", DOCX_BYTES, DOCX_MIME)),
            ("files", ("笔记/索引.md", "# 索引\n\n嵌套目录正文。\n".encode(), "text/markdown")),
        ],
        data={
            "paths": ["报告.pdf", "数据.xlsx", "说明书.docx", "笔记/索引.md"],
            "status": "published",
            "docx_mode": "archive",
        },
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 4


def _export(client, ws_id: int, auth, style: str) -> bytes:
    r = client.get(EXPORT.format(ws=ws_id), params={"style": style}, headers=auth)
    assert r.status_code == 200, r.text
    return r.content


def _import_zip(client, ws_id: int, auth, data: bytes, style: str, *, conflict: str = "rename") -> dict:
    r = client.post(
        ZIP_IMPORT.format(ws=ws_id),
        files={"file": ("roundtrip.zip", data, "application/zip")},
        data={"style": style, "conflict": conflict, "status": "published"},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _asset_bytes(client, ws_id: int, auth, doc_id: int) -> bytes:
    r = client.get(f"{DOCS.format(ws=ws_id)}/{doc_id}/asset", headers=auth)
    assert r.status_code == 200, r.text
    return r.content


def _assert_tree_roundtrip(client, source_ws: Workspace, target_ws: Workspace, auth) -> None:
    """结构 / 正文 / 原件三层校验（两种方式共用）."""
    source = {node["title"]: node for node in _tree(client, source_ws.id, auth) if not node["is_folder"]}
    target = {node["title"]: node for node in _tree(client, target_ws.id, auth) if not node["is_folder"]}
    assert set(target) == set(source), target.keys()

    # Markdown 正文与嵌套文件夹结构
    assert _content(client, target_ws.id, target["说明"]["id"], auth).strip().startswith("# 说明")
    assert target["索引"]["parent_id"] is not None
    assert "嵌套目录正文" in _content(client, target_ws.id, target["索引"]["id"], auth)
    assert any(node["is_folder"] and node["title"] == "笔记" for node in _tree(client, target_ws.id, auth))

    # 原件族：内容类型与字节都保持原样（不再落空 Markdown）
    assert target["报告"]["content_type"] == "pdf"
    assert _asset_bytes(client, target_ws.id, auth, target["报告"]["id"]) == PDF_BYTES
    assert target["数据"]["content_type"] == "xlsx"
    assert _asset_bytes(client, target_ws.id, auth, target["数据"]["id"]) == XLSX_BYTES
    assert target["说明书"]["content_type"] == "word"
    assert _asset_bytes(client, target_ws.id, auth, target["说明书"]["id"]) == DOCX_BYTES

    # 站内图片：导出进 attachments/，导入后重新落盘为站内附件（正文引用 file:）
    note = _content(client, target_ws.id, target["说明"]["id"], auth)
    assert "file:" in note and "![" in note


class TestArchiveRoundtrip:
    def test_archive_export_import_roundtrip(self, client, db, ws, owner, auth):
        _seed(client, db, ws, owner, auth)
        exported = _export(client, ws.id, auth, "archive")

        target = _workspace(db, owner, "回环压缩包")
        stats = _import_zip(client, target.id, auth, exported, "archive")
        assert stats["created"] >= 4
        assert stats["assets"] == 3

        _assert_tree_roundtrip(client, ws, target, auth)
        # 压缩文档：导出物不带 front-matter / .obsidian
        with zipfile.ZipFile(io.BytesIO(exported)) as archive:
            names = set(archive.namelist())
            assert "回环源/说明.md" in names
            assert not any(name.startswith("回环源/.obsidian/") for name in names)
            assert not archive.read("回环源/说明.md").decode("utf-8").startswith("---")

    def test_archive_roundtrip_is_stable_across_generations(self, client, db, ws, owner, auth):
        """第二代回环：导入后的工作区再导出 → 再导入，结构与原件仍然一致."""
        _seed(client, db, ws, owner, auth)
        first = _workspace(db, owner, "回环二段A")
        _import_zip(client, first.id, auth, _export(client, ws.id, auth, "archive"), "archive")

        second = _workspace(db, owner, "回环二段B")
        stats = _import_zip(client, second.id, auth, _export(client, first.id, auth, "archive"), "archive")
        assert stats["assets"] == 3
        _assert_tree_roundtrip(client, first, second, auth)


class TestObsidianRoundtrip:
    def test_obsidian_export_import_roundtrip(self, client, db, ws, owner, auth):
        _seed(client, db, ws, owner, auth)
        exported = _export(client, ws.id, auth, "obsidian")

        target = _workspace(db, owner, "回环库")
        stats = _import_zip(client, target.id, auth, exported, "obsidian")
        assert stats["assets"] == 3
        assert stats["created"] >= 4

        _assert_tree_roundtrip(client, ws, target, auth)
        # Obsidian 库：导出物带 front-matter 与 .obsidian 配置
        with zipfile.ZipFile(io.BytesIO(exported)) as archive:
            names = set(archive.namelist())
            assert "回环源/.obsidian/app.json" in names
            assert archive.read("回环源/说明.md").decode("utf-8").startswith("---")

        # 说明文档带 front-matter（title / created / updated），导入后正文不含元数据块
        assert "---" not in _content(
            client,
            target.id,
            next(node["id"] for node in _tree(client, target.id, auth) if node["title"] == "说明"),
            auth,
        )

    def test_obsidian_roundtrip_keeps_tags(self, client, db, ws, owner, auth):
        _seed(client, db, ws, owner, auth)
        # 给 Markdown 文档挂标签，导出 front-matter 后再导入应恢复标签
        from cndb.plugins.documents.models import Document, Tag
        from cndb.plugins.documents.services import content as content_service

        note = next(node for node in _tree(client, ws.id, auth) if node["title"] == "说明")
        tag = Tag(workspace_id=ws.id, name="回环标签", color="", description="")
        db.add(tag)
        db.commit()
        content_service._apply_tags(db, db.get(Document, note["id"]), [tag.id], owner)

        exported = _export(client, ws.id, auth, "obsidian")
        target = _workspace(db, owner, "回环库标签")
        stats = _import_zip(client, target.id, auth, exported, "obsidian")
        assert "回环标签" in stats["tags_created"]
        imported = next(node for node in _tree(client, target.id, auth) if node["title"] == "说明")
        assert imported["tag_ids"]


class TestZipAnalyze:
    def test_archive_analyze_counts_assets(self, client, db, ws, owner, auth):
        _seed(client, db, ws, owner, auth)
        exported = _export(client, ws.id, auth, "archive")

        r = client.post(
            ZIP_ANALYZE.format(ws=ws.id),
            files={"file": ("roundtrip.zip", exported, "application/zip")},
            data={"style": "archive"},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["assets"] == 3
        assert any(item["is_asset"] for item in data["items"])
        assert {"pdf", "xlsx", "word"} <= {item["kind"] for item in data["items"] if item["is_asset"]}

    def test_invalid_import_style_rejected(self, client, db, ws, owner, auth):
        _seed(client, db, ws, owner, auth)
        exported = _export(client, ws.id, auth, "archive")

        r = client.post(
            ZIP_IMPORT.format(ws=ws.id),
            files={"file": ("roundtrip.zip", exported, "application/zip")},
            data={"style": "word"},
            headers=auth,
        )
        assert r.status_code == 400
