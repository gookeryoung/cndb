"""PDF 旋转 / 水平镜像派生副本测试（ADR 0164 P0）.

判定层（模块直测）与接口层（方向信息 / 派生副本 / 权限 / 异常 / 缓存）分开写，
与 ADR 0164 §7 的测试清单一一对应。
"""

from __future__ import annotations

import io
import re
import struct
import zlib

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import Document
from cndb.plugins.documents.services.preview import pdf_rotation
from cndb.plugins.files.services import resolve_workspace_file
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
IMPORT = DOCS + "/import/files"


def _pdf_bytes(*, pages: int = 1, size: tuple[float, float] = (200, 100), text: str = "LEFT") -> bytes:
    """用 reportlab 生成带文字的样本 PDF（默认一页横向 200x100）."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=size)
    for _ in range(pages):
        c.drawString(10, 50, text)
        c.showPage()
    c.save()
    return buffer.getvalue()


def _png_bytes() -> bytes:
    """最小 PNG（1x1），用于「非 PDF 不受理」用例."""

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


def _rotated_pdf(data: bytes, angle: int) -> bytes:
    """给样本 PDF 的每页声明 ``/Rotate``（模拟扫描件自带方向标记）."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    for page in writer.pages:
        page.rotate(angle)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _content_bytes(data: bytes) -> bytes:
    from pypdf import PdfReader

    page = PdfReader(io.BytesIO(data)).pages[0]
    return page.get_contents().get_data()


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
    return _make_user(db, "rotate_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    workspace = Workspace(name="方向库", created_by_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(workspace)
    return workspace


@pytest.fixture
def auth(client, owner) -> dict[str, str]:
    return _login(client, owner.username)


@pytest.fixture(autouse=True)
def _clean_rotation_cache():
    pdf_rotation.clear_cache()
    yield
    pdf_rotation.clear_cache()


def _import_one(client, ws_id: int, auth, name: str, data: bytes, ctype: str) -> dict:
    r = client.post(
        IMPORT.format(ws=ws_id),
        files=[("files", (name, data, ctype))],
        data={"paths": name},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _imported_doc(db: Session, ws_id: int) -> Document:
    doc = db.scalars(select(Document).where(Document.workspace_id == ws_id)).one()
    return doc


# ── 判定层：模块直测 ──


class TestPdfRotationModule:
    def test_read_page_orientations(self):
        pages = pdf_rotation.read_page_orientations(_pdf_bytes(pages=2))
        assert len(pages) == 2
        assert pages[0].rotate == 0
        assert (pages[0].width, pages[0].height) == (200.0, 100.0)

    def test_rotate_90_swaps_mediabox_and_resets_rotate(self):
        result = pdf_rotation.render_rotated(_pdf_bytes(), rotate=90, flip=False)
        from pypdf import PdfReader

        page = PdfReader(io.BytesIO(result)).pages[0]
        assert round(float(page.mediabox.width), 1) == 100.0
        assert round(float(page.mediabox.height), 1) == 200.0
        assert int(page.get("/Rotate", 0) or 0) == 0

    def test_flip_writes_mirror_matrix(self):
        result = pdf_rotation.render_rotated(_pdf_bytes(), rotate=0, flip=True)
        assert re.search(rb"-1\s+0\.0?\s+0\.0?\s+1\s+200", _content_bytes(result))

    def test_rejects_invalid_angle(self):
        with pytest.raises(ValueError):
            pdf_rotation.render_rotated(_pdf_bytes(), rotate=45, flip=False)

    def test_rejects_unreadable_bytes(self):
        with pytest.raises(pdf_rotation.PdfRotationError):
            pdf_rotation.read_page_orientations(b"not a pdf")
        with pytest.raises(pdf_rotation.PdfRotationError):
            pdf_rotation.render_rotated(b"not a pdf", rotate=90, flip=False)

    def test_rejects_encrypted_pdf(self):
        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(_pdf_bytes())))
        writer.encrypt(user_password="secret")
        out = io.BytesIO()
        writer.write(out)
        with pytest.raises(pdf_rotation.PdfRotationError):
            pdf_rotation.read_page_orientations(out.getvalue())


# ── 接口层 ──


