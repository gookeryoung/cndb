"""PPTX → PDF 衍生预览件：缓存路径 / 进程内队列 / 状态（ADR 0129 P0）.

设计口径（与 ADR 0129 §1-§2 对应）：

- **零迁移、零新表**：任务状态只在进程内，缓存文件是否存在是唯一权威事实；
- **可丢弃**：衍生 PDF 写入 ``CACHE_DIR/document-pdf/<版本>/<工作区>/<原件 key>.pdf``，
  不计配额、不进备份，缺失可随时重建；
- **单飞 + 有界**：同一文档同时最多一个任务，全局队列与并发都有硬上限；
- **默认关闭**：``PPTX_PDF_CONVERTER_URL`` 为空时所有判定直接返回 ``disabled``；
- **原子写入**：先写同目录 ``.part`` 再 ``os.replace``，避免读到半成品。

低版本 Python 兼容性与线程模型：单 daemon 线程 + ``queue.Queue``，首次投递时惰性启动。
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.core.database import SessionLocal
from cndb.core.errors import BadRequestError
from cndb.plugins.documents.models import CONTENT_TYPE_PPTX, Document
from cndb.plugins.files.services import resolve_workspace_file

from . import pdf_converter

logger = logging.getLogger(__name__)

#: 缓存版本：LibreOffice 大版本或转换参数变化时递增，旧目录由补扫按 TTL 清理
CONVERTER_CACHE_VERSION = "lo-1"
#: CACHE_DIR 下的衍生件子目录
CACHE_SUBDIR = "document-pdf"
#: 失败态冷却时间（秒）：冷却内读取不再反复入队
FAILED_COOLDOWN_SECONDS = 600
#: 202 响应建议客户端的轮询间隔（秒）
RETRY_AFTER_SECONDS = 2
#: 每轮补扫最多入队的文档数：低频治理不能把队列瞬间打满
SWEEP_BATCH_LIMIT = 50

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_DISABLED = "disabled"
STATUS_UNSUPPORTED = "unsupported"
STATUS_TOO_LARGE = "too_large"
STATUS_BUSY = "busy"

#: 旧版二进制 .ppt（不可由 LibreOffice 稳定转换，前端保持客户端能力判定）
LEGACY_PPT_MIME = "application/vnd.ms-powerpoint"


@dataclass
class PdfJobState:
    """一次衍生件判定 / 任务的状态快照."""

    status: str
    error_code: str | None = None
    attempts: int = 0
    updated_at: float = field(default_factory=time.monotonic)


# ── 进程内状态与队列 ──

_jobs: dict[int, PdfJobState] = {}
_lock = threading.RLock()


@dataclass
class _WorkerRuntime:
    """惰性创建的队列与消费者（放在可变对象里，避免模块级 global）."""

    queue: queue.Queue[tuple[int, int, str]] | None = None
    worker: threading.Thread | None = None


_runtime = _WorkerRuntime()


@dataclass
class _SweeperRuntime:
    """低频补扫线程（启动延迟 / 停机停止）."""

    thread: threading.Thread | None = None
    stop_event: threading.Event | None = None


_sweeper = _SweeperRuntime()


def reset_state() -> None:
    """清空进程内任务状态（进程重启等价；测试与运维排障使用）."""
    with _lock:
        _jobs.clear()


def derived_pdf_path(workspace_id: int, asset_file_key: str) -> Path:
    """衍生 PDF 的唯一路径（含缓存版本 / 工作区 / 原件 key）."""
    if (
        not asset_file_key
        or len(asset_file_key) > 255
        or ".." in asset_file_key
        or "/" in asset_file_key
        or "\\" in asset_file_key
    ):
        raise ValueError("非法的原件标识符")
    return (
        Path(settings.CACHE_DIR) / CACHE_SUBDIR / CONVERTER_CACHE_VERSION / str(workspace_id) / f"{asset_file_key}.pdf"
    )


def _cache_ready(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:  # pragma: no cover - 权限 / 竞态删除
        return False


def _set_state(doc_id: int, state: PdfJobState) -> PdfJobState:
    state.updated_at = time.monotonic()
    with _lock:
        _jobs[doc_id] = state
    return state


def _current_state(doc_id: int) -> PdfJobState | None:
    with _lock:
        return _jobs.get(doc_id)


def _queue_instance() -> queue.Queue[tuple[int, int, str]]:
    """惰性创建队列并启动唯一的 daemon 消费者."""
    with _lock:
        if _runtime.queue is None:
            _runtime.queue = queue.Queue(maxsize=max(settings.PPTX_PDF_QUEUE_MAX, 1))
        if _runtime.worker is None or not _runtime.worker.is_alive():
            _runtime.worker = threading.Thread(target=_worker_loop, name="pptx-pdf-worker", daemon=True)
            _runtime.worker.start()
        return _runtime.queue


def _dispatch(workspace_id: int, doc_id: int, asset_file_key: str) -> bool:
    """把任务放入队列；队列已满返回 False（调用方映射 503）."""
    try:
        _queue_instance().put_nowait((workspace_id, doc_id, asset_file_key))
    except queue.Full:
        return False
    return True


def _worker_loop() -> None:  # pragma: no cover - 常驻线程循环
    """单线程消费者：逐个执行转换任务，异常不退出线程."""
    while True:
        workspace_id, doc_id, asset_file_key = _queue_instance().get()
        try:
            execute_queued_job(workspace_id, doc_id, asset_file_key)
        except Exception:
            logger.exception("PPTX PDF 任务异常 doc_id=%s workspace_id=%s", doc_id, workspace_id)
        finally:
            _queue_instance().task_done()


def execute_queued_job(workspace_id: int, doc_id: int, asset_file_key: str) -> None:
    """后台线程入口：每个任务独立 Session，避免跨线程共享事务."""
    session = SessionLocal()
    try:
        execute_job(session, workspace_id, doc_id, asset_file_key)
    finally:
        session.close()


# ── 判定与入队 ──


def ensure_pptx_pdf(
    workspace_id: int,
    doc_id: int,
    *,
    retry: bool = False,
    db: Session | None = None,
) -> PdfJobState:
    """读取路径的判定入口：负责全部前置检查并保证最多一次入队.

    判定顺序与 ADR 0129 §2 一致：关闭 → 类型 / 旧版 → 超限 → 缓存命中 →
    进行中 → 队列满 → 失败冷却 → 入队。
    """
    return _submit(workspace_id, doc_id, retry=retry, db=db)


def enqueue_pptx_pdf(
    workspace_id: int,
    doc_id: int,
    *,
    retry: bool = False,
    db: Session | None = None,
) -> PdfJobState:
    """导入后 / 补扫的入队入口（与读取路径共用同一判定）."""
    return _submit(workspace_id, doc_id, retry=retry, db=db)


def _submit(
    workspace_id: int,
    doc_id: int,
    *,
    retry: bool,
    db: Session | None,
) -> PdfJobState:
    if not pdf_converter.is_configured():
        return PdfJobState(STATUS_DISABLED, "pdf_preview_disabled")

    session = db if db is not None else SessionLocal()
    owns_session = db is None
    try:
        doc = session.get(Document, doc_id)
        if doc is None or doc.workspace_id != workspace_id or doc.is_folder:
            return PdfJobState(STATUS_FAILED, "pdf_conversion_failed")
        if doc.content_type != CONTENT_TYPE_PPTX or doc.asset_mime == LEGACY_PPT_MIME or not doc.asset_file_key:
            return PdfJobState(STATUS_UNSUPPORTED, "pdf_preview_unsupported")
        try:
            source = resolve_workspace_file(workspace_id, doc.asset_file_key)
        except BadRequestError:
            return PdfJobState(STATUS_FAILED, "pdf_conversion_failed")
        if not source.is_file():
            return PdfJobState(STATUS_FAILED, "pdf_conversion_failed")
        if source.stat().st_size > settings.PPTX_PDF_MAX_SOURCE_BYTES:
            return PdfJobState(STATUS_TOO_LARGE, "pdf_preview_too_large")
        asset_file_key = doc.asset_file_key
    finally:
        if owns_session:
            session.close()

    try:
        path = derived_pdf_path(workspace_id, asset_file_key)
    except ValueError:
        return PdfJobState(STATUS_FAILED, "pdf_conversion_failed")
    if _cache_ready(path):
        return _set_state(doc_id, PdfJobState(STATUS_READY))

    with _lock:
        current = _jobs.get(doc_id)
        if current is not None and current.status in (STATUS_QUEUED, STATUS_RUNNING):
            return current
        if (
            current is not None
            and current.status == STATUS_FAILED
            and not retry
            and (time.monotonic() - current.updated_at) < FAILED_COOLDOWN_SECONDS
        ):
            return current
        queued = PdfJobState(STATUS_QUEUED)
        _jobs[doc_id] = queued

    if not _dispatch(workspace_id, doc_id, asset_file_key):
        with _lock:
            if _jobs.get(doc_id) is queued:
                _jobs.pop(doc_id, None)
        return PdfJobState(STATUS_BUSY, "pdf_preview_busy")
    return queued


# ── 执行 ──


def execute_job(db: Session, workspace_id: int, doc_id: int, asset_file_key: str) -> None:
    """执行一次转换（可被后台线程或测试直接调用）.

    入队后原件可能被覆盖导入替换（``asset_file_key`` 变化），执行前必须重新比对；
    不匹配说明已有更新的任务，直接丢弃本次结果。
    """
    doc = db.get(Document, doc_id)
    if (
        doc is None
        or doc.workspace_id != workspace_id
        or doc.content_type != CONTENT_TYPE_PPTX
        or doc.asset_file_key != asset_file_key
    ):
        _set_state(doc_id, PdfJobState(STATUS_FAILED, "pdf_conversion_failed"))
        return

    started = time.monotonic()
    attempt = 0
    while True:
        _set_state(doc_id, PdfJobState(STATUS_RUNNING, attempts=attempt))
        try:
            source = resolve_workspace_file(workspace_id, asset_file_key)
            data = source.read_bytes()
            pdf_bytes = pdf_converter.convert_pptx_to_pdf(data)
            _atomic_write(derived_pdf_path(workspace_id, asset_file_key), pdf_bytes)
        except (pdf_converter.PdfConversionError, pdf_converter.PdfConverterDisabledError) as exc:
            retryable = getattr(exc, "retryable", False)
            if retryable and attempt < settings.PPTX_PDF_RETRY:
                attempt += 1
                continue
            _set_state(doc_id, PdfJobState(STATUS_FAILED, "pdf_conversion_failed", attempts=attempt))
            logger.warning(
                "pptx_pdf result=failed error_code=pdf_conversion_failed doc_id=%s workspace_id=%s "
                "asset_file_key=%s duration_ms=%s attempts=%s error=%s",
                doc_id,
                workspace_id,
                asset_file_key,
                int((time.monotonic() - started) * 1000),
                attempt,
                getattr(exc, "detail", str(exc)),
            )
            return
        except (OSError, ValueError, BadRequestError) as exc:
            _set_state(doc_id, PdfJobState(STATUS_FAILED, "pdf_conversion_failed", attempts=attempt))
            logger.warning(
                "pptx_pdf result=failed error_code=pdf_conversion_failed doc_id=%s workspace_id=%s "
                "duration_ms=%s error=%s",
                doc_id,
                workspace_id,
                int((time.monotonic() - started) * 1000),
                exc,
            )
            return

        _set_state(doc_id, PdfJobState(STATUS_READY, attempts=attempt))
        logger.info(
            "pptx_pdf result=ready doc_id=%s workspace_id=%s asset_file_key=%s duration_ms=%s attempts=%s",
            doc_id,
            workspace_id,
            asset_file_key,
            int((time.monotonic() - started) * 1000),
            attempt,
        )
        return


def _atomic_write(path: Path, data: bytes) -> None:
    """先写 ``.part`` 再原子替换，读取方永远看不到半成品."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.part")
    try:
        temp.write_bytes(data)
        temp.replace(path)
    finally:
        with suppress(OSError):
            temp.unlink(missing_ok=True)


