"""ADR 0129 P0 判定层测试：缓存路径 / 队列判定 / 执行 / 失效.

与 ADR §8 测试清单的后端判定部分对应；接口层见 ``test_pptx_pdf_preview_api.py``。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import CONTENT_TYPE_MARKDOWN, CONTENT_TYPE_PPTX, Document
from cndb.plugins.documents.services.preview import pdf_converter, pptx_pdf
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
LEGACY_PPT_MIME = "application/vnd.ms-powerpoint"
PPTX_BYTES = b"PK\x03\x04fake-pptx-payload"
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"


@pytest.fixture(autouse=True)
def _pdf_env(monkeypatch, tmp_path):
    """隔离缓存目录与开关，每个用例从干净状态开始."""
    pptx_pdf.reset_state()
    monkeypatch.setattr(settings, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(settings, "PPTX_PDF_CONVERTER_URL", "http://pdf-worker:8100")
    monkeypatch.setattr(settings, "PPTX_PDF_MAX_SOURCE_BYTES", 1024)
    monkeypatch.setattr(settings, "PPTX_PDF_RETRY", 1)
    yield
    pptx_pdf.stop_pptx_pdf_sweeper()
    pptx_pdf.reset_state()


def _workspace(db: Session) -> tuple[Workspace, User]:
    user = User(username=f"pdf_user_{time.time_ns()}", nickname="pdf")
    user.set_password("passw0rd")
    db.add(user)
    db.flush()
    workspace = Workspace(name="PDF 预览", created_by_id=user.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(workspace)
    return workspace, user


def _doc(
    db: Session,
    workspace: Workspace,
    user: User,
    *,
    key: str = "deck.pptx",
    content_type: str = CONTENT_TYPE_PPTX,
    mime: str = PPTX_MIME,
    data: bytes = PPTX_BYTES,
) -> Document:
    path = Path(settings.UPLOAD_DIR) / str(workspace.id) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    doc = Document(
        workspace_id=workspace.id,
        title="deck",
        content_type=content_type,
        asset_file_key=key,
        asset_mime=mime,
        created_by_id=user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _record_dispatch(monkeypatch, *, ok: bool = True) -> list[tuple[int, int, str]]:
    calls: list[tuple[int, int, str]] = []

    def _dispatch(workspace_id: int, doc_id: int, asset_file_key: str) -> bool:
        calls.append((workspace_id, doc_id, asset_file_key))
        return ok

    monkeypatch.setattr(pptx_pdf, "_dispatch", _dispatch)
    return calls


class TestPathAndDecision:
    def test_derived_path_is_cache_scoped(self):
        path = pptx_pdf.derived_pdf_path(7, "abc.pptx")
        assert (
            path == Path(settings.CACHE_DIR) / "document-pdf" / pptx_pdf.CONVERTER_CACHE_VERSION / "7" / "abc.pptx.pdf"
        )

    def test_rejects_illegal_asset_key(self):
        with pytest.raises(ValueError):
            pptx_pdf.derived_pdf_path(1, "../escape.pptx")

    def test_disabled_when_url_empty(self, db, monkeypatch):
        workspace, user = _workspace(db)
        doc = _doc(db, workspace, user)
        monkeypatch.setattr(settings, "PPTX_PDF_CONVERTER_URL", "")

        state = pptx_pdf.ensure_pptx_pdf(workspace.id, doc.id, db=db)

        assert state.status == pptx_pdf.STATUS_DISABLED
        assert state.error_code == "pdf_preview_disabled"

    def test_unsupported_for_non_pptx(self, db):
        workspace, user = _workspace(db)
        doc = _doc(db, workspace, user, content_type=CONTENT_TYPE_MARKDOWN, key="note.md", mime="text/markdown")

        state = pptx_pdf.ensure_pptx_pdf(workspace.id, doc.id, db=db)

        assert state.status == pptx_pdf.STATUS_UNSUPPORTED

    def test_legacy_ppt_is_unsupported(self, db):
        workspace, user = _workspace(db)
        doc = _doc(db, workspace, user, key="old.ppt", mime=LEGACY_PPT_MIME)

        state = pptx_pdf.ensure_pptx_pdf(workspace.id, doc.id, db=db)

        assert state.status == pptx_pdf.STATUS_UNSUPPORTED

    def test_too_large_by_source_bytes(self, db, monkeypatch):
        workspace, user = _workspace(db)
        doc = _doc(db, workspace, user, data=b"x" * 32)
        monkeypatch.setattr(settings, "PPTX_PDF_MAX_SOURCE_BYTES", 8)

        state = pptx_pdf.ensure_pptx_pdf(workspace.id, doc.id, db=db)

        assert state.status == pptx_pdf.STATUS_TOO_LARGE
        assert state.error_code == "pdf_preview_too_large"

    def test_ready_when_cache_exists(self, db):
        workspace, user = _workspace(db)
        doc = _doc(db, workspace, user)
        path = pptx_pdf.derived_pdf_path(workspace.id, doc.asset_file_key or "")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PDF_BYTES)

        state = pptx_pdf.ensure_pptx_pdf(workspace.id, doc.id, db=db)

        assert state.status == pptx_pdf.STATUS_READY

    def test_single_flight(self, db, monkeypatch):
        workspace, user = _workspace(db)
        doc = _doc(db, workspace, user)
        calls = _record_dispatch(monkeypatch)

        first = pptx_pdf.ensure_pptx_pdf(workspace.id, doc.id, db=db)
        second = pptx_pdf.ensure_pptx_pdf(workspace.id, doc.id, db=db)

        assert first.status == second.status == pptx_pdf.STATUS_QUEUED
        assert len(calls) == 1

    def test_busy_when_queue_full(self, db, monkeypatch):
        workspace, user = _workspace(db)
        doc = _doc(db, workspace, user)
        _record_dispatch(monkeypatch, ok=False)

        state = pptx_pdf.ensure_pptx_pdf(workspace.id, doc.id, db=db)

        assert state.status == pptx_pdf.STATUS_BUSY
        # 队列满不留下 queued 状态，下次读取仍可重试
        assert pptx_pdf._current_state(doc.id) is None

    def test_failed_cooldown_and_manual_retry(self, db, monkeypatch):
        workspace, user = _workspace(db)
        doc = _doc(db, workspace, user)
        pptx_pdf._set_state(doc.id, pptx_pdf.PdfJobState(pptx_pdf.STATUS_FAILED, "pdf_conversion_failed"))
        calls = _record_dispatch(monkeypatch)

        cooling = pptx_pdf.ensure_pptx_pdf(workspace.id, doc.id, db=db)
        assert cooling.status == pptx_pdf.STATUS_FAILED
        assert calls == []

        retried = pptx_pdf.ensure_pptx_pdf(workspace.id, doc.id, db=db, retry=True)
        assert retried.status == pptx_pdf.STATUS_QUEUED
        assert len(calls) == 1


class TestExecuteJob:
    def test_success_writes_atomic_pdf(self, db, monkeypatch):
        workspace, user = _workspace(db)
        doc = _doc(db, workspace, user)
        monkeypatch.setattr(pdf_converter, "convert_pptx_to_pdf", lambda data: PDF_BYTES)

        pptx_pdf.execute_job(db, workspace.id, doc.id, doc.asset_file_key or "")

        path = pptx_pdf.derived_pdf_path(workspace.id, doc.asset_file_key or "")
        assert path.read_bytes() == PDF_BYTES
        assert not path.with_name(f"{path.name}.part").exists()
        assert pptx_pdf._current_state(doc.id).status == pptx_pdf.STATUS_READY

    def test_transient_error_retries_once(self, db, monkeypatch):
        workspace, user = _workspace(db)
        doc = _doc(db, workspace, user)
        attempts: list[int] = []

        def _convert(data: bytes) -> bytes:
            attempts.append(1)
            if len(attempts) == 1:
                raise pdf_converter.PdfConversionError("超时", retryable=True)
            return PDF_BYTES

        monkeypatch.setattr(pdf_converter, "convert_pptx_to_pdf", _convert)

        pptx_pdf.execute_job(db, workspace.id, doc.id, doc.asset_file_key or "")

        state = pptx_pdf._current_state(doc.id)
        assert state.status == pptx_pdf.STATUS_READY
        assert state.attempts == 1
        assert len(attempts) == 2

    def test_permanent_error_does_not_retry(self, db, monkeypatch):
        workspace, user = _workspace(db)
        doc = _doc(db, workspace, user)
        attempts: list[int] = []

        def _convert(data: bytes) -> bytes:
            attempts.append(1)
            raise pdf_converter.PdfConversionError("非 PDF", retryable=False)

        monkeypatch.setattr(pdf_converter, "convert_pptx_to_pdf", _convert)

        pptx_pdf.execute_job(db, workspace.id, doc.id, doc.asset_file_key or "")

        assert pptx_pdf._current_state(doc.id).status == pptx_pdf.STATUS_FAILED
        assert len(attempts) == 1

    def test_superseded_asset_key_is_dropped(self, db, monkeypatch):
        workspace, user = _workspace(db)
        doc = _doc(db, workspace, user)
        attempts: list[int] = []
        monkeypatch.setattr(
            pdf_converter,
            "convert_pptx_to_pdf",
            lambda data: attempts.append(1) or PDF_BYTES,
        )

        pptx_pdf.execute_job(db, workspace.id, doc.id, "other-key.pptx")

        assert attempts == []
        assert pptx_pdf._current_state(doc.id).status == pptx_pdf.STATUS_FAILED

    def test_missing_source_fails(self, db, monkeypatch):
        workspace, user = _workspace(db)
        doc = _doc(db, workspace, user)
        (Path(settings.UPLOAD_DIR) / str(workspace.id) / (doc.asset_file_key or "")).unlink()

        pptx_pdf.execute_job(db, workspace.id, doc.id, doc.asset_file_key or "")

        assert pptx_pdf._current_state(doc.id).status == pptx_pdf.STATUS_FAILED

    def test_invalidate_removes_derived_pdf(self):
        path = pptx_pdf.derived_pdf_path(3, "deck.pptx")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PDF_BYTES)

        pptx_pdf.invalidate_pptx_pdf(3, "deck.pptx")

        assert not path.exists()


class TestConverterClient:
    def test_disabled_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "PPTX_PDF_CONVERTER_URL", "")
        with pytest.raises(pdf_converter.PdfConverterDisabledError):
            pdf_converter.convert_pptx_to_pdf(b"data")

    def test_non_pdf_response_is_permanent(self, monkeypatch):
        class _Resp:
            status_code = 200
            content = b"<html>oops</html>"

        class _Client:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, *args, **kwargs):
                return _Resp()

        monkeypatch.setattr(pdf_converter.httpx2, "Client", lambda **kwargs: _Client())

        with pytest.raises(pdf_converter.PdfConversionError) as exc:
            pdf_converter.convert_pptx_to_pdf(b"data")
        assert exc.value.retryable is False

    def test_worker_5xx_is_retryable(self, monkeypatch):
        class _Resp:
            status_code = 503
            content = b""

        class _Client:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, *args, **kwargs):
                return _Resp()

        monkeypatch.setattr(pdf_converter.httpx2, "Client", lambda **kwargs: _Client())

        with pytest.raises(pdf_converter.PdfConversionError) as exc:
            pdf_converter.convert_pptx_to_pdf(b"data")
        assert exc.value.retryable is True

    def test_timeout_is_retryable(self, monkeypatch):
        def _raise(**kwargs):
            raise pdf_converter.httpx2.TimeoutException("timeout")

        monkeypatch.setattr(pdf_converter.httpx2, "Client", _raise)

        with pytest.raises(pdf_converter.PdfConversionError) as exc:
            pdf_converter.convert_pptx_to_pdf(b"data")
        assert exc.value.retryable is True


class TestSweeperAndCache:
    """ADR 0129 P2：低频补扫与衍生件缓存治理."""

    def _write_cache(self, workspace_id: int, asset_file_key: str, *, size: int = len(PDF_BYTES)) -> Path:
        path = pptx_pdf.derived_pdf_path(workspace_id, asset_file_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        return path

    def test_sweep_enqueues_only_missing_pptx(self, db, monkeypatch):
        calls = _record_dispatch(monkeypatch)
        workspace, user = _workspace(db)
        pending = _doc(db, workspace, user, key="pending.pptx")
        _doc(db, workspace, user, key="cached.pptx")
        _doc(db, workspace, user, key="note.md", content_type=CONTENT_TYPE_MARKDOWN, mime="text/markdown")
        self._write_cache(workspace.id, "cached.pptx")

        stats = pptx_pdf.run_sweep(db=db)

        assert stats["queued"] == 1
        assert calls == [(workspace.id, pending.id, "pending.pptx")]

    def test_sweep_skips_when_queue_busy(self, db, monkeypatch):
        calls = _record_dispatch(monkeypatch)
        monkeypatch.setattr(pptx_pdf, "_queue_busy", lambda: True)
        workspace, user = _workspace(db)
        _doc(db, workspace, user)

        stats = pptx_pdf.run_sweep(db=db)

        assert stats["queued"] == 0
        assert calls == []

    def test_sweep_noop_when_disabled(self, db, monkeypatch):
        calls = _record_dispatch(monkeypatch)
        monkeypatch.setattr(settings, "PPTX_PDF_CONVERTER_URL", "")
        workspace, user = _workspace(db)
        _doc(db, workspace, user)

        stats = pptx_pdf.run_sweep(db=db)

        assert stats["queued"] == 0
        assert calls == []

    def test_sweep_skips_legacy_ppt(self, db, monkeypatch):
        calls = _record_dispatch(monkeypatch)
        workspace, user = _workspace(db)
        _doc(db, workspace, user, key="old.ppt", mime=LEGACY_PPT_MIME)

        stats = pptx_pdf.run_sweep(db=db)

        assert stats["queued"] == 0
        assert calls == []

    def test_sweep_respects_batch_limit(self, db, monkeypatch):
        _record_dispatch(monkeypatch)
        monkeypatch.setattr(pptx_pdf, "SWEEP_BATCH_LIMIT", 1)
        workspace, user = _workspace(db)
        _doc(db, workspace, user, key="a.pptx")
        _doc(db, workspace, user, key="b.pptx")

        stats = pptx_pdf.run_sweep(db=db)

        assert stats["queued"] == 1

    def test_cleanup_removes_expired_cache(self, db):
        workspace, user = _workspace(db)
        _doc(db, workspace, user, key="ttl.pptx")
        path = self._write_cache(workspace.id, "ttl.pptx")
        old = time.time() - 31 * 86400
        os.utime(path, (old, old))

        stats = pptx_pdf.cleanup_cache(db=db)

        assert stats["removed_ttl"] == 1
        assert not path.exists()

    def test_cleanup_removes_orphan_cache(self, db):
        workspace, _ = _workspace(db)
        path = self._write_cache(workspace.id, "gone.pptx")

        stats = pptx_pdf.cleanup_cache(db=db)

        assert stats["removed_orphan"] == 1
        assert not path.exists()

    def test_cleanup_evicts_oldest_when_over_capacity(self, db, monkeypatch):
        workspace, user = _workspace(db)
        _doc(db, workspace, user, key="old.pptx")
        _doc(db, workspace, user, key="new.pptx")
        old_path = self._write_cache(workspace.id, "old.pptx", size=10)
        new_path = self._write_cache(workspace.id, "new.pptx", size=10)
        now = time.time()
        os.utime(old_path, (now - 1000, now - 1000))
        os.utime(new_path, (now, now))
        monkeypatch.setattr(settings, "PPTX_PDF_CACHE_MAX_BYTES", 10)

        stats = pptx_pdf.cleanup_cache(db=db)

        assert stats["removed_capacity"] == 1
        assert not old_path.exists()
        assert new_path.exists()

    def test_cleanup_ignores_missing_cache_dir(self, db):
        assert pptx_pdf.cleanup_cache(db=db)["scanned"] == 0

    def test_sweeper_not_started_when_interval_zero(self, monkeypatch):
        monkeypatch.setattr(settings, "PPTX_PDF_SWEEP_INTERVAL_SECONDS", 0)

        pptx_pdf.start_pptx_pdf_sweeper()

        assert pptx_pdf._sweeper.thread is None

    def test_sweeper_not_started_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "PPTX_PDF_CONVERTER_URL", "")

        pptx_pdf.start_pptx_pdf_sweeper()

        assert pptx_pdf._sweeper.thread is None

    def test_sweeper_start_and_stop(self, monkeypatch):
        monkeypatch.setattr(settings, "PPTX_PDF_SWEEP_INTERVAL_SECONDS", 3600)
        monkeypatch.setattr(settings, "PPTX_PDF_SWEEP_STARTUP_DELAY_SECONDS", 3600)

        pptx_pdf.start_pptx_pdf_sweeper()
        thread = pptx_pdf._sweeper.thread
        assert thread is not None
        assert thread.is_alive()

        pptx_pdf.stop_pptx_pdf_sweeper()

        assert not thread.is_alive()
        assert pptx_pdf._sweeper.thread is None