class TestOrientationEndpoint:
    def test_reports_pages_and_uniform_aspect(self, client, ws, auth):
        _import_one(client, ws.id, auth, "横版.pdf", _pdf_bytes(pages=2), "application/pdf")
        doc_id = _imported_doc_id(client, ws.id, auth)
        r = client.get(DOCS.format(ws=ws.id) + f"/{doc_id}/asset/orientation", headers=auth)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["page_count"] == 2
        assert body["uniform_rotate"] == 0
        assert body["uniform_aspect"] == "landscape"

    def test_reports_declared_rotate(self, client, db, ws, auth):
        _import_one(client, ws.id, auth, "带方向.pdf", _rotated_pdf(_pdf_bytes(), 90), "application/pdf")
        doc_id = _imported_doc_id(client, ws.id, auth)
        r = client.get(DOCS.format(ws=ws.id) + f"/{doc_id}/asset/orientation", headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["uniform_rotate"] == 90

    def test_non_pdf_is_404(self, client, ws, auth):
        _import_one(client, ws.id, auth, "图.png", _png_bytes(), "image/png")
        doc_id = _imported_doc_id(client, ws.id, auth)
        r = client.get(DOCS.format(ws=ws.id) + f"/{doc_id}/asset/orientation", headers=auth)
        assert r.status_code == 404

    def test_unreadable_pdf_is_422(self, client, ws, auth):
        _import_one(client, ws.id, auth, "坏.pdf", b"not a pdf", "application/pdf")
        doc_id = _imported_doc_id(client, ws.id, auth)
        r = client.get(DOCS.format(ws=ws.id) + f"/{doc_id}/asset/orientation", headers=auth)
        assert r.status_code == 422
        assert r.json()["code"] == "pdf_unreadable"

    def test_non_member_is_403(self, client, db, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", _pdf_bytes(), "application/pdf")
        doc_id = _imported_doc_id(client, ws.id, auth)
        _make_user(db, "rotate_outsider")
        outsider = _login(client, "rotate_outsider")
        r = client.get(DOCS.format(ws=ws.id) + f"/{doc_id}/asset/orientation", headers=outsider)
        assert r.status_code == 403


class TestRotatedEndpoint:
    def test_rotate_90_returns_pdf(self, client, ws, auth):
        _import_one(client, ws.id, auth, "横版.pdf", _pdf_bytes(), "application/pdf")
        doc_id = _imported_doc_id(client, ws.id, auth)
        r = client.get(
            DOCS.format(ws=ws.id) + f"/{doc_id}/asset/rotated",
            params={"rotate": 90},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/pdf")
        from pypdf import PdfReader

        page = PdfReader(io.BytesIO(r.content)).pages[0]
        assert round(float(page.mediabox.width), 1) == 100.0
        assert round(float(page.mediabox.height), 1) == 200.0

    def test_rotation_is_relative_to_declared_rotate(self, client, ws, auth):
        """页面自带 /Rotate=90 + 用户再转 90 → 只应用一次方向，输出 180°（200x100）."""
        _import_one(client, ws.id, auth, "带方向.pdf", _rotated_pdf(_pdf_bytes(), 90), "application/pdf")
        doc_id = _imported_doc_id(client, ws.id, auth)
        r = client.get(
            DOCS.format(ws=ws.id) + f"/{doc_id}/asset/rotated",
            params={"rotate": 90},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        from pypdf import PdfReader

        page = PdfReader(io.BytesIO(r.content)).pages[0]
        assert round(float(page.mediabox.width), 1) == 200.0
        assert round(float(page.mediabox.height), 1) == 100.0
        assert int(page.get("/Rotate", 0) or 0) == 0

    def test_flip_mirrors_content(self, client, ws, auth):
        _import_one(client, ws.id, auth, "横版.pdf", _pdf_bytes(), "application/pdf")
        doc_id = _imported_doc_id(client, ws.id, auth)
        r = client.get(
            DOCS.format(ws=ws.id) + f"/{doc_id}/asset/rotated",
            params={"rotate": 0, "flip": "true"},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert re.search(rb"-1\s+0\.0?\s+0\.0?\s+1\s+200", _content_bytes(r.content))

    def test_original_bytes_unchanged(self, client, ws, auth):
        _import_one(client, ws.id, auth, "横版.pdf", _pdf_bytes(), "application/pdf")
        doc_id = _imported_doc_id(client, ws.id, auth)
        before = client.get(DOCS.format(ws=ws.id) + f"/{doc_id}/asset", headers=auth)
        assert before.status_code == 200
        client.get(DOCS.format(ws=ws.id) + f"/{doc_id}/asset/rotated", params={"rotate": 90}, headers=auth)
        after = client.get(DOCS.format(ws=ws.id) + f"/{doc_id}/asset", headers=auth)
        assert after.content == before.content

    def test_invalid_rotate_is_422(self, client, ws, auth):
        _import_one(client, ws.id, auth, "横版.pdf", _pdf_bytes(), "application/pdf")
        doc_id = _imported_doc_id(client, ws.id, auth)
        r = client.get(
            DOCS.format(ws=ws.id) + f"/{doc_id}/asset/rotated",
            params={"rotate": 45},
            headers=auth,
        )
        assert r.status_code == 422
        assert r.json()["code"] == "pdf_rotation_invalid"

    def test_non_pdf_is_404(self, client, ws, auth):
        _import_one(client, ws.id, auth, "图.png", _png_bytes(), "image/png")
        doc_id = _imported_doc_id(client, ws.id, auth)
        r = client.get(DOCS.format(ws=ws.id) + f"/{doc_id}/asset/rotated", headers=auth)
        assert r.status_code == 404

    def test_unreadable_pdf_is_422(self, client, ws, auth):
        _import_one(client, ws.id, auth, "坏.pdf", b"not a pdf", "application/pdf")
        doc_id = _imported_doc_id(client, ws.id, auth)
        r = client.get(DOCS.format(ws=ws.id) + f"/{doc_id}/asset/rotated", headers=auth)
        assert r.status_code == 422
        assert r.json()["code"] == "pdf_unreadable"

    def test_missing_asset_file_is_404(self, client, db, ws, auth):
        _import_one(client, ws.id, auth, "横版.pdf", _pdf_bytes(), "application/pdf")
        doc = _imported_doc(db, ws.id)
        resolve_workspace_file(ws.id, doc.asset_file_key or "").unlink()
        r = client.get(DOCS.format(ws=ws.id) + f"/{doc.id}/asset/rotated", headers=auth)
        assert r.status_code == 404

    def test_derived_copy_is_cached(self, client, ws, auth, monkeypatch):
        _import_one(client, ws.id, auth, "横版.pdf", _pdf_bytes(), "application/pdf")
        doc_id = _imported_doc_id(client, ws.id, auth)
        calls: list[int] = []
        original = pdf_rotation.render_rotated

        def counting(data, *, rotate, flip):
            calls.append(rotate)
            return original(data, rotate=rotate, flip=flip)

        monkeypatch.setattr(pdf_rotation, "render_rotated", counting)
        url = DOCS.format(ws=ws.id) + f"/{doc_id}/asset/rotated"
        assert client.get(url, params={"rotate": 90}, headers=auth).status_code == 200
        assert client.get(url, params={"rotate": 90}, headers=auth).status_code == 200
        assert client.get(url, params={"rotate": 180}, headers=auth).status_code == 200
        assert calls == [90, 180]

    def test_non_member_is_403(self, client, db, ws, auth):
        _import_one(client, ws.id, auth, "横版.pdf", _pdf_bytes(), "application/pdf")
        doc_id = _imported_doc_id(client, ws.id, auth)
        _make_user(db, "rotate_outsider2")
        outsider = _login(client, "rotate_outsider2")
        r = client.get(DOCS.format(ws=ws.id) + f"/{doc_id}/asset/rotated", headers=outsider)
        assert r.status_code == 403


def _imported_doc_id(client, ws_id: int, auth) -> int:
    """取工作区里唯一的非文件夹文档 id（导入用例一次只放一份原件）."""
    r = client.get(DOCS.format(ws=ws_id) + "/tree", headers=auth)
    assert r.status_code == 200, r.text

    def flatten(nodes):
        for node in nodes:
            yield node
            yield from flatten(node.get("children") or [])

    docs = [node for node in flatten(r.json()["items"]) if not node["is_folder"]]
    assert len(docs) == 1, docs
    return int(docs[0]["id"])