def invalidate_pptx_pdf(workspace_id: int, asset_file_key: str) -> None:
    """失效某个原件的衍生缓存（覆盖导入 / 彻底删除时同步调用）."""
    try:
        derived_pdf_path(workspace_id, asset_file_key).unlink(missing_ok=True)
    except (OSError, ValueError):
        return


# ── 低频补扫与缓存治理（ADR 0129 P2） ──


def _queue_busy() -> bool:
    """队列里还有待执行任务时补扫不投递，避免和用户首次打开抢队列."""
    with _lock:
        instance = _runtime.queue
    return instance is not None and not instance.empty()


def _remove_quietly(path: Path) -> bool:
    try:
        path.unlink()
    except OSError:
        return False
    return True


def _split_cache_path(root: Path, path: Path) -> tuple[str | None, int | None, str]:
    """把 ``<版本>/<工作区>/<key>.pdf`` 拆回来；层级不符返回空值（不参与孤儿判定）."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None, None, ""
    if len(parts) != 3:
        return None, None, ""
    version, workspace_raw, filename = parts
    try:
        workspace_id = int(workspace_raw)
    except ValueError:
        return None, None, ""
    key = filename[: -len(".pdf")] if filename.endswith(".pdf") else filename
    return version, workspace_id, key


def _accepted_asset_keys(db: Session | None) -> set[tuple[int, str]]:
    """数据库里仍存在的 (workspace_id, asset_file_key) 集合.

    含回收站文档：软删除只改状态、原件仍在，恢复后缓存可直接复用。
    """
    session = db if db is not None else SessionLocal()
    owns_session = db is None
    try:
        rows = session.execute(
            select(Document.workspace_id, Document.asset_file_key).where(Document.asset_file_key.is_not(None))
        ).all()
        return {(workspace_id, key) for workspace_id, key in rows}
    finally:
        if owns_session:
            session.close()


def cleanup_cache(*, now: float | None = None, db: Session | None = None) -> dict[str, int]:
    """清理衍生件缓存：TTL → 孤儿（原件已不存在）→ 全局容量淘汰.

    顺序固定：先删过期 / 孤儿，再按 mtime 从旧到新淘汰到容量上限以内。
    所有失败都静默（缓存可重建，治理不能影响读取链路）。
    """
    stats = {"scanned": 0, "removed_ttl": 0, "removed_orphan": 0, "removed_capacity": 0}
    root = Path(settings.CACHE_DIR) / CACHE_SUBDIR
    if not root.is_dir():
        return stats

    current = time.time() if now is None else now
    ttl_days = settings.PPTX_PDF_CACHE_TTL_DAYS
    ttl_seconds = ttl_days * 86400 if ttl_days > 0 else 0
    accepted = _accepted_asset_keys(db)
    kept: list[tuple[float, int, Path]] = []

    for path in root.rglob("*.pdf"):
        try:
            meta = path.stat()
        except OSError:
            continue
        stats["scanned"] += 1
        if ttl_seconds and current - meta.st_mtime > ttl_seconds:
            if _remove_quietly(path):
                stats["removed_ttl"] += 1
            continue
        version, workspace_id, key = _split_cache_path(root, path)
        if version == CONVERTER_CACHE_VERSION and workspace_id is not None and (workspace_id, key) not in accepted:
            if _remove_quietly(path):
                stats["removed_orphan"] += 1
            continue
        kept.append((meta.st_mtime, meta.st_size, path))

    limit = settings.PPTX_PDF_CACHE_MAX_BYTES
    if limit > 0:
        total = sum(size for _, size, _ in kept)
        for _, size, path in sorted(kept, key=lambda item: item[0]):
            if total <= limit:
                break
            if _remove_quietly(path):
                total -= size
                stats["removed_capacity"] += 1
    return stats


def run_sweep(db: Session | None = None, *, now: float | None = None) -> dict[str, int]:
    """执行一轮补扫：先治理缓存，队列空闲时给缺缓存的 PPTX 补入队.

    只处理「未删除、非旧版 .ppt、缓存缺失、当前没有排队 / 执行任务」的文档，
    每轮最多 ``SWEEP_BATCH_LIMIT`` 个，避免后台任务抢占前台首开。
    """
    stats = {"queued": 0, "scanned": 0, "removed_ttl": 0, "removed_orphan": 0, "removed_capacity": 0}
    if not pdf_converter.is_configured():
        return stats

    started = time.monotonic()
    session = db if db is not None else SessionLocal()
    owns_session = db is None
    try:
        stats.update(cleanup_cache(now=now, db=session))
        if not _queue_busy():
            rows = session.execute(
                select(
                    Document.id,
                    Document.workspace_id,
                    Document.asset_file_key,
                    Document.asset_mime,
                )
                .where(
                    Document.content_type == CONTENT_TYPE_PPTX,
                    Document.is_folder.is_(False),
                    Document.deleted_at.is_(None),
                    Document.asset_file_key.is_not(None),
                )
                .order_by(Document.id.asc())
            ).all()
            for doc_id, workspace_id, asset_file_key, asset_mime in rows:
                if stats["queued"] >= SWEEP_BATCH_LIMIT:
                    break
                if not asset_file_key or asset_mime == LEGACY_PPT_MIME:
                    continue
                try:
                    path = derived_pdf_path(workspace_id, asset_file_key)
                except ValueError:
                    continue
                if _cache_ready(path):
                    continue
                with _lock:
                    state = _jobs.get(doc_id)
                if state is not None and state.status in (STATUS_QUEUED, STATUS_RUNNING):
                    continue
                if enqueue_pptx_pdf(workspace_id, doc_id, db=session).status == STATUS_QUEUED:
                    stats["queued"] += 1
    finally:
        if owns_session:
            session.close()

    logger.info(
        "pptx_pdf sweep result=ok queued=%s scanned=%s removed_ttl=%s removed_orphan=%s "
        "removed_capacity=%s duration_ms=%s",
        stats["queued"],
        stats["scanned"],
        stats["removed_ttl"],
        stats["removed_orphan"],
        stats["removed_capacity"],
        int((time.monotonic() - started) * 1000),
    )
    return stats


def _sweeper_loop(stop_event: threading.Event) -> None:
    """启动延迟 → 周期补扫；``stop_event`` 置位后立刻退出（停机 / 测试）."""
    delay = max(settings.PPTX_PDF_SWEEP_STARTUP_DELAY_SECONDS, 0)
    if stop_event.wait(delay):
        return
    while not stop_event.is_set():
        try:
            run_sweep()
        except Exception:
            logger.exception("pptx_pdf sweep result=error")
        interval = settings.PPTX_PDF_SWEEP_INTERVAL_SECONDS
        if interval <= 0 or stop_event.wait(interval):
            return


def start_pptx_pdf_sweeper() -> None:
    """启动低频补扫线程；转换器未配置或周期 <= 0 时不启动（桌面端 / 单机）."""
    if not pdf_converter.is_configured():
        logger.info("pptx_pdf sweep 跳过：未配置转换器")
        return
    interval = settings.PPTX_PDF_SWEEP_INTERVAL_SECONDS
    if interval <= 0:
        logger.info("pptx_pdf sweep 跳过：周期为 0")
        return
    with _lock:
        if _sweeper.thread is not None and _sweeper.thread.is_alive():
            return
        stop_event = threading.Event()
        thread = threading.Thread(target=_sweeper_loop, args=(stop_event,), name="pptx-pdf-sweeper", daemon=True)
        _sweeper.stop_event = stop_event
        _sweeper.thread = thread
        thread.start()
    logger.info(
        "pptx_pdf sweep 已启动 interval=%ss startup_delay=%ss",
        interval,
        settings.PPTX_PDF_SWEEP_STARTUP_DELAY_SECONDS,
    )


def stop_pptx_pdf_sweeper() -> None:
    """停止补扫线程（应用停机时调用；可重复调用）."""
    with _lock:
        stop_event = _sweeper.stop_event
        thread = _sweeper.thread
        _sweeper.stop_event = None
        _sweeper.thread = None
    if stop_event is not None:
        stop_event.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)


__all__ = [
    "CONVERTER_CACHE_VERSION",
    "FAILED_COOLDOWN_SECONDS",
    "STATUS_BUSY",
    "STATUS_DISABLED",
    "STATUS_FAILED",
    "STATUS_QUEUED",
    "STATUS_READY",
    "STATUS_RUNNING",
    "STATUS_TOO_LARGE",
    "STATUS_UNSUPPORTED",
    "SWEEP_BATCH_LIMIT",
    "PdfJobState",
    "cleanup_cache",
    "derived_pdf_path",
    "enqueue_pptx_pdf",
    "ensure_pptx_pdf",
    "execute_job",
    "execute_queued_job",
    "invalidate_pptx_pdf",
    "reset_state",
    "run_sweep",
    "start_pptx_pdf_sweeper",
    "stop_pptx_pdf_sweeper",
]
