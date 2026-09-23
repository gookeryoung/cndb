"""行数据路由."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.schemas import (
    RecordCreate,
    RecordListRequest,
    RecordListResponse,
    RecordUpdate,
)
from cndb.plugins.tables.services.core.access import TableAction, get_table_or_404
from cndb.plugins.tables.services.core.records import (
    create_row,
    delete_row,
    get_row,
    list_rows,
    restore_row,
    trash_row,
    update_row,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/records", tags=["records"])


def _list_response(
    db: Session,
    dt: DataTable,
    user: User,
    *,
    filters: list[dict[str, Any]] | None,
    filter_logic: str,
    sorts: list[dict[str, Any]] | None,
    limit: int,
    offset: int,
    include_trashed: bool,
) -> RecordListResponse:
    """调用 list_rows 并统一错误映射（ValueError→400，其余→500），GET/POST 列表端点共用."""
    try:
        rows, total = list_rows(
            db.get_bind(),
            dt,
            filters=filters,
            filter_logic=filter_logic,
            sorts=sorts,
            limit=limit,
            offset=offset,
            include_trashed=include_trashed,
            db=db,
            user=user,
        )
    except ValueError as exc:
        # 业务语义错误（未知操作符、非法字段等）— 客户端可修正
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # SQLAlchemy / 数据库等运行时错误 — 记录日志后统一返回 500
        logger.exception("list_rows 运行时异常")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RecordListResponse(rows=rows, total=total, limit=limit, offset=offset)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_record(
    workspace_id: int,
    table_id: int,
    payload: RecordCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)

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
    """GET /records - 前端友好的列表端点.

    sorts / filters 为 URL 编码的 JSON 字符串. 解析失败时降级为空列表
    而非报错，确保分页等基础功能不被参数格式阻断.
    """
    import json as _json

    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    def _parse(s: str | None, label: str) -> list[dict[str, Any]] | None:
        if not s:
            return None
        try:
            v = _json.loads(s)
        except _json.JSONDecodeError:
            logger.warning("%s JSON 解析失败，降级为空", label)
            return None
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        return None

    return _list_response(
        db,
        dt,
        current_user,
        filters=_parse(filters, "filters"),
        filter_logic=filter_logic,
        sorts=_parse(sorts, "sorts"),
        limit=limit,
        offset=offset,
        include_trashed=include_trashed,
    )


@router.post("/list", response_model=RecordListResponse)
def list_records(
    workspace_id: int,
    table_id: int,
    payload: RecordListRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_trashed: bool = Query(default=False),
) -> RecordListResponse:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    return _list_response(
        db,
        dt,
        current_user,
        filters=payload.filters if payload.filters else None,
        filter_logic=payload.filter_logic,
        sorts=payload.sorts if payload.sorts else None,
        limit=payload.limit,
        offset=payload.offset,
        include_trashed=include_trashed,
    )


@router.get("/{record_id}")
def get_record(
    workspace_id: int,
    table_id: int,
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
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
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)

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
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)

    if soft:
        ok = trash_row(db.get_bind(), dt, record_id, db=db)
    else:
        ok = delete_row(db.get_bind(), dt, record_id, db=db)

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
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)
    ok = restore_row(db.get_bind(), dt, record_id, db=db)
    if not ok:
        raise HTTPException(status_code=404, detail="行不存在或未在回收站中")
    row = get_row(db.get_bind(), dt, record_id, db=db, user=current_user)
    if row is None:  # pragma: no cover - 防御性
        raise HTTPException(status_code=500, detail="恢复后读取失败")
    return row
