"""行数据路由."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.access import TableAction
from cndb.plugins.tables.records import (
    create_row,
    delete_row,
    get_row,
    list_rows,
    restore_row,
    trash_row,
    update_row,
)
from cndb.plugins.tables.routers.tables import _get_table_or_404
from cndb.plugins.tables.schemas import (
    RecordCreate,
    RecordListRequest,
    RecordListResponse,
    RecordUpdate,
)

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/records", tags=["records"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_record(
    workspace_id: int,
    table_id: int,
    payload: RecordCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)

    try:
        row = create_row(db.get_bind(), dt, payload.values, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if row is None:
        raise HTTPException(status_code=500, detail="创建失败")
    return row


@router.get("", response_model=RecordListResponse)
def list_records_get(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=5000),
    filters: str | None = Query(default=None),
    sorts: str | None = Query(default=None),
    filter_logic: str = Query(default="AND", pattern="^(AND|OR)$"),
    include_trashed: bool = Query(default=False),
) -> RecordListResponse:
    """GET /records - 前端友好的列表端点."""
    import json as _json

    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    def _parse(s: str | None):
        if not s:
            return None
        try:
            return _json.loads(s)
        except _json.JSONDecodeError:
            return None

    try:
        rows, total = list_rows(
            db.get_bind(),
            dt,
            filters=_parse(filters),
            filter_logic=filter_logic,
            sorts=_parse(sorts),
            limit=limit,
            offset=offset,
            include_trashed=include_trashed,
            db=db,
            user=current_user,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RecordListResponse(rows=rows, total=total, limit=limit, offset=offset)


@router.post("/list", response_model=RecordListResponse)
def list_records(
    workspace_id: int,
    table_id: int,
    payload: RecordListRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_trashed: bool = Query(default=False),
) -> RecordListResponse:
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    try:
        rows, total = list_rows(
            db.get_bind(),
            dt,
            filters=payload.filters,
            filter_logic=payload.filter_logic,
            sorts=payload.sorts,
            limit=payload.limit,
            offset=payload.offset,
            include_trashed=include_trashed,
            db=db,
            user=current_user,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RecordListResponse(
        rows=rows,
        total=total,
        limit=payload.limit,
        offset=payload.offset,
    )


@router.get("/{record_id}")
def get_record(
    workspace_id: int,
    table_id: int,
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    row = get_row(db.get_bind(), dt, record_id, db=db, user=current_user)
    if row is None:
        raise HTTPException(status_code=404, detail="行不存在")
    return row


@router.patch("/{record_id}")
def update_record(
    workspace_id: int,
    table_id: int,
    record_id: int,
    payload: RecordUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)

    try:
        row = update_row(db.get_bind(), dt, record_id, payload.values, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if row is None:
        raise HTTPException(status_code=404, detail="行不存在")
    return row


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_record(
    workspace_id: int,
    table_id: int,
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    soft: bool = Query(default=True, description="软删除 vs 硬删除"),
) -> None:
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)

    if soft:
        ok = trash_row(db.get_bind(), dt, record_id, db=db)
    else:
        ok = delete_row(db.get_bind(), dt, record_id)

    if not ok:
        raise HTTPException(status_code=404, detail="行不存在")


@router.post("/{record_id}/restore", status_code=status.HTTP_200_OK)
def restore_record(
    workspace_id: int,
    table_id: int,
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)
    ok = restore_row(db.get_bind(), dt, record_id, db=db)
    if not ok:
        raise HTTPException(status_code=404, detail="行不存在或未在回收站中")
    row = get_row(db.get_bind(), dt, record_id, db=db, user=current_user)
    if row is None:  # pragma: no cover - 防御性
        raise HTTPException(status_code=500, detail="恢复后读取失败")
    return row
