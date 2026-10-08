"""治理任务执行器 —— 状态机 + 后台线程调度.

状态机：
    pending -> running -> done / failed

执行器独立 Session（线程内新建），通过状态转换做乐观锁；
与 import_tasks 的执行器为结构同构（第三个任务型需求出现前不合并）。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.tables.models import DataTable, GovernanceTask

logger = logging.getLogger(__name__)

# 任务类型
TASK_KINDS = ("detect", "merge", "clean")

# 允许的状态转换
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running"},
    "running": {"done", "failed"},
    "done": set(),
    "failed": set(),
}

# 活跃状态：同表同时仅允许一个活跃任务
ACTIVE_STATUSES = {"pending", "running"}

# 追踪所有后台线程，供测试 fixture 等待完成
_background_threads: list[threading.Thread] = []
_background_lock = threading.Lock()


class GovernanceTaskError(Exception):
    """治理任务业务校验错误（路由层映射为 400）."""


def join_background_threads(timeout: float = 10.0) -> None:
    """等待所有后台线程结束（用于测试清理前调用）."""
    with _background_lock:
        threads = list(_background_threads)
        _background_threads.clear()
    for t in threads:
        if t.is_alive():
            t.join(timeout=timeout)


def create_governance_task(
    db: Session,
    *,
    table: DataTable,
    user_id: int | None,
    kind: str,
    config: dict[str, Any],
) -> GovernanceTask:
    """创建治理任务并入库.

    Raises:
        GovernanceTaskError: kind 非法，或同表已存在 pending/running 任务.
    """
    if kind not in TASK_KINDS:
        raise GovernanceTaskError(f"不支持的任务类型: {kind}")
    exists = (
        db.query(GovernanceTask.id)
        .filter(
            GovernanceTask.table_id == table.id,
            GovernanceTask.status.in_(ACTIVE_STATUSES),
        )
        .first()
    )
    if exists is not None:
        raise GovernanceTaskError("该表已有进行中的治理任务，请等待完成后再创建")
    task = GovernanceTask(table_id=table.id, user_id=user_id, kind=kind, config=config or {})
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _transition_status(task: GovernanceTask, new_status: str) -> None:
    """原子状态转换，非法转换抛 ValueError."""
    allowed = _VALID_TRANSITIONS.get(task.status, set())
    if new_status not in allowed:
        raise ValueError(f"非法状态转换: {task.status} -> {new_status}")
    task.status = new_status


def execute_governance_task(db_session: Session, task_id: int) -> None:
    """执行治理任务（在线程中调用，独立 Session 安全）.

    生命周期统一在此管理（running -> done/failed）；
    各 kind 的具体执行器只做业务处理并更新进度 / 报告。
    """
    task = db_session.get(GovernanceTask, task_id)
    if task is None:
        logger.error("GovernanceTask %s 不存在", task_id)
        return

    _transition_status(task, "running")
    task.progress = 5
    db_session.commit()

    try:
        table = db_session.get(DataTable, task.table_id)
        if table is None:
            raise RuntimeError(f"数据表 {task.table_id} 不存在")

        # 按需延迟导入，避免循环依赖；monkeypatch 模块属性可替换执行器（测试用）
        if task.kind == "detect":
            from cndb.plugins.tables.services.governance import detect

            detect.execute_detect_task(db_session, task)
        elif task.kind == "merge":
            from cndb.plugins.tables.services.governance import merge

            merge.execute_merge_task(db_session, task)
        elif task.kind == "clean":
            from cndb.plugins.tables.services.governance import clean

            clean.execute_clean_task(db_session, task)
        else:  # pragma: no cover - create_governance_task 已拦截非法 kind
            raise GovernanceTaskError(f"不支持的任务类型: {task.kind}")

        task.progress = 100
        _transition_status(task, "done")
        db_session.commit()
        logger.info("GovernanceTask %s 完成（kind=%s）", task_id, task.kind)

    except Exception as exc:
        logger.exception("GovernanceTask %s 失败: %s", task_id, exc)
        task.error_message = str(exc)
        task.progress = 100
        try:
            _transition_status(task, "failed")
            db_session.commit()
        except ValueError:  # pragma: no cover - 防御性兜底
            task.status = "failed"
            db_session.commit()


def run_governance_task_in_background(db_session_factory: Any, task_id: int) -> None:
    """在后台线程中执行治理任务."""

    def _worker() -> None:
        session = db_session_factory()
        try:
            execute_governance_task(session, task_id)
        finally:
            session.close()

    thread = threading.Thread(target=_worker, daemon=True)
    with _background_lock:
        _background_threads.append(thread)
    thread.start()


__all__ = [
    "ACTIVE_STATUSES",
    "TASK_KINDS",
    "GovernanceTaskError",
    "create_governance_task",
    "execute_governance_task",
    "join_background_threads",
    "run_governance_task_in_background",
]
