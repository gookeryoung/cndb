"""异步导入任务执行器 —— BackgroundTasks + 线程池.

状态机：pending -> running -> done / failed
执行器独立 Session，通过乐观锁更新状态.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.tables import transfer
from cndb.plugins.tables.models import DataTable, ImportTask

logger = logging.getLogger(__name__)

# 允许的状态转换
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running"},
    "running": {"done", "failed"},
    "done": set(),
    "failed": {"running"},
}


def _transition_status(task: ImportTask, new_status: str) -> None:
    """原子状态转换，非法转换抛 ValueError."""
    allowed = _VALID_TRANSITIONS.get(task.status, set())
    if new_status not in allowed:
        raise ValueError(f"非法状态转换: {task.status} -> {new_status}")
    task.status = new_status


def execute_import_task(db_session: Session, task_id: int) -> None:  # noqa: PLR0912
    """执行导入任务（在线程中调用，独立 Session 安全）.

    包含：状态转换 -> 读取 DataTable -> 解码文件内容 -> 估算行数 -> 执行导入 -> 标记完成.
    """
    task = db_session.get(ImportTask, task_id)
    if task is None:
        logger.error("ImportTask %s 不存在", task_id)
        return

    _transition_status(task, "running")
    task.progress = 5
    db_session.commit()

    try:
        # 获取 DataTable
        table = db_session.get(DataTable, task.table_id)
        if table is None:
            raise RuntimeError(f"数据表 {task.table_id} 不存在")

        # 解析文件内容
        if task.format == "xlsx":
            raw: bytes | str = base64.b64decode(task.file_content)
        else:
            raw = task.file_content

        # 估算总行数（进度用）
        total_lines = 0
        if task.format in ("json", "csv") and isinstance(raw, str):
            try:
                if task.format == "json":
                    data = json.loads(raw)
                    total_lines = len(data) if isinstance(data, list) else 0
                else:
                    total_lines = raw.count("\n")
            except Exception:
                pass
        task.total_rows = total_lines
        task.progress = 10
        db_session.commit()

        # 执行导入
        task.progress = 30
        db_session.commit()

        engine = db_session.get_bind()
        if task.format == "json":
            assert isinstance(raw, str)
            ids = transfer.import_rows_from_json(engine, table, raw, db=db_session)
        elif task.format == "csv":
            assert isinstance(raw, str)
            ids = transfer.import_rows_from_csv(engine, table, raw, db=db_session)
        elif task.format == "xlsx":
            assert isinstance(raw, bytes)
            ids = transfer.import_rows_from_xlsx(engine, table, raw, db=db_session)
        else:
            raise ValueError(f"不支持的格式: {task.format}")

        task.imported_rows = len(ids)
        task.result_ids = ids
        task.progress = 100
        _transition_status(task, "done")
        db_session.commit()
        logger.info("ImportTask %s 完成：导入 %d 行", task_id, len(ids))

    except Exception as exc:
        logger.exception("ImportTask %s 失败: %s", task_id, exc)
        task.error_message = str(exc)
        task.progress = 100
        try:
            _transition_status(task, "failed")
            db_session.commit()
        except ValueError:
            task.status = "failed"
            db_session.commit()


def create_import_task(
    db: Session,
    *,
    table_id: int,
    user_id: int | None,
    filename: str,
    fmt: str,
    content: bytes | str,
) -> ImportTask:
    """创建异步导入任务并入库."""
    if fmt == "xlsx":
        if isinstance(content, bytes):
            stored = base64.b64encode(content).decode("ascii")
        else:
            stored = base64.b64encode(content.encode("latin-1")).decode("ascii")
    elif isinstance(content, bytes):
        stored = content.decode("utf-8")
    else:
        stored = content

    task = ImportTask(
        table_id=table_id,
        user_id=user_id,
        filename=filename,
        format=fmt,
        file_content=stored,
        status="pending",
        progress=0,
        total_rows=0,
        imported_rows=0,
        error_message="",
        result_ids=[],
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def run_task_in_background(
    db_session_factory: Any,
    task_id: int,
) -> None:
    """在后台线程中执行任务（避免 FastAPI BackgroundTasks 与请求生命周期耦合）."""

    def _worker() -> None:
        session = db_session_factory()
        try:
            execute_import_task(session, task_id)
        finally:
            session.close()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


__all__ = [
    "create_import_task",
    "execute_import_task",
    "run_task_in_background",
]
