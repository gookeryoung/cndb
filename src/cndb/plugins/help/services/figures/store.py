"""图示快照存储 + 后台定期重建（ADR 0030 §3）.

三层保障，按「先快后新」排序：

1. **磁盘快照**：`CACHE_DIR/help-figures/<key>.svg` + `index.json`。进程重启后
   首次访问直接读盘，不必重新构建（管理台 / 帮助首屏秒开）。
2. **请求期指纹校验**：每个请求都拿当前指纹与快照比对，不一致**立即重建**
   （改代码、改 CSV 后第一次访问就是新的，不用等定时轮次）。
3. **后台定期轮次**：`HELP_FIGURES_INTERVAL_SECONDS` 周期全量重建一次，
   保证长期无人访问的图也不会停留在旧版本，也让「图示更新时间」可信。

线程模型与 `core/storage_refresh.py` 一致：单守护线程 + `Event` 唤醒，
关闭时先置停止信号再 join，不阻塞进程退出。
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from cndb.core.config import settings
from cndb.plugins.help.services.figures.registry import FIGURE_SPECS, FigureSpec, find_spec

logger = logging.getLogger(__name__)

CACHE_SUBDIR = "help-figures"
_INDEX_VERSION = 1


class FigureMeta(TypedDict):
    """清单接口返回的图示元信息（与 `schemas.HelpFigureResponse` 同构）."""

    key: str
    title: str
    caption: str
    section: str
    fingerprint: str
    generatedAt: float


@dataclass(frozen=True)
class RenderedFigure:
    """一张已生成并落盘的图示."""

    key: str
    svg: str
    fingerprint: str
    generated_at: float


class FigureStore:
    """图示快照仓库（进程内单实例，线程安全）."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, RenderedFigure] = {}
        self._loaded = False
        self._cache_dir = cache_dir

    # ── 路径 ──

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir or (settings.CACHE_DIR / CACHE_SUBDIR)

    def _index_path(self) -> Path:
        return self.cache_dir / "index.json"

    def _svg_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.svg"

    # ── 磁盘快照 ──

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        index_path = self._index_path()
        if not index_path.is_file():
            return
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            for item in payload.get("items", []):
                key = item.get("key", "")
                spec = find_spec(key)
                if spec is None:
                    continue  # 清单里已删除的图示，忽略旧快照
                svg_path = self._svg_path(key)
                if not svg_path.is_file():
                    continue
                self._records[key] = RenderedFigure(
                    key=key,
                    svg=svg_path.read_text(encoding="utf-8"),
                    fingerprint=str(item.get("fingerprint", "")),
                    generated_at=float(item.get("generatedAt", 0.0)),
                )
        except (OSError, ValueError, TypeError):
            logger.warning("帮助图示快照索引不可读，忽略并重建", exc_info=True)

    def _write_disk(self, record: RenderedFigure) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._svg_path(record.key).write_text(record.svg, encoding="utf-8")
            payload = {
                "version": _INDEX_VERSION,
                "items": [
                    {
                        "key": item.key,
                        "fingerprint": item.fingerprint,
                        "generatedAt": item.generated_at,
                    }
                    for item in sorted(self._records.values(), key=lambda item: item.key)
                ],
            }
            self._index_path().write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            # 只读文件系统 / 磁盘满：退化为纯内存快照，不影响接口可用
            logger.warning("帮助图示快照写入失败（退化为内存快照）", exc_info=True)

    # ── 读写 ──

    def get(self, key: str, *, force: bool = False) -> RenderedFigure | None:
        """取一张图；指纹不一致或 `force` 时重建。未知 key 返回 None."""
        spec = find_spec(key)
        if spec is None:
            return None
        with self._lock:
            self._ensure_loaded()
            fingerprint = spec.fingerprint()
            cached = self._records.get(key)
            if cached is not None and not force and cached.fingerprint == fingerprint:
                return cached
            return self._render(spec, fingerprint)

    def _render(self, spec: FigureSpec, fingerprint: str) -> RenderedFigure:
        try:
            svg = spec.build()
        except Exception:
            # 单张图失败不能拖垮整个清单：回退到旧快照（若有），否则抛给上层记 500
            stale = self._records.get(spec.key)
            logger.warning("帮助图示 %s 生成失败", spec.key, exc_info=True)
            if stale is not None:
                return stale
            raise
        record = RenderedFigure(
            key=spec.key,
            svg=svg,
            fingerprint=fingerprint,
            generated_at=time.time(),
        )
        self._records[spec.key] = record
        self._write_disk(record)
        logger.debug("帮助图示已重建：%s（指纹 %s）", spec.key, fingerprint)
        return record

    def list_meta(self) -> list[FigureMeta]:
        """全部图示的元信息（顺带把过期项重建，保证前端拿到的指纹与内容一致）."""
        items: list[FigureMeta] = []
        for spec in FIGURE_SPECS:
            record = self.get(spec.key)
            items.append(
                {
                    "key": spec.key,
                    "title": spec.title,
                    "caption": spec.caption,
                    "section": spec.section,
                    "fingerprint": record.fingerprint if record else "",
                    "generatedAt": record.generated_at if record else 0.0,
                }
            )
        return items

    def refresh(self, *, force: bool = False) -> int:
        """重建全部图示，返回实际重建张数；单张失败不影响其余."""
        rebuilt = 0
        for spec in FIGURE_SPECS:
            with self._lock:
                self._ensure_loaded()
                before = self._records.get(spec.key)
                fingerprint = spec.fingerprint()
                if before is not None and not force and before.fingerprint == fingerprint:
                    continue
                try:
                    self._render(spec, fingerprint)
                except Exception:
                    logger.warning("帮助图示 %s 重建失败（跳过）", spec.key, exc_info=True)
                    continue
                rebuilt += 1
        return rebuilt

    def reset(self) -> None:
        """清空内存与磁盘快照（仅供测试与排障）."""
        with self._lock:
            self._records.clear()
            self._loaded = False
            for spec in FIGURE_SPECS:
                with contextlib.suppress(OSError):
                    self._svg_path(spec.key).unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                self._index_path().unlink(missing_ok=True)


