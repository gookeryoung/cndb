"""异步导入任务执行器 —— BackgroundTasks + 线程池.

状态机（扩展后）：
    pending_validation -> pending_confirm -> running -> done / failed
    pending_confirm    -> pending_validation              （用户取消确认）
    pending            -> running -> done / failed          （兼容旧流程）

执行器独立 Session，通过状态转换做乐观锁。
"""

from __future__ import annotations

import base64
import io
import json
import logging
import threading
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.tables.models import DataTable, ImportTask
from cndb.plugins.tables.services import transfer

# 追踪所有后台线程，供测试 fixture 等待完成
_background_threads: list[threading.Thread] = []
_background_lock = threading.Lock()


def join_background_threads(timeout: float = 5.0) -> None:
    """等待所有后台线程结束（用于测试清理前调用）."""
    with _background_lock:
        threads = list(_background_threads)
        _background_threads.clear()
    for t in threads:
        if t.is_alive():
            t.join(timeout=timeout)


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


def run_with_stage_timeout[T](fn: Callable[[], T], *, stage: str, timeout_seconds: int | None = None) -> T:
    """在独立线程中执行某阶段，超时抛 ``TimeoutError``（把静默卡死变成明确失败）.

    为什么需要：历史上 WPS 导出的 XLSX 会被解析层拖住（已在解析层修复），
    但**任何**解析/校验异常都可能表现为"进度停在 5%、无报错" —— 用户无法区分
    "还在跑"与"已经死了"。这里给出上界：超过 ``IMPORT_TASK_TIMEOUT_SECONDS`` 即失败并说明原因。

    - 超时后线程仍在后台运行（Python 无法强杀线程），但任务已判定失败；
      该线程后续若再改状态会被 ``_transition_status`` 的合法迁移校验挡住。
    - 因此这里 ``shutdown(wait=False)``，不阻塞调用方。
    """
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeoutError

    if timeout_seconds is None:
        from cndb.core.config import settings

        timeout_seconds = int(settings.IMPORT_TASK_TIMEOUT_SECONDS)

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"import-{stage}")
    future = pool.submit(fn)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        raise TimeoutError(
            f"导入{stage}阶段超过 {timeout_seconds} 秒仍未完成，已判定失败。"
            "常见原因是文件范围异常（如 WPS/Excel 写入的整列样式）或图片过多；"
            "请用 WPS/Excel 打开后「另存为」一份干净副本，或只保留所需行列后重试。"
        ) from exc
    finally:
        pool.shutdown(wait=False)


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
    from cndb.plugins.tables.services.importing.importer import Importer

    task = db_session.get(ImportTask, task_id)
    if task is None:
        logger.error("ImportTask %s 不存在", task_id)
        return

    try:
        _transition_status(task, "pending_validation")
    except ValueError:
        # 幂等守卫：任务已在分析/确认态（重复派发）时静默忽略，不崩线程
        logger.warning("ImportTask %s 重复触发 analyze（当前状态 %s），忽略", task_id, task.status)
        return
    task.progress = 5
    db_session.commit()

    try:
        table = db_session.get(DataTable, task.table_id)
        if table is None:
            raise RuntimeError(f"数据表 {task.table_id} 不存在")

        raw = _decode_content(task)
        engine = db_session.get_bind()

        imp = Importer(engine, db_session, table)
        analysis = run_with_stage_timeout(
            lambda: imp.analyze(
                raw,
                task.format,
                match_keys=list(task.match_keys) if task.match_keys else None,
                unknown_cols_strategy=task.unknown_cols_strategy or "drop",
            ),
            stage="校验",
        )

        task.total_rows = len(analysis.results)
        task.progress = 90
        db_session.commit()

        task.validation_report = json.dumps(analysis.report, ensure_ascii=False, default=str)
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

        # 字节输入走统一编码探测（与 importer._parse_csv / transfer 同源），
        # 不再硬编码 utf-8 —— GBK 等中文 CSV 之前会直接 UnicodeDecodeError
        buf = raw if isinstance(raw, str) else transfer.decode_bytes_auto(raw)[0]
        reader = _csv.DictReader(io.StringIO(buf))
        file_columns = list(reader.fieldnames or [])
        rows: list[dict[str, Any]] = []
        for row in reader:
            rows.append(dict(row))
        # CSV 导入场景下 link 值是分号分隔串，这里不做预解析，交给 RowValidator._parse_link_value
        return rows, file_columns, len(rows)
    if fmt == "json":
        data = json.loads(raw if isinstance(raw, str) else transfer.decode_bytes_auto(raw)[0])
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
        from cndb.plugins.tables.services.transfer.xlsx_rows import read_xlsx_rows

        # 有界流式读取（同 importer）：WPS 文件常声明百万行仅样式范围，全量物化会卡死
        rows: list[dict[str, Any]] = []
        file_columns: list[str] = []
        has_rows = False
        for _sheet_row, r in read_xlsx_rows(raw):
            has_rows = True
            if not file_columns:
                file_columns = [str(c) if c is not None else f"col_{i}" for i, c in enumerate(r)]
                continue
            # 与旧实现（openpyxl 补齐到最大列宽）一致：更宽的行补 col_{i} 列名
            if len(r) > len(file_columns):
                file_columns = [
                    *file_columns,
                    *[f"col_{i}" for i in range(len(file_columns), len(r))],
                ]
            # 长数字保护：对每个单元格值做精度保护转换
            rows.append({k: transfer._coerce_long_numeric_to_text(v) for k, v in zip(file_columns, r, strict=False)})
        if not has_rows:
            return [], [], 0
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

    try:
        _transition_status(task, "running")
    except ValueError:
        # 幂等守卫：任务已在执行/完成态（重复派发）时静默忽略，不崩线程
        logger.warning("ImportTask %s 重复触发 execute（当前状态 %s），忽略", task_id, task.status)
        return
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
            from cndb.plugins.tables.services.fields.field_ops import sync_select_options_from_table
            from cndb.plugins.tables.services.importing.importer import Importer

            importer = Importer(engine, db_session, table)
            result = run_with_stage_timeout(
                lambda: importer.execute(
                    raw,
                    task.format,
                    match_keys=list(task.match_keys) if task.match_keys else None,
                    unknown_cols_strategy=task.unknown_cols_strategy or "drop",
                    dropped_columns=list(task.dropped_columns) if task.dropped_columns else None,
                    cleaning_actions=list(task.cleaning_actions) if task.cleaning_actions else None,
                ),
                stage="执行",
            )
            task.imported_rows = len(result.imported_ids)
            task.result_ids = result.imported_ids
            task.validation_report = json.dumps(result.report, ensure_ascii=False, default=str)
            # 导入完成后自动补全 select/multiselect options
            try:
                sync_select_options_from_table(db_session, table)
            except Exception as exc:
                logger.warning("[ImportTask %s] select options 自动补全失败: %s", task_id, exc)
        else:
            # ── 旧流程兼容：直接调 transfer.import_rows_from_* ──
            from cndb.plugins.tables.services.fields.field_ops import sync_select_options_from_table

            total_lines = _estimate_total_rows(raw, task.format)
            task.total_rows = total_lines
            task.progress = 30
            db_session.commit()

            if task.format == "json":
                if not isinstance(raw, str):
                    raise ValueError("JSON 导入内容必须为文本")
                ids = transfer.import_rows_from_json(engine, table, raw, db=db_session)
            elif task.format == "csv":
                if not isinstance(raw, str):
                    raise ValueError("CSV 导入内容必须为文本")
                ids = transfer.import_rows_from_csv(engine, table, raw, db=db_session)
            elif task.format == "xlsx":
                if not isinstance(raw, bytes):
                    raise ValueError("XLSX 导入内容必须为字节")
                ids = transfer.import_rows_from_xlsx(engine, table, raw, db=db_session)
            else:
                raise ValueError(f"不支持的格式: {task.format}")

            task.imported_rows = len(ids)
            task.result_ids = ids
            # transfer 内部已有 _post_import_sync，但保险起见再调一次
            if ids:
                try:
                    sync_select_options_from_table(db_session, table)
                except Exception as exc:
                    logger.warning("[ImportTask %s] select options 自动补全失败: %s", task_id, exc)

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
        logger.debug("估算导入总行数失败，按 0 处理", exc_info=True)
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
    dropped_columns: list[str] | None = None,
) -> ImportTask:
    """创建异步导入任务并入库."""
    from cndb.plugins.tables.services.transfer import decode_bytes_auto

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
        dropped_columns=list(dropped_columns) if dropped_columns else [],
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
    from cndb.plugins.tables.services.importing.importer import Importer

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

        task.validation_report = json.dumps(analysis.report, ensure_ascii=False, default=str)
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
    with _background_lock:
        _background_threads.append(thread)
    thread.start()


__all__ = [
    "analyze_import_task",
    "create_import_task",
    "execute_import_task",
    "join_background_threads",
    "reanalyze_import_task",
    "run_task_in_background",
]
