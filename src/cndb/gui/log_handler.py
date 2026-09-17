"""GUI 日志重定向辅助.

把 stdout/stderr 的 print 输出实时追加到 tkinter Text 组件，
便于在 GUI 中展示后端服务日志、备份/恢复进度等信息。

线程安全：GUI 更新必须在主线程执行，本模块用 root.after() 排队。
"""

from __future__ import annotations

import sys
import threading
from collections import deque
from collections.abc import Callable
from typing import TextIO


class QueueStdout:
    """线程安全的文本队列，供后台 worker 写入、主线程定时 flush。

    用法：
        import sys
        q = QueueStdout()
        sys.stdout = q
        sys.stderr = q
        # 主线程定时调用 q.flush_to(widget)
    """

    def __init__(self) -> None:
        self._queue: deque[str] = deque()
        self._lock = threading.Lock()
        self._original_stdout: TextIO = sys.stdout
        self._original_stderr: TextIO = sys.stderr

    def write(self, text: str) -> int:
        if text:
            with self._lock:
                self._queue.append(text)
        return len(text)

    def flush(self) -> None:
        # 主线程会定时 drain
        pass

    def get_batch(self) -> str:
        """取出当前累积的全部文本（清空队列）."""
        with self._lock:
            if not self._queue:
                return ""
            # 拼接后清空
            text = "".join(self._queue)
            self._queue.clear()
            return text


def flush_log_to_text(queue: QueueStdout, text_widget: object) -> None:
    """把队列中待输出的文本追加到 Text 组件（无 Tag，纯文本）."""
    import tkinter as tk

    batch = queue.get_batch()
    if not batch:
        return
    text_widget.configure(state=tk.NORMAL)  # type: ignore[attr-defined]
    text_widget.insert(tk.END, batch)  # type: ignore[attr-defined]
    text_widget.see(tk.END)  # type: ignore[attr-defined]
    text_widget.configure(state=tk.DISABLED)  # type: ignore[attr-defined]


def schedule_log_flush(root: object, queue: QueueStdout, text_widget: object, interval_ms: int = 120) -> None:
    """在 tk 主循环中定时 flush 队列到 Text 组件."""

    def _tick() -> None:
        flush_log_to_text(queue, text_widget)
        root.after(interval_ms, _tick)  # type: ignore[union-attr]

    root.after(interval_ms, _tick)  # type: ignore[union-attr]


def run_in_thread(target: Callable[[], None]) -> threading.Thread:
    """后台启动一个 daemon 线程跑耗时任务（备份/恢复/seed 等）."""
    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t
