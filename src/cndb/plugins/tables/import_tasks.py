"""异步导入任务执行器 —— BackgroundTasks + 线程池.

状态机（扩展后）：
    pending_validation -> pending_confirm -> running -> done / failed
    pending_confirm    -> pending_validation              （用户取消确认）
    pending            -> running -> done / failed          （兼容旧流程）

执行器独立 Session，通过状态转换做乐观锁。
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
    "pending_validation": {"pending_confirm", "failed"},
    "pending_confirm": {"pending_validation", "running", "failed"},
    "pending": {"running", "pending_validation"},
    "running": {"done", "failed"},
    "done": set(),
    "failed": {"pending_validation", "pending_confirm", "running"},
}


def _transition_status(task: ImportTask, new_status: str) -> None:
    """原子状态转换，非法转换抛 ValueError."""
    allowed = _VALID_TRANSITIONS.get(task.status, set())
    if new_status not in allowed:
        raise ValueError(f"非法状态转换: {task.status} -> {new_status}")
    task.status = new_status


def _decode_content(task: ImportTask) -> bytes | str:
    """根据 ImportTask.format 解码 file_content."""
    if task.format == "xlsx":
        return base64.b64decode(task.file_content)
    return task.file_content


# ── Analyze 阶段 ──────────────────────────────────


def analyze_import_task(db_session: Session, task_id: int) -> None:
    """仅做解析 + 校验 + 报告，不写库.

    完成后 task.status = pending_confirm，validation_report 填充 JSON.
    """
    from cndb.plugins.tables.importer import Importer

    task = db_session.get(ImportTask, task_id)
    if task is None:
        logger.error("ImportTask %s 不存在", task_id)
        return

    _transition_status(task, "pending_validation")
    task.progress = 5
    db_session.commit()

    try:
        table = db_session.get(DataTable, task.table_id)
        if table is None:
            raise RuntimeError(f"数据表 {task.table_id} 不存在")

        raw = _decode_content(task)
        engine = db_session.get_bind()

        imp = Importer(engine, db_session, table)
        analysis = imp.analyze(
            raw,
            task.format,
            match_keys=list(task.match_keys) if task.match_keys else None,
            unknown_cols_strategy=task.unknown_cols_strategy or "drop",
        )

        task.total_rows = len(analysis.results)
        task.progress = 90
        db_session.commit()

        task.validation_report = json.dumps(analysis.report, ensure_ascii=False)
        task.progress = 95
        _transition_status(task, "pending_confirm")
        db_session.commit()

        logger.info(
            "ImportTask %s analyze 完成：total=%d valid=%d error=%d",
            task_id,
            task.total_rows,
            analysis.report["valid_count"],
            analysis.report["error_count"],
        )
    except Exception as exc:
        logger.exception("ImportTask %s analyze 失败: %s", task_id, exc)
        task.error_message = str(exc)
        task.progress = 100
        try:
            _transition_status(task, "failed")
            db_session.commit()
        except ValueError:
            task.status = "failed"
            db_session.commit()


def _parse_to_rows(
    raw: bytes | str,
    fmt: str,
    _engine: Any,
    _table: DataTable,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """解析文件内容为 (行列表, 文件列名, 总行数)."""
    if fmt == "csv":
        import csv as _csv

        buf = raw if isinstance(raw, str) else raw.decode("utf-8")
        reader = _csv.DictReader(__import__("io").StringIO(buf))
        file_columns = list(reader.fieldnames or [])
        rows: list[dict[str, Any]] = []
        for row in reader:
            rows.append(dict(row))
        # CSV 导入场景下 link 值是分号分隔串，这里不做预解析，交给 RowValidator._parse_link_value
        return rows, file_columns, len(rows)
    if fmt == "json":
        data = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
        if not isinstance(data, list):
            raise ValueError("JSON 必须是对象数组")
        file_columns: list[str] = []
        seen: set[str] = set()
        for item in data:
            if isinstance(item, dict):
                for k in item:
                    if k not in seen:
                        seen.add(k)
                        file_columns.append(k)
        return [r for r in data if isinstance(r, dict)], file_columns, len(data)
    if fmt == "xlsx":
        from openpyxl import load_workbook

        buf = __import__("io").BytesIO(raw if isinstance(raw, bytes) else raw.encode())
        wb = load_workbook(buf)
        ws = wb.active
        assert ws is not None
        all_rows = list(ws.iter_rows(values_only=True))
        if not all_rows:
            return [], [], 0
        file_columns = [str(c) if c is not None else f"col_{i}" for i, c in enumerate(all_rows[0])]
        rows = [dict(zip(file_columns, r, strict=False)) for r in all_rows[1:] if any(c is not None for c in r)]
        return rows, file_columns, len(rows)
    raise ValueError(f"不支持的格式: {fmt}")


# ── Execute 阶段 ──────────────────────────────────


def execute_import_task(db_session: Session, task_id: int) -> None:
    """执行导入任务（在线程中调用，独立 Session 安全）.

    支持两种入口：
    1. pending_confirm → running  （新流程，已有 validation_report）
    2. pending / failed → running （兼容旧流程，直接跑 import_rows_from_*）
    """
    task = db_session.get(ImportTask, task_id)
    if task is None:
        logger.error("ImportTask %s 不存在", task_id)
        return

    _transition_status(task, "running")
    task.progress = 5
    db_session.commit()

    try:
        table = db_session.get(DataTable, task.table_id)
        if table is None:
            raise RuntimeError(f"数据表 {task.table_id} 不存在")

        raw = _decode_content(task)
        engine = db_session.get_bind()

        # ── 有 validation_report 时走 Importer 链路（支持 upsert + 字段自动新增） ──
        if task.validation_report:
            from cndb.plugins.tables.importer import Importer

            importer = Importer(engine, db_session, table)
            result = importer.execute(
                raw,
                task.format,
                match_keys=list(task.match_keys) if task.match_keys else None,
                unknown_cols_strategy=task.unknown_cols_strategy or "drop",
                cleaning_actions=list(task.cleaning_actions) if task.cleaning_actions else None,
            )
            task.imported_rows = len(result.imported_ids)
            task.result_ids = result.imported_ids
            task.validation_report = json.dumps(result.report, ensure_ascii=False)
        else:
            # ── 旧流程兼容：直接调 transfer.import_rows_from_* ──
            total_lines = _estimate_total_rows(raw, task.format)
            task.total_rows = total_lines
            task.progress = 30
            db_session.commit()

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
        logger.info("ImportTask %s 完成：导入 %d 行", task_id, task.imported_rows)

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


def _estimate_total_rows(raw: bytes | str, fmt: str) -> int:
    """快速估算行数（进度条用，不追求精确）."""
    try:
        if fmt in ("json",) and isinstance(raw, str):
            data = json.loads(raw)
            return len(data) if isinstance(data, list) else 0
        if fmt == "csv" and isinstance(raw, str):
            return raw.count("\n")
    except Exception:
        pass
    return 0


# ── 创建 / 调度入口 ────────────────────────────────


def create_import_task(
    db: Session,
    *,
    table_id: int,
    user_id: int | None,
    filename: str,
    fmt: str,
    content: bytes | str,
    status: str = "pending",
    match_keys: list[str] | None = None,
    unknown_cols_strategy: str = "drop",
) -> ImportTask:
    """创建异步导入任务并入库."""
    from cndb.plugins.tables.transfer import decode_bytes_auto

    if fmt == "xlsx":
        if isinstance(content, bytes):
            stored = base64.b64encode(content).decode("ascii")
        else:
            stored = base64.b64encode(content.encode("latin-1")).decode("ascii")
    elif isinstance(content, bytes):
        # CSV / JSON bytes：自动编码检测后存字符串
        stored, _enc, _conf = decode_bytes_auto(content)
    else:
        stored = content

    task = ImportTask(
        table_id=table_id,
        user_id=user_id,
        filename=filename,
        format=fmt,
        file_content=stored,
        status=status,
        progress=0,
        total_rows=0,
        imported_rows=0,
        error_message="",
        result_ids=[],
        validation_report="",
        match_keys=list(match_keys) if match_keys else [],
        unknown_cols_strategy=unknown_cols_strategy or "drop",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def reanalyze_import_task(
    db_session: Session,
    task_id: int,
    *,
    match_keys: list[str] | None = None,
    unknown_cols_strategy: str | None = None,
) -> None:
    """用新参数重新跑 analyze（让用户在 preview 阶段改参考列/未知列策略后重算 diff）.

    允许的源状态：pending_confirm、pending_validation。
    完成后回到 pending_confirm，更新后的 validation_report 带新的 upsert 分类。
    """
    from cndb.plugins.tables.importer import Importer

    task = db_session.get(ImportTask, task_id)
    if task is None:
        logger.error("ImportTask %s 不存在", task_id)
        return
    if task.status not in ("pending_confirm", "pending_validation"):
        raise ValueError(f"当前状态 {task.status} 不允许重新分析（需 pending_confirm）")

    # 更新任务参数
    if match_keys is not None:
        task.match_keys = list(match_keys)
    if unknown_cols_strategy is not None:
        task.unknown_cols_strategy = unknown_cols_strategy

    _transition_status(task, "pending_validation")
    task.progress = 10
    task.error_message = ""
    db_session.commit()

    try:
        table = db_session.get(DataTable, task.table_id)
        if table is None:
            raise RuntimeError(f"数据表 {task.table_id} 不存在")

        raw = _decode_content(task)
        engine = db_session.get_bind()

        imp = Importer(engine, db_session, table)
        analysis = imp.analyze(
            raw,
            task.format,
            match_keys=list(task.match_keys) if task.match_keys else None,
            unknown_cols_strategy=task.unknown_cols_strategy or "drop",
        )

        task.total_rows = len(analysis.results)
        task.progress = 90
        db_session.commit()

        task.validation_report = json.dumps(analysis.report, ensure_ascii=False)
        task.progress = 95
        _transition_status(task, "pending_confirm")
        db_session.commit()

        logger.info(
            "ImportTask %s reanalyze 完成：new=%d update=%d error=%d",
            task_id,
            analysis.report.get("new_count", 0),
            analysis.report.get("update_count", 0),
            analysis.report["error_count"],
        )
    except Exception as exc:
        logger.exception("ImportTask %s reanalyze 失败: %s", task_id, exc)
        task.error_message = str(exc)
        task.progress = 100
        try:
            _transition_status(task, "failed")
            db_session.commit()
        except ValueError:
            task.status = "failed"
            db_session.commit()


def run_task_in_background(
    db_session_factory: Any,
    task_id: int,
    *,
    phase: str = "execute",
) -> None:
    """在后台线程中执行任务.

    Args:
        phase: "execute"（默认，跑 execute_import_task）、"analyze"（跑 analyze_import_task），
            或 "reanalyze"（跑 reanalyze_import_task，match_keys / unknown_cols_strategy 从 task 上读取）.
        match_keys / unknown_cols_strategy: reanalyze 阶段可选的新参数.
    """

    def _worker() -> None:
        session = db_session_factory()
        try:
            if phase == "analyze":
                analyze_import_task(session, task_id)
            elif phase == "reanalyze":
                reanalyze_import_task(session, task_id)
            else:
                execute_import_task(session, task_id)
        finally:
            session.close()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


__all__ = [
    "analyze_import_task",
    "create_import_task",
    "execute_import_task",
    "reanalyze_import_task",
    "run_task_in_background",
]
