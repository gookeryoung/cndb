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
from cndb.plugins.tables.import_tasks import create_import_task, run_task_in_background
from cndb.plugins.tables.models import ImportTask
from cndb.plugins.tables.routers.tables import _check_table_permission, _get_table_or_404
from cndb.plugins.tables.schemas import BulkDeleteRequest
from cndb.plugins.workspaces.models import WorkspaceRole

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
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    dt = _get_table_or_404(table_id, workspace_id, db)
    rows = payload.get("rows", [])
    if not rows:
        raise HTTPException(status_code=400, detail="rows 不能为空")
    # 兼容两种格式：直接 values 数组 或 {values} 包装
    normalized = [r.get("values", r) if isinstance(r, dict) else r for r in rows]
    ids = rec.bulk_create(db.get_bind(), dt, normalized, db=db)
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
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    dt = _get_table_or_404(table_id, workspace_id, db)
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
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    dt = _get_table_or_404(table_id, workspace_id, db)
    row_ids = payload.get("row_ids", [])
    values = payload.get("values", {})
    if not row_ids:
        raise HTTPException(status_code=400, detail="row_ids 不能为空")
    if not values:
        raise HTTPException(status_code=400, detail="values 不能为空")
    updated = rec.bulk_update(db.get_bind(), dt, row_ids, values, db=db)
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
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    dt = _get_table_or_404(table_id, workspace_id, db)

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
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    dt = _get_table_or_404(table_id, workspace_id, db)

    try:
        fmt = transfer.guess_format_from_filename(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content = await file.read()

    try:
        if fmt == "json":
            ids = transfer.import_rows_from_json(db.get_bind(), dt, content.decode("utf-8"))
        elif fmt == "csv":
            ids = transfer.import_rows_from_csv(db.get_bind(), dt, content.decode("utf-8"))
        elif fmt == "xlsx":
            ids = transfer.import_rows_from_xlsx(db.get_bind(), dt, content)
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
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    dt = _get_table_or_404(table_id, workspace_id, db)

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
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    dt = _get_table_or_404(table_id, workspace_id, db)

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
    unknown_cols_strategy: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """提交文件仅做解析+校验，返回 task_id（不写库）.

    任务进入 pending_validation → pending_confirm 状态，
    前端轮询 task_id 拿到 validation_report 后展示预览，
    用户点击确认 → POST /import/{task_id}/confirm 才真正落库.

    V2: 支持 match_keys（upsert 参考列，JSON 序列化的字符串数组如 "[\"code\"]"）
    和 unknown_cols_strategy（未知列策略：drop / add_text_field）.
    """
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    dt = _get_table_or_404(table_id, workspace_id, db)

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

    # 后台跑 analyze 阶段
    from sqlalchemy.orm import sessionmaker

    engine = db.get_bind()
    bg_session_factory = sessionmaker(bind=engine)
    run_task_in_background(bg_session_factory, task.id, phase="analyze")

    return {
        "task_id": task.id,
        "status": task.status,
        "progress": task.progress,
        "hint": "等待 pending_confirm 状态后，可通过 GET /import/async/{task_id} 查看校验报告",
    }


@router.post("/import/{task_id}/confirm")
def import_table_confirm(
    workspace_id: int,
    table_id: int,
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """确认导入 — 把 pending_confirm 状态的任务推进到 running → done.

    成功返回导入的行数和 result_ids.
    """
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    dt = _get_table_or_404(table_id, workspace_id, db)

    task = db.get(ImportTask, task_id)
    if task is None or task.table_id != dt.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in ("pending_confirm", "pending_validation", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {task.status} 不允许确认（需 pending_confirm）",
        )

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
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    dt = _get_table_or_404(table_id, workspace_id, db)

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
    analysis = importer.analyze(raw, task.format)

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
