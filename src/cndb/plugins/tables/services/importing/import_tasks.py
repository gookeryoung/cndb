"""异步导入任务执行器 —— BackgroundTasks + 线程池.

状态机（扩展后）：
    pending_validation -> pending_confirm -> running -> done / failed
    pending_confirm    -> pending_validation              （用户取消确认）
    pending            -> running -> done / failed          （兼容旧流程）

执行器独立 Session，通过状态转换做乐观锁。
"""

from __future__ import annotations

import base64
import contextlib
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


# ── 失败落库 ──────────────────────────────────────


def _readable_error(exc: Exception) -> str:
    """把异常压成一句给用户看的原因（完整堆栈留在服务日志里）.

    ORM/DB 异常的 ``str()`` 会带整段 SQL 与绑定参数，直接塞进前端提示既读不懂
    也可能泄露表结构，因此对常见冲突做翻译。
    """
    from sqlalchemy.exc import IntegrityError

    if isinstance(exc, IntegrityError):
        text = str(getattr(exc, "orig", exc))
        if "tables_datafield" in text:
            return (
                "字段写入冲突：表中已存在同名字段（含已删除但占用名字的字段），导入已中止。"
                "请在表格设置里清理重名字段后重试。"
            )
        return "数据写入冲突（唯一约束），导入已中止。请检查是否有重复字段或重复行。"

    import re

    from sqlalchemy.exc import SQLAlchemyError

    if isinstance(exc, SQLAlchemyError):
        # 去掉 SQLAlchemy 拼接的 "[SQL: ...]" / "[parameters: ...]" 尾巴
        return re.split(r"\s*\[SQL:|\(Background on this error", str(exc))[0].strip() or exc.__class__.__name__
    return str(exc)


def _mark_task_failed(db_session: Session, task_id: int, exc: Exception) -> None:
    """把任务落库为 failed（唯一入口）.

    必须**先 rollback 再写**：异常若发生在 flush/commit 中途（如唯一约束冲突），
    Session 进入 PendingRollback 状态，此时任何 commit 都会再抛
    ``PendingRollbackError``。旧实现在 ``except`` 里直接 commit，第二个异常逃逸出
    后台线程 → 任务行永远停在 ``running``/"执行子步骤 25%"，
    前端表现就是"进度卡住、无任何报错"。所以这里先回滚，再单独提交失败状态。
    """
    with contextlib.suppress(Exception):
        db_session.rollback()

    task = db_session.get(ImportTask, task_id)
    if task is None:  # pragma: no cover - 任务被并发删除
        logger.warning("ImportTask %s 不存在，无法落库失败状态", task_id)
        return

    task.error_message = _readable_error(exc)
    task.progress = 100
    try:
        _transition_status(task, "failed")
    except ValueError:  # pragma: no cover - 状态已不可迁移，兜底直写
        task.status = "failed"

    try:
        db_session.commit()
    except Exception:
        # 落库失败也必须让调用方知道，但不允许再抛出异常拖垮后台线程
        logger.exception("ImportTask %s 失败状态落库失败", task_id)
        with contextlib.suppress(Exception):
            db_session.rollback()


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
    logger.info(
        "[ImportTask %s] analyze 开始（文件 %s，%d 字节）", task_id, task.filename, len(task.file_content or "")
    )

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
        _mark_task_failed(db_session, task_id, exc)


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


