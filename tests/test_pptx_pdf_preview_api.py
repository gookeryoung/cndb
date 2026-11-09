"""ADR 0129 P0 接口层测试：权限 / 202/200/304 / 错误映射 / 导入钩子 / 不改原件."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import Document
from cndb.plugins.documents.services.preview import pdf_converter, pptx_pdf
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
IMPORT = DOCS + "/import/files"
PDF_MIME = "application/pdf"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PPTX_BYTES = b"PK\x03\x04fake-pptx-payload"
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"


@pytest.fixture(autouse=True)
def _pdf_env(monkeypatch, tmp_path):
    pptx_pdf.reset_state()
    monkeypatch.setattr(settings, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(settings, "PPTX_PDF_MAX_SOURCE_BYTES", 1024)
    monkeypatch.setattr(settings, "PPTX_PDF_RETRY", 1)
    yield
    pptx_pdf.reset_state()


@pytest.fixture
def workspace(db: Session, auth_headers) -> Workspace:
    owner = db.execute(select(User).where(User.username == "testuser")).scalar_one()
    workspace = Workspace(name="PDF 接口", created_by_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(workspace)
    return workspace


def _import(client, ws_id: int, auth, name: str, data: bytes, mime: str, **form) -> dict:
    r = client.post(
        IMPORT.format(ws=ws_id),
        files=[("files", (name, data, mime))],
        data={"paths": name, **form},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _record_dispatch(monkeypatch, *, ok: bool = True) -> list[tuple[int, int, str]]:
    calls: list[tuple[int, int, str]] = []

    def _dispatch(workspace_id: int, doc_id: int, asset_file_key: str) -> bool:
        calls.append((workspace_id, doc_id, asset_file_key))
        return ok

    monkeypatch.setattr(pptx_pdf, "_dispatch", _dispatch)
    return calls


def _url(ws_id: int, doc_id: int) -> str:
    return f"{DOCS.format(ws=ws_id)}/{doc_id}/asset/pdf"


def test_non_pptx_is_409(client, workspace, auth_headers):
    result = _import(client, workspace.id, auth_headers, "a.pdf", PDF_BYTES, PDF_MIME)

    r = client.get(_url(workspace.id, result["documents"][0]["id"]), headers=auth_headers)

    assert r.status_code == 409
    assert r.json()["code"] == "pdf_preview_unsupported"


def test_disabled_returns_409(client, workspace, auth_headers):
    result = _import(client, workspace.id, auth_headers, "deck.pptx", PPTX_BYTES, PPTX_MIME)

    r = client.get(_url(workspace.id, result["documents"][0]["id"]), headers=auth_headers)

    assert r.status_code == 409
    assert r.json()["code"] == "pdf_preview_disabled"


def test_queued_returns_202_then_ready_200(client, db, workspace, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "PPTX_PDF_CONVERTER_URL", "http://pdf-worker:8100")
    calls = _record_dispatch(monkeypatch)
    result = _import(client, workspace.id, auth_headers, "deck.pptx", PPTX_BYTES, PPTX_MIME)
    doc_id = result["documents"][0]["id"]

    # 导入钩子已入队（且单飞）
    assert len(calls) == 1
    pending = client.get(_url(workspace.id, doc_id), headers=auth_headers)
    assert pending.status_code == 202
    assert pending.json()["status"] == "queued"
    assert pending.headers["Retry-After"] == str(pptx_pdf.RETRY_AFTER_SECONDS)
    assert len(calls) == 1

    doc = db.get(Document, doc_id)
    assert doc is not None
    key_before = doc.asset_file_key
    versions_before = len(doc.versions)
    monkeypatch.setattr(pdf_converter, "convert_pptx_to_pdf", lambda data: PDF_BYTES)
    pptx_pdf.execute_job(db, workspace.id, doc_id, key_before or "")

    ready = client.get(_url(workspace.id, doc_id), headers=auth_headers)
    assert ready.status_code == 200
    assert ready.headers["content-type"] == "application/pdf"
    assert ready.headers["x-content-type-options"] == "nosniff"
    assert ready.content == PDF_BYTES

    cached = client.get(_url(workspace.id, doc_id), headers={**auth_headers, "If-None-Match": ready.headers["etag"]})
    assert cached.status_code == 304

    db.refresh(doc)
    assert doc.content_type == "pptx"
    assert doc.asset_file_key == key_before
    assert len(doc.versions) == versions_before


def test_post_retry_is_idempotent(client, workspace, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "PPTX_PDF_CONVERTER_URL", "http://pdf-worker:8100")
    calls = _record_dispatch(monkeypatch)
    result = _import(client, workspace.id, auth_headers, "deck.pptx", PPTX_BYTES, PPTX_MIME)
    doc_id = result["documents"][0]["id"]
    # 模拟失败后手动重试
    pptx_pdf._set_state(doc_id, pptx_pdf.PdfJobState(pptx_pdf.STATUS_FAILED, "pdf_conversion_failed"))

    r = client.post(_url(workspace.id, doc_id), headers=auth_headers)

    assert r.status_code == 202
    assert r.json()["status"] == "queued"
    assert len(calls) == 2  # 导入 + 手动重试
    again = client.post(_url(workspace.id, doc_id), headers=auth_headers)
    assert again.status_code == 202
    assert len(calls) == 2


def test_too_large_returns_413(client, workspace, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "PPTX_PDF_CONVERTER_URL", "http://pdf-worker:8100")
    monkeypatch.setattr(settings, "PPTX_PDF_MAX_SOURCE_BYTES", 4)
    _record_dispatch(monkeypatch)
    result = _import(client, workspace.id, auth_headers, "deck.pptx", PPTX_BYTES, PPTX_MIME)

    r = client.get(_url(workspace.id, result["documents"][0]["id"]), headers=auth_headers)

    assert r.status_code == 413
    assert r.json()["code"] == "pdf_preview_too_large"


def test_busy_returns_503_with_retry_after(client, workspace, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "PPTX_PDF_CONVERTER_URL", "http://pdf-worker:8100")
    _record_dispatch(monkeypatch, ok=False)
    result = _import(client, workspace.id, auth_headers, "deck.pptx", PPTX_BYTES, PPTX_MIME)

    r = client.get(_url(workspace.id, result["documents"][0]["id"]), headers=auth_headers)

    assert r.status_code == 503
    assert r.json()["code"] == "pdf_preview_busy"
    assert r.headers["Retry-After"] == "5"


def test_failed_returns_422(client, workspace, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "PPTX_PDF_CONVERTER_URL", "http://pdf-worker:8100")
    _record_dispatch(monkeypatch)
    result = _import(client, workspace.id, auth_headers, "deck.pptx", PPTX_BYTES, PPTX_MIME)
    doc_id = result["documents"][0]["id"]
    pptx_pdf._set_state(doc_id, pptx_pdf.PdfJobState(pptx_pdf.STATUS_FAILED, "pdf_conversion_failed"))

    r = client.get(_url(workspace.id, doc_id), headers=auth_headers)

    assert r.status_code == 422
    assert r.json()["code"] == "pdf_conversion_failed"


def test_import_hook_enqueues_only_pptx(client, workspace, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "PPTX_PDF_CONVERTER_URL", "http://pdf-worker:8100")
    calls = _record_dispatch(monkeypatch)

    r = client.post(
        IMPORT.format(ws=workspace.id),
        files=[
            ("files", ("deck.pptx", PPTX_BYTES, PPTX_MIME)),
            ("files", ("a.pdf", PDF_BYTES, PDF_MIME)),
        ],
        data={"paths": ["deck.pptx", "a.pdf"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    assert len(calls) == 1
    assert calls[0][2].endswith(".pptx")


def test_overwrite_invalidates_old_derived_pdf(client, db, workspace, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "PPTX_PDF_CONVERTER_URL", "http://pdf-worker:8100")
    _record_dispatch(monkeypatch)
    result = _import(client, workspace.id, auth_headers, "deck.pptx", PPTX_BYTES, PPTX_MIME)
    doc_id = result["documents"][0]["id"]
    doc = db.get(Document, doc_id)
    assert doc is not None
    old_key = doc.asset_file_key or ""
    cache = pptx_pdf.derived_pdf_path(workspace.id, old_key)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(PDF_BYTES)

    _import(client, workspace.id, auth_headers, "deck.pptx", PPTX_BYTES + b"-v2", PPTX_MIME, conflict="overwrite")

    db.refresh(doc)
    assert doc.asset_file_key != old_key
    assert not cache.exists()
    assert not pptx_pdf.derived_pdf_path(workspace.id, doc.asset_file_key or "").exists()
