"""FTS 索引一致性后台校验 / 重建线程（需求 0170）.

FTS5 无 DB 触发器，写路径靠应用层同步（content.py 的 sync_fts / _sync_fts_delete）。
任一条写路径遗漏或异常会造成索引漂移。本线程按周期只读校验，发现不一致时
全量重建主表 + trigram 影子表，使漂移自愈。

线程模型（与 storage_refresh / pptx_pdf sweeper 同范式）：
- 单守护线程 + ``threading.Event``；启动延迟后每轮校验，周期 0 关闭定时轮次；
- 校验只读、重建只改 FTS 虚拟表，不改业务数据（H38）；
- 单轮失败只记日志，不影响下一轮；stop() 先唤醒再 join，超时不阻塞退出。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from sqlalchemy.orm import Session

from cndb.core.config import settings

logger = logging.getLogger(__name__)

# 周期 / 首轮延迟由 Settings 提供；默认 6 小时一轮，启动后 5 分钟首轮。
# FTS_VERIFY_ENABLED=0 关闭线程（测试/桌面端用，避免独立 SessionLocal 连真实库污染内存测试库）。
_INTERVAL_SECONDS = settings.FTS_VERIFY_INTERVAL_SECONDS
_STARTUP_DELAY_SECONDS = settings.FTS_VERIFY_STARTUP_DELAY_SECONDS


class _FtsRefresher:
    def __init__(self, *, interval_seconds: int, startup_delay_seconds: int) -> None:
        self._interval = max(0, int(interval_seconds))
        self._delay = max(0, int(startup_delay_seconds))
        self._stop = threading.Event()
        self._wakeup = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if not settings.FTS_VERIFY_ENABLED:
            logger.info("FTS 校验线程已禁用（FTS_VERIFY_ENABLED=0）")
            return False
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="cndb-fts-verify", daemon=True)
        self._thread.start()
        logger.info("FTS 校验线程已启动（周期 %ss，首轮延迟 %ss）", self._interval or "关闭", self._delay)
        return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wakeup.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning("FTS 校验线程未在 %.1fs 内退出（守护线程，随进程结束）", timeout)
        self._thread = None
        logger.info("FTS 校验线程已停止")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        if self._delay and self._wakeup.wait(timeout=self._delay):
            return
        while not self._stop.is_set():
            try:
                self.verify_once()
            except Exception:  # 后台线程不得因单轮失败退出
                logger.warning("FTS 一致性校验轮次失败（忽略，下一轮重试）", exc_info=True)
            if self._interval <= 0:
                break
            if self._wakeup.wait(timeout=self._interval):
                self._wakeup.clear()

    def verify_once(self) -> dict[str, Any]:
        """执行一轮校验，不一致时重建；返回报告（含 rebuilt 字段）."""
        from cndb.core.database import SessionLocal
        from cndb.plugins.documents.services.search import (
            ensure_fts_schema,
            rebuild_fts_index,
            verify_fts_index,
        )

        db: Session = SessionLocal()
        try:
            ensure_fts_schema(db)
            report = verify_fts_index(db)
            payload = report.as_dict()
            payload["rebuilt"] = 0
            if not report.consistent:
                logger.warning("检测到 FTS 索引漂移：%s，触发全量重建", payload["counts"])
                payload["rebuilt"] = rebuild_fts_index(db)
                logger.info("FTS 索引重建完成：%d 篇文档", payload["rebuilt"])
            return payload
        finally:
            db.close()


_refresher = _FtsRefresher(
    interval_seconds=_INTERVAL_SECONDS,
    startup_delay_seconds=_STARTUP_DELAY_SECONDS,
)


def start_fts_refresher() -> bool:
    return _refresher.start()


def stop_fts_refresher() -> None:
    _refresher.stop()


def get_fts_refresher() -> _FtsRefresher:
    return _refresher


__all__ = ["get_fts_refresher", "start_fts_refresher", "stop_fts_refresher"]