class FigureRefresher:
    """后台定期重建线程（进程内单例）."""

    def __init__(self, *, interval_seconds: int, startup_delay_seconds: int, store: FigureStore) -> None:
        self._interval = max(0, int(interval_seconds))
        self._startup_delay = max(0, int(startup_delay_seconds))
        self._store = store
        self._wakeup = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        """启动后台线程（幂等）；已运行返回 False."""
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="cndb-help-figures", daemon=True)
        self._thread.start()
        logger.info(
            "帮助图示刷新线程已启动（周期 %ss，首轮延迟 %ss）",
            self._interval or "关闭",
            self._startup_delay,
        )
        return True

    def stop(self, timeout: float = 5.0) -> None:
        """停止后台线程（幂等）."""
        thread = self._thread
        self._stop.set()
        self._wakeup.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning("帮助图示刷新线程未在 %.1fs 内退出（守护线程，随进程结束）", timeout)
        self._thread = None
        logger.info("帮助图示刷新线程已停止")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wake(self) -> None:
        """立即触发一轮（手动刷新后调用，让定时轮次重新计时）."""
        self._wakeup.set()

    def _run(self) -> None:
        if self._startup_delay and self._stop.wait(self._startup_delay):
            return
        while not self._stop.is_set():
            try:
                rebuilt = self._store.refresh()
                if rebuilt:
                    logger.info("帮助图示后台重建完成：%d 张", rebuilt)
            except Exception:  # pragma: no cover - 线程不能因单轮失败退出
                logger.warning("帮助图示后台重建轮次失败（等下一轮）", exc_info=True)
            self._wakeup.wait(self._interval if self._interval > 0 else None)
            self._wakeup.clear()


class _Registry:
    """进程内句柄（用实例属性代替模块级 ``global``）."""

    def __init__(self) -> None:
        self.store = FigureStore()
        self.refresher: FigureRefresher | None = None


_registry = _Registry()


def get_figure_store() -> FigureStore:
    """当前进程的图示仓库."""
    return _registry.store


def get_figure_refresher() -> FigureRefresher | None:
    """当前进程的刷新线程（未启动时为 None）."""
    return _registry.refresher


def start_figure_refresher() -> FigureRefresher | None:
    """按配置启动刷新线程（`HELP_FIGURES_ENABLED=False` 时跳过）."""
    if not settings.HELP_FIGURES_ENABLED:
        logger.debug("帮助图示后台刷新已关闭（HELP_FIGURES_ENABLED=False）")
        return None
    current = _registry.refresher
    if current is not None and current.running:
        return current
    _registry.refresher = FigureRefresher(
        interval_seconds=settings.HELP_FIGURES_INTERVAL_SECONDS,
        startup_delay_seconds=settings.HELP_FIGURES_STARTUP_DELAY_SECONDS,
        store=get_figure_store(),
    )
    _registry.refresher.start()
    return _registry.refresher


def stop_figure_refresher(timeout: float = 5.0) -> None:
    """停止刷新线程（应用关闭时调用）."""
    current = _registry.refresher
    _registry.refresher = None
    if current is not None:
        current.stop(timeout=timeout)


__all__ = [
    "CACHE_SUBDIR",
    "FigureMeta",
    "FigureRefresher",
    "FigureStore",
    "RenderedFigure",
    "get_figure_refresher",
    "get_figure_store",
    "start_figure_refresher",
    "stop_figure_refresher",
]
