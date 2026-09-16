"""批量操作 + 导入导出路由."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables import records as rec
from cndb.plugins.tables import transfer
from cndb.plugins.tables.access import TableAction
from cndb.plugins.tables.import_tasks import create_import_task, run_task_in_background
from cndb.plugins.tables.models import ImportTask
from cndb.plugins.tables.routers.tables import _get_table_or_404
from cndb.plugins.tables.schemas import BulkDeleteRequest

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}", tags=["bulk"])


# ── 批量建行 ───────────────────────────────────────────


@router.post("/records/bulk-create", status_code=status.HTTP_201_CREATED)
def bulk_create_records(
    workspace_id: int,
    table_id: int,
    payload: dict[str, Any],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)
    rows = payload.get("rows", [])
    if not rows:
        raise HTTPException(status_code=400, detail="rows 不能为空")
    # 兼容两种格式：直接 values 数组 或 {values} 包装
    normalized = [r.get("values", r) if isinstance(r, dict) else r for r in rows]

    # 导入前预填充 + 导入后同步 select/multiselect options
    try:
        from cndb.plugins.tables.field_ops import (
            prefill_select_options_from_rows,
            sync_select_options_from_table,
        )

        if normalized:
            prefill_select_options_from_rows(db, dt, normalized)
    except Exception:
        pass

    ids = rec.bulk_create(db.get_bind(), dt, normalized, db=db)

    try:
        from cndb.plugins.tables.field_ops import sync_select_options_from_table

        sync_select_options_from_table(db, dt)
    except Exception:
        pass

    return {"created": len(ids), "ids": ids}


# ── 批量删行 ───────────────────────────────────────────


@router.post("/records/bulk-delete", status_code=status.HTTP_200_OK)
def bulk_delete_records(
    workspace_id: int,
    table_id: int,
    payload: BulkDeleteRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)
    deleted = rec.bulk_delete(db.get_bind(), dt, payload.row_ids)
    return {"deleted": deleted}


# ── 批量改行 ───────────────────────────────────────────


@router.post("/records/bulk-update", status_code=status.HTTP_200_OK)
def bulk_update_records(
    workspace_id: int,
    table_id: int,
    payload: dict[str, Any],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)
    row_ids = payload.get("row_ids", [])
    values = payload.get("values", {})
    if not row_ids:
        raise HTTPException(status_code=400, detail="row_ids 不能为空")
    if not values:
        raise HTTPException(status_code=400, detail="values 不能为空")

    # 更新前预填充 select/multiselect options（让新值的校验能通过）
    try:
        from cndb.plugins.tables.field_ops import prefill_select_options_from_rows

        # values 是 {"field_name": new_value} 格式，转换成 rows=[values] 让 prefill 能提取
        prefill_select_options_from_rows(db, dt, [values])
    except Exception:
        pass

    updated = rec.bulk_update(db.get_bind(), dt, row_ids, values, db=db)

    # 更新后同步 select/multiselect options（兜底：物理表中可能有其他行的值未覆盖）
    try:
        from cndb.plugins.tables.field_ops import sync_select_options_from_table

        sync_select_options_from_table(db, dt)
    except Exception:
        pass

    return {"updated": updated}


# ── 导出 ──────────────────────────────────────────────


@router.get("/export")
def export_table(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    format: str = "json",
    view_id: int | None = None,
) -> Response:
    """导出当前表的数据，支持按视图筛选条件导出.

    Args:
        workspace_id: 工作区 ID
        table_id: 表 ID
        current_user: 当前登录用户
        db: 数据库会话
        format: 导出格式（json/csv/xlsx），默认 json
        view_id: 可选的视图 ID；传入后按该视图的 filters/sortings/filter_type 过滤结果

    Returns:
        对应格式的文件二进制响应
    """
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    filters: list[dict[str, Any]] | None = None
    sorts: list[dict[str, Any]] | None = None
    filter_logic = "AND"

    if view_id is not None:
        from cndb.plugins.tables.models import DataView

        dv = db.get(DataView, view_id)
        if dv is None or dv.table_id != dt.id:
            raise HTTPException(status_code=404, detail="视图不存在或不属于当前表")
        filters = dv.filters or None
        sorts = dv.sortings or None
        filter_logic = dv.filter_type or "AND"

    rows, _total = rec.list_rows(
        db.get_bind(),
        dt,
        limit=10000,
        db=db,
        filters=filters,
        sorts=sorts,
        filter_logic=filter_logic,
    )

    fmt = format.lower()
    if fmt == "json":
        body = transfer.export_rows_to_json(rows)
        return Response(content=body, media_type="application/json")
    if fmt == "csv":
        body = transfer.export_rows_to_csv(rows)
        return Response(content=body, media_type="text/csv")
    if fmt == "xlsx":
        body = transfer.export_rows_to_xlsx(rows)
        return Response(content=body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    raise HTTPException(status_code=400, detail=f"不支持的导出格式: {format}")


# ── 导入 ──────────────────────────────────────────────


@router.post("/import")
async def import_table(
    workspace_id: int,
    table_id: int,
    file: UploadFile,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)

    try:
        fmt = transfer.guess_format_from_filename(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content = await file.read()

    try:
        if fmt == "json":
            text, _enc = transfer.decode_bytes_auto(content)
            ids = transfer.import_rows_from_json(db.get_bind(), dt, text, db=db)
        elif fmt == "csv":
            text, _enc = transfer.decode_bytes_auto(content)
            ids = transfer.import_rows_from_csv(db.get_bind(), dt, text, db=db)
        elif fmt == "xlsx":
            ids = transfer.import_rows_from_xlsx(db.get_bind(), dt, content, db=db)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的格式: {fmt}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"imported": len(ids), "ids": ids}


# ── 异步导入 ──────────────────────────────────────────


@router.post("/import/async")
async def import_table_async(
    workspace_id: int,
    table_id: int,
    file: UploadFile,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    match_keys: Annotated[str | None, Form()] = None,
    unknown_cols_strategy: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """提交异步导入任务，返回 task_id.

    前端轮询 GET /import/async/{task_id} 查询进度.

    V2: 支持 match_keys（upsert 参考列，JSON 序列化字符串如 "[\"code\"]"）
    和 unknown_cols_strategy（未知列策略：drop / add_text_field）.
    """
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)

    try:
        fmt = transfer.guess_format_from_filename(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content = await file.read()
    task = create_import_task(
        db,
        table_id=dt.id,
        user_id=current_user.id if current_user else None,
        filename=file.filename or "upload",
        fmt=fmt,
        content=content,
        match_keys=json.loads(match_keys) if match_keys else None,
        unknown_cols_strategy=unknown_cols_strategy or "drop",
    )

    # 启动后台线程执行：用请求 session 的 bind 保证连接到同一个数据库
    from sqlalchemy.orm import sessionmaker

    engine = db.get_bind()
    bg_session_factory = sessionmaker(bind=engine)
    run_task_in_background(bg_session_factory, task.id)

    return {
        "task_id": task.id,
        "status": task.status,
        "progress": task.progress,
    }


@router.get("/import/async/{task_id}")
def get_import_task(
    workspace_id: int,
    table_id: int,
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """查询异步导入任务进度."""
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    task = db.get(ImportTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.table_id != dt.id:
        raise HTTPException(status_code=404, detail="任务不属于此表")

    result: dict[str, Any] = {
        "task_id": task.id,
        "status": task.status,
        "progress": task.progress,
        "filename": task.filename,
        "format": task.format,
        "total_rows": task.total_rows,
        "imported_rows": task.imported_rows,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }
    # 完成时返回导入的行 ID 列表
    if task.status == "done":
        result["result_ids"] = task.result_ids
    # 有校验报告时一并返回（preview 导入场景）
    if task.validation_report:
        import json as _json

        try:
            result["validation_report"] = _json.loads(task.validation_report)
        except Exception:
            result["validation_report_raw"] = task.validation_report
    return result


# ── 预览式导入（两阶段：analyze → confirm）────────────


@router.post("/import/analyze")
async def import_table_analyze(
    workspace_id: int,
    table_id: int,
    file: UploadFile,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    match_keys: Annotated[str | None, Form()] = None,
    unknown_cols_strategy: Annotated[str, Form()] = "drop",
) -> dict[str, Any]:
    """提交文件仅做解析+校验，返回 task_id（不写库）.

    任务进入 pending_validation → pending_confirm 状态，
    前端轮询 task_id 拿到 validation_report 后展示预览，
    用户点击确认 → POST /import/{task_id}/confirm 才真正落库.

    V2: 接受 match_keys (JSON 字符串, list[str]) 和 unknown_cols_strategy ("drop" / "add_text_field").
    """
    import json as _json

    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)

    try:
        fmt = transfer.guess_format_from_filename(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content = await file.read()

    # 解析 match_keys JSON 字符串
    parsed_keys: list[str] | None = None
    if match_keys:
        try:
            parsed = _json.loads(match_keys)
            if isinstance(parsed, list):
                parsed_keys = [str(x) for x in parsed]
        except _json.JSONDecodeError:
            # 也接受逗号分隔的简单形式
            parsed_keys = [k.strip() for k in match_keys.split(",") if k.strip()]

    strategy = unknown_cols_strategy or "drop"
    if strategy not in ("drop", "add_text_field"):
        raise HTTPException(status_code=400, detail=f"无效的 unknown_cols_strategy: {strategy}")

    task = create_import_task(
        db,
        table_id=dt.id,
        user_id=current_user.id if current_user else None,
        filename=file.filename or "upload",
        fmt=fmt,
        content=content,
        match_keys=parsed_keys,
        unknown_cols_strategy=strategy,
    )

    # 后台跑 analyze 阶段
    from sqlalchemy.orm import sessionmaker

    engine = db.get_bind()
    bg_session_factory = sessionmaker(bind=engine)
    run_task_in_background(bg_session_factory, task.id, phase="analyze")

    return {
        "task_id": task.id,
        "status": task.status,
        "progress": task.progress,
        "match_keys": parsed_keys or [],
        "unknown_cols_strategy": strategy,
        "hint": "等待 pending_confirm 状态后，可通过 GET /import/async/{task_id} 查看校验报告",
    }


@router.post("/import/{task_id}/confirm")
def import_table_confirm(
    workspace_id: int,
    table_id: int,
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    match_keys: str | None = None,
    unknown_cols_strategy: str | None = None,
) -> dict[str, Any]:
    """确认导入 — 把 pending_confirm 状态的任务推进到 running → done.

    V2: 允许前端在 confirm 阶段覆盖 analyze 时的 match_keys / unknown_cols_strategy.
        覆盖后会重新跑 analyze（因为 validation_report 里需要新的 upsert 分类）。
    """
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)

    task = db.get(ImportTask, task_id)
    if task is None or task.table_id != dt.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in ("pending_confirm", "pending_validation", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {task.status} 不允许确认（需 pending_confirm）",
        )

    # 覆盖参数（如果前端在 preview 阶段改了选择）
    import json as _json

    need_reanalyze = False
    if match_keys is not None:
        try:
            parsed = _json.loads(match_keys)
            if isinstance(parsed, list):
                new_keys = [str(x) for x in parsed]
            else:
                new_keys = [k.strip() for k in match_keys.split(",") if k.strip()]
        except _json.JSONDecodeError:
            new_keys = [k.strip() for k in match_keys.split(",") if k.strip()]
        if new_keys != list(task.match_keys or []):
            task.match_keys = new_keys
            need_reanalyze = True

    if (
        unknown_cols_strategy is not None
        and unknown_cols_strategy in ("drop", "add_text_field")
        and unknown_cols_strategy != task.unknown_cols_strategy
    ):
        task.unknown_cols_strategy = unknown_cols_strategy
        need_reanalyze = True

    if need_reanalyze:
        # 覆盖后重新 commit（execute 阶段 Importer 会重新 analyze 以拿到新的 validation_report）
        db.commit()

    # 后台跑 execute 阶段
    from sqlalchemy.orm import sessionmaker

    engine = db.get_bind()
    bg_session_factory = sessionmaker(bind=engine)
    run_task_in_background(bg_session_factory, task.id, phase="execute")

    return {
        "task_id": task.id,
        "status": "running",
        "message": "已提交执行，请轮询 GET /import/async/{task_id} 查看结果",
    }


@router.post("/import/{task_id}/reanalyze")
def import_table_reanalyze(
    workspace_id: int,
    table_id: int,
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    match_keys: str | None = None,
    unknown_cols_strategy: str | None = None,
) -> dict[str, Any]:
    """用新参数重新跑 analyze（让用户在 preview 阶段改参考列/未知列策略后重算 diff）.

    适用场景：用户先上传文件看全量数据，再选参考列，重新 DIFF 得到 new/update 分类.
    任务必须处于 pending_confirm 或 pending_validation 状态.
    """
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)

    task = db.get(ImportTask, task_id)
    if task is None or task.table_id != dt.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in ("pending_confirm", "pending_validation"):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {task.status} 不允许重新分析（需 pending_confirm）",
        )

    # 解析参数（与 confirm 保持一致的 JSON 字符串/逗号分隔两种形式）
    import json as _json

    if match_keys is not None:
        try:
            parsed = _json.loads(match_keys)
            if isinstance(parsed, list):
                new_keys = [str(x) for x in parsed]
            else:
                new_keys = [k.strip() for k in match_keys.split(",") if k.strip()]
        except _json.JSONDecodeError:
            new_keys = [k.strip() for k in match_keys.split(",") if k.strip()]
        task.match_keys = new_keys

    if unknown_cols_strategy is not None and unknown_cols_strategy in ("drop", "add_text_field"):
        task.unknown_cols_strategy = unknown_cols_strategy

    task.validation_report = ""  # 清空旧报告
    task.progress = 0
    task.error_message = ""
    db.commit()

    # 后台跑 reanalyze 阶段（复用 run_task_in_background 的 phase="reanalyze"）
    from sqlalchemy.orm import sessionmaker

    engine = db.get_bind()
    bg_session_factory = sessionmaker(bind=engine)
    run_task_in_background(bg_session_factory, task.id, phase="reanalyze")

    return {
        "task_id": task.id,
        "status": task.status,
        "match_keys": list(task.match_keys or []),
        "unknown_cols_strategy": task.unknown_cols_strategy,
        "message": "已提交重新分析，请轮询 GET /import/async/{task_id} 查看新报告",
    }


@router.get("/import/{task_id}/failed-rows")
def download_failed_rows(
    workspace_id: int,
    table_id: int,
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    *,
    format: str = "csv",
) -> Response:
    """下载失败行文件（CSV / XLSX / JSON）."""
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    task = db.get(ImportTask, task_id)
    if task is None or task.table_id != dt.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task.validation_report:
        raise HTTPException(status_code=400, detail="任务尚未完成校验")

    # 重新跑一次 analyze 拿到完整 ValidationResult 列表（因为 analysis 结果没存）
    # 或者从 validation_report 里只能拿到 errors/warnings 明细，没有 values
    # 实际上 Importer.execute 内部已经过滤了，validation_report 里有所有 row_number
    # 但要导出完整的 values，需要重新 parse + validate
    from cndb.plugins.tables.failed_row_exporter import FailedRowExporter
    from cndb.plugins.tables.importer import Importer

    engine = db.get_bind()
    importer = Importer(engine, db, dt)
    # 用空的 content 不行，但我们有 task.file_content —— 只需要重新 analyze
    import base64 as _b64

    raw: bytes | str = _b64.b64decode(task.file_content) if task.format == "xlsx" else task.file_content
    analysis = importer.analyze(raw, task.format, match_keys=list(task.match_keys) if task.match_keys else None)

    content_bytes = FailedRowExporter.export_failed_rows(analysis.results, format=format)

    # 构造 HTTP 响应
    mime_map = {
        "csv": "text/csv; charset=utf-8",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "json": "application/json",
    }
    ext_map = {"csv": ".csv", "xlsx": ".xlsx", "json": ".json"}
    filename = f"{dt.name}-failed-rows-{task.id}{ext_map.get(format, '.csv')}"

    if isinstance(content_bytes, str):
        content_bytes = content_bytes.encode("utf-8")

    return Response(
        content=content_bytes,
        media_type=mime_map.get(format, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── 扩展现有查询端点返回 validation_report ────────────


def _augment_task_result(result: dict[str, Any], task: ImportTask) -> dict[str, Any]:
    """为 GET /import/async/{task_id} 返回值追加 validation_report."""
    if task.validation_report:
        import json as _json

        try:
            result["validation_report"] = _json.loads(task.validation_report)
        except Exception:
            result["validation_report_raw"] = task.validation_report
    return result


# （不破坏向后兼容：只新增字段）
