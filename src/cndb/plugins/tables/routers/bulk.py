"""批量操作 + 导入导出路由."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
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
) -> Response:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    dt = _get_table_or_404(table_id, workspace_id, db)
    rows, _total = rec.list_rows(db.get_bind(), dt, limit=10000, db=db)

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
) -> dict[str, Any]:
    """提交异步导入任务，返回 task_id.

    前端轮询 GET /import/async/{task_id} 查询进度.
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
    return result
