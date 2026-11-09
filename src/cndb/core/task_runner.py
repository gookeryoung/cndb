"""后台任务线程的统一登记、超时与回收.

背景：导入 / 治理 / 数据流程 / 数据源同步等域各自起线程，其中三个域还各自维护一份
``_background_threads`` + ``join_background_threads``（超时 5s vs 10s、死线程是否清理
各不相同），测试收尾时只能对各自模块调用，跨域残留线程无法统一观测。导入阶段的超时
还通过 ``ThreadPoolExecutor`` + ``shutdown(wait=False)`` 实现：线程超时后既没有句柄、
也没有登记，属于真正的「无人认领」。

这里收敛成一份登记表：

- :func:`spawn`：启动并登记一个守护线程（可传 name 便于日志排查）
- :func:`run_with_timeout`：在登记线程中执行并等待结果，超时抛 ``TimeoutError``；
  超时线程留在登记表里，``join_all`` 仍可观测 / 等待
- :func:`join_all`：等待全部登记线程（测试收尾与服务关停用），未结束的线程保留登记

注意：Python 无法强杀线程，超时只代表「调用方不再等待」，被放弃的线程仍可能继续
写库；需要对写冲突敏感的场景（如导入写同一张物理表）应自行加写闸，见
``plugins/tables/services/importing/import_tasks.py`` 的 ``_exclusive_table_write``。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_threads: list[threading.Thread] = []


def spawn(name: str, target: Callable[[], None], *, daemon: bool = True) -> threading.Thread:
    """启动并登记一个后台线程；返回线程句柄（主要供调用方观测名字 / 存活状态）."""
    thread = threading.Thread(target=target, name=name, daemon=daemon)
    with _lock:
        # 顺手清理已结束的登记，避免长跑进程的登记表无限增长
        _threads[:] = [item for item in _threads if item.is_alive()]
        _threads.append(thread)
    thread.start()
    return thread


def run_with_timeout[T](fn: Callable[[], T], *, name: str, timeout: float, timeout_message: str) -> T:
    """在登记线程中执行 ``fn`` 并等待结果；超时抛 ``TimeoutError(timeout_message)``.

    超时后线程不会被强杀，而是留在登记表（``join_all`` 可观测），由调用方把任务判定为失败。
    ``fn`` 抛出的异常会原样在调用线程重新抛出，保持与直接调用一致的错误语义。
    """
    results: list[T] = []
    errors: list[BaseException] = []
    done = threading.Event()

    def _runner() -> None:
        try:
            results.append(fn())
        except BaseException as exc:  # 原样回抛给调用线程
            errors.append(exc)
        finally:
            done.set()

    spawn(name, _runner)
    if not done.wait(timeout):
        raise TimeoutError(timeout_message)
    if errors:
        raise errors[0]
    return results[0]


def join_all(timeout: float = 10.0) -> None:
    """等待全部登记线程结束；仍未结束的线程保留登记，便于下次继续等待 / 观测."""
    with _lock:
        threads = list(_threads)
    for thread in threads:
        thread.join(timeout=timeout)
        if thread.is_alive():
            logger.warning("后台线程 %s 在 %.1fs 内未结束（超时被放弃的任务线程），保留登记", thread.name, timeout)
    with _lock:
        _threads[:] = [item for item in _threads if item.is_alive()]


def live_threads() -> list[str]:
    """当前仍存活的登记线程名（运维排查 / 测试断言用）."""
    with _lock:
        return [item.name for item in _threads if item.is_alive()]


def reset() -> None:
    """清空登记（仅测试用：配合 ``join_all`` 隔离用例间的线程状态）."""
    with _lock:
        _threads.clear()


__all__ = ["join_all", "live_threads", "reset", "run_with_timeout", "spawn"]