def _header_row_from_report(task: ImportTask) -> int | None:
    """从 analyze 产出的 ``validation_report`` 读取本次采用的表头行.

    execute 在独立线程 / 独立 Session 中重新解析文件，必须按 analyze 时同一行
    切分才能保证「预览看到的表头 = 实际落库的表头」。历史任务与 JSON 导入没有
    ``header_row`` 键，返回 None（auto 识别 / JSON 不涉及表头）。
    """
    if not task.validation_report:
        return None
    try:
        report = json.loads(task.validation_report)
    except (TypeError, ValueError):
        return None
    value = report.get("header_row") if isinstance(report, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


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
    logger.info(
        "[ImportTask %s] execute 开始（文件 %s，%d 字节，进度 %s%%)",
        task_id,
        task.filename,
        len(task.file_content or ""),
        task.progress,
    )

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

            def _on_progress(percent: int, stage: str) -> None:
                # 子步骤进度落库：卡住时能直接看出卡在解析/校验/写入/选项同步哪一步，
                # 而不是永远只有一个 5%。
                task.progress = percent
                db_session.commit()
                logger.info("[ImportTask %s] 执行子步骤 %d%%：%s", task_id, percent, stage)

            result = run_with_stage_timeout(
                lambda: importer.execute(
                    raw,
                    task.format,
                    match_keys=list(task.match_keys) if task.match_keys else None,
                    unknown_cols_strategy=task.unknown_cols_strategy or "drop",
                    dropped_columns=list(task.dropped_columns) if task.dropped_columns else None,
                    cleaning_actions=list(task.cleaning_actions) if task.cleaning_actions else None,
                    progress_cb=_on_progress,
                    header_row=_header_row_from_report(task),
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
        _mark_task_failed(db_session, task_id, exc)


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
    header_row: int | None = None,
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

    # 更新任务参数；表头行优先用本次参数，其次沿用 endpoint 写入的种子报告，
    # 都没有则由 analyze 自动识别（确定性，同一文件同一结果）
    if header_row is None:
        header_row = _header_row_from_report(task)
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
            header_row=header_row,
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
        _mark_task_failed(db_session, task_id, exc)


# 任务处于"进行中"的状态集合（进程重启会把这些留在原地）
_IN_FLIGHT_STATUSES = ("pending_validation", "running")
# 失速判定阈值（秒）：进行中任务超过该时长没有任何更新即判定为中断
STALL_THRESHOLD_SECONDS = 180


def _stall_message(task: ImportTask, elapsed: float) -> str:
    return (
        f"导入任务已 {elapsed:.0f} 秒没有进展（停留在「{task.status}」/ {task.progress}%），"
        "判定为中断。常见原因：服务在任务执行期间重启或容器被重建（部署/内存不足），"
        "导致后台线程被直接终止。请重新上传文件重试；若反复出现，请缩小文件或联系管理员查看服务日志。"
    )


def reclaim_interrupted_tasks(db_session: Session, *, stall_threshold: int = STALL_THRESHOLD_SECONDS) -> int:
    """回收"进行中但已无推进"的导入任务 → failed（返回处理条数）.

    为什么需要：任务跑在**进程内后台线程**里，容器重建/进程崩溃会把它直接带走，
    任务行永远停在"运行中 5%"。前端只依据 status 展示，于是表现为
    "进度卡 5% 且无任何报错" —— 用户无法知道该怎么办。

    两处调用：
    - 应用启动时（``reclaim_on_startup``）：上一进程遗留的任务必然已成为孤儿；
    - 查询任务详情时（``get_import_task``）：进程仍活着但线程异常终止的情况。
    """
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=stall_threshold)
    stale = (
        db_session.query(ImportTask)
        .filter(ImportTask.status.in_(_IN_FLIGHT_STATUSES))
        .filter((ImportTask.updated_at.is_(None)) | (ImportTask.updated_at < cutoff))
        .all()
    )
    for task in stale:
        updated = task.updated_at or task.created_at
        elapsed = (datetime.now(UTC).replace(tzinfo=None) - updated).total_seconds() if updated else 0.0
        task.error_message = _stall_message(task, elapsed)
        task.progress = 100
        task.status = "failed"
        logger.warning(
            "[ImportTask %s] 回收中断任务（状态=%s 进度=%s 停滞 %.0fs）",
            task.id,
            task.status,
            task.progress,
            elapsed,
        )
    if stale:
        db_session.commit()
    return len(stale)


def reclaim_on_startup() -> int:
    """应用启动时回收上一进程遗留的进行中任务（best-effort，绝不阻塞启动）."""
    try:
        from cndb.core.database import SessionLocal

        session = SessionLocal()
        try:
            # 上一进程已消失：这些任务不可能再有人推进，按"已中断"直接判定
            return reclaim_interrupted_tasks(session, stall_threshold=0)
        finally:
            session.close()
    except Exception:
        logger.warning("启动时回收导入任务失败（忽略，不影响启动）", exc_info=True)
        return 0


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
    "reclaim_interrupted_tasks",
    "reclaim_on_startup",
    "run_task_in_background",
]
