"""工作区存储用量快照的后台刷新线程（ADR 0024 P0）.

管理台「空间分配」等入口曾经在请求内逐工作区现算用量（附件目录遍历 + 文档正文
汇总 + 每张物理表逐行字节累加），成本随数据量线性增长。改为后台按周期重算一次
并落库（``workspaces_storage_snapshot``），读路径只查快照。

线程模型：

- 单守护线程 + ``threading.Event`` 唤醒。等待 ``STORAGE_SNAPSHOT_INTERVAL_SECONDS``
  超时（定时轮次）或被 ``mark_dirty`` / ``request_refresh`` 唤醒（脏轮次）；
- 每轮都调 ``refresh_all(only_dirty=True)``：脏集合非空 → 只刷脏工作区；
  为空 → 全量兜底（覆盖直连数据库改数据等外部变更）；
- 单工作区失败只记日志并计入 ``failed``，不影响其余工作区，也不打断线程；
- ``interval = 0`` 关闭定时轮次，线程仍常驻以服务「立即刷新」与脏唤醒。

关闭顺序：``stop_storage_refresher`` 先 set 唤醒信号再 join，超时不阻塞进程退出。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from cndb.core.config import settings

logger = logging.getLogger(__name__)


class StorageSnapshotRefresher:
    """工作区用量快照刷新器（进程内单实例）."""

    def __init__(self, *, interval_seconds: int, startup_delay_seconds: int) -> None:
        self._interval = max(0, int(interval_seconds))
        self._startup_delay = max(0, int(startup_delay_seconds))
        self._wakeup = threading.Event()
        self._stop = threading.Event()
        self._refreshing = threading.Event()
        self._thread: threading.Thread | None = None

    # ── 生命周期 ──

    def start(self) -> bool:
        """启动后台线程（幂等）；已运行返回 False."""
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="cndb-storage-snapshot",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "存储用量快照刷新线程已启动（周期 %ss，首轮延迟 %ss）",
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
                logger.warning("存储用量快照刷新线程未在 %.1fs 内退出（守护线程，随进程结束）", timeout)
        self._thread = None
        logger.info("存储用量快照刷新线程已停止")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def is_refreshing(self) -> bool:
        """当前是否正在执行一轮刷新（接口用它回传 refreshing）."""
        return self._refreshing.is_set()

    # ── 轮次 ──

    def _run(self) -> None:
        from cndb.plugins.workspaces.services.storage_snapshot import refresh_all, register_wakeup

        register_wakeup(self._wakeup)
        try:
            # 首轮：延迟后先做一次全量，避免刚启动时管理台全是「统计中」
            if self._startup_delay and self._stop.wait(self._startup_delay):
                return
            while not self._stop.is_set():
                self._refresh_once(refresh_all)
                # 定时轮次：interval=0 时无限等，只由脏唤醒 / 停止信号推进
                self._wakeup.wait(self._interval if self._interval > 0 else None)
                self._wakeup.clear()
        finally:
            register_wakeup(None)

    def _refresh_once(self, refresh_all: Callable[..., Any]) -> None:
        self._refreshing.set()
        try:
            refresh_all(only_dirty=True)
        except Exception:  # pragma: no cover - 兜底：线程不能因单轮失败退出
            logger.warning("存储用量快照刷新轮次失败（等下一轮）", exc_info=True)
        finally:
            self._refreshing.clear()


class _Registry:
    """进程内刷新器句柄（用实例属性代替模块级 ``global``）."""

    def __init__(self) -> None:
        self.refresher: StorageSnapshotRefresher | None = None


_registry = _Registry()


def get_storage_refresher() -> StorageSnapshotRefresher | None:
    """当前进程的刷新器（未启动时为 None）."""
    return _registry.refresher


def start_storage_refresher() -> StorageSnapshotRefresher | None:
    """按配置启动刷新器（``STORAGE_SNAPSHOT_ENABLED=False`` 时跳过）."""
    if not settings.STORAGE_SNAPSHOT_ENABLED:
        logger.debug("存储用量快照刷新已关闭（STORAGE_SNAPSHOT_ENABLED=False）")
        return None
    current = _registry.refresher
    if current is not None and current.running:
        return current
    _registry.refresher = StorageSnapshotRefresher(
        interval_seconds=settings.STORAGE_SNAPSHOT_INTERVAL_SECONDS,
        startup_delay_seconds=settings.STORAGE_SNAPSHOT_STARTUP_DELAY_SECONDS,
    )
    _registry.refresher.start()
    return _registry.refresher


def stop_storage_refresher(timeout: float = 5.0) -> None:
    """停止刷新器（应用关闭时调用）."""
    current = _registry.refresher
    _registry.refresher = None
    if current is not None:
        current.stop(timeout=timeout)


__all__ = [
    "StorageSnapshotRefresher",
    "get_storage_refresher",
    "start_storage_refresher",
    "stop_storage_refresher",
]
