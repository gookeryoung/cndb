"""批量记录端点：批量建行 / 批量删除 / 批量更新."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.change_requests import services as cr_services
from cndb.plugins.tables.schemas import BulkDeleteRequest
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core.access import TableAction, check_action, get_table_or_404

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 批量建行 ───────────────────────────────────────────


@router.post("/records/bulk-create", status_code=status.HTTP_201_CREATED)
def bulk_create_records(
    workspace_id: int,
    table_id: int,
    payload: dict[str, Any],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)
    rows = payload.get("rows", [])
    if not rows:
        raise HTTPException(status_code=400, detail="rows 不能为空")
    # 兼容两种格式：直接 values 数组 或 {values} 包装
    normalized = [r.get("values", r) if isinstance(r, dict) else r for r in rows]

    # 导入前预填充 + 导入后同步 select/multiselect options
    try:
        from cndb.plugins.tables.services.fields.field_ops import (
            prefill_select_options_from_rows,
            sync_select_options_from_table,
        )

        if normalized:
            prefill_select_options_from_rows(db, dt, normalized)
    except Exception:
        logger.debug("导入前预填充 select options 失败，跳过", exc_info=True)

    ids: list[int]
    try:
        ids = rec.bulk_create(db.get_bind(), dt, normalized, db=db)
    except ValueError as exc:
        # link 目标预校验失败（如关联行不存在）——返回 400 而非 500
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        from cndb.plugins.tables.services.fields.field_ops import sync_select_options_from_table

        sync_select_options_from_table(db, dt)
    except Exception:
        logger.debug("导入后同步 select options 失败，跳过", exc_info=True)

    return {"created": len(ids), "ids": ids}


# ── 批量删行 ───────────────────────────────────────────


@router.post("/records/bulk-delete", status_code=status.HTTP_200_OK, response_model=None)
def bulk_delete_records(
    workspace_id: int,
    table_id: int,
    payload: BulkDeleteRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any] | JSONResponse:
    """批量删行：可直编者直接删除；否则生成含多个 delete item 的修改申请（202）."""
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    if not cr_services.can_write_directly(db, dt, current_user):
        cr = cr_services.create_batch_delete_request(db, dt, current_user, payload.row_ids)
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "change_request": cr_services.serialize_request(cr),
                "created_items": len(cr.items),
            },
        )

    if not check_action(db, dt, current_user, TableAction.EDIT_RECORDS):
        raise HTTPException(status_code=403, detail="表级权限不足")

    deleted = rec.bulk_delete(db.get_bind(), dt, payload.row_ids, db=db, user=current_user)
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
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)
    row_ids = payload.get("row_ids", [])
    values = payload.get("values", {})
    if not row_ids:
        raise HTTPException(status_code=400, detail="row_ids 不能为空")
    if not values:
        raise HTTPException(status_code=400, detail="values 不能为空")

    # 更新前预填充 select/multiselect options（让新值的校验能通过）
    try:
        from cndb.plugins.tables.services.fields.field_ops import prefill_select_options_from_rows

        # values 是 {"field_name": new_value} 格式，转换成 rows=[values] 让 prefill 能提取
        prefill_select_options_from_rows(db, dt, [values])
    except Exception:
        logger.debug("更新前预填充 select options 失败，跳过", exc_info=True)

    updated: int
    try:
        updated = rec.bulk_update(db.get_bind(), dt, row_ids, values, db=db, user=current_user)
    except ValueError as exc:
        # link 目标预校验失败（如关联行不存在）——返回 400 而非 500
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 更新后同步 select/multiselect options（兜底：物理表中可能有其他行的值未覆盖）
    try:
        from cndb.plugins.tables.services.fields.field_ops import sync_select_options_from_table

        sync_select_options_from_table(db, dt)
    except Exception:
        logger.debug("更新后同步 select options 失败，跳过", exc_info=True)

    return {"updated": updated}


__all__ = ["router"]
