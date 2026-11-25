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
from cndb.plugins.tables.schemas import BulkDeleteRequest, BulkUpdateRequest
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core.access import TableAction, check_action, get_table_or_404
from cndb.plugins.workspaces.permissions import raise_permission_denied

logger = logging.getLogger(__name__)

router = APIRouter()


def _dispatch_record_updated(
    db: Session,
    table: Any,
    *,
    action: str,
    row_ids: list[int],
    count: int,
) -> None:
    """记录批量变更后触发流水线（ADR 0076 P1；尽力而为，失败不影响响应）."""
    try:
        from cndb.plugins.pipeline.services.triggers import (
            EVENT_RECORD_UPDATED,
            dispatch_event,
        )

        dispatch_event(
            db,
            EVENT_RECORD_UPDATED,
            workspace_id=table.workspace_id,
            payload={
                "table_id": table.id,
                "table_name": table.name,
                "action": action,
                "row_ids": row_ids,
                "count": count,
            },
        )
    except Exception:
        logger.warning("记录变更事件分发失败，跳过", exc_info=True)


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

    _dispatch_record_updated(db, dt, action="created", row_ids=list(ids), count=len(ids))
    return {"created": len(ids), "ids": ids}


#: 跨页全选单次最多处理的命中行数（超出要求收窄筛选，避免一次删掉整表）
SELECT_ALL_MAX_ROWS = 10_000


def _resolve_bulk_row_ids(
    payload: BulkDeleteRequest | BulkUpdateRequest,
    dt: Any,
    db: Session,
    current_user: User,
) -> list[int]:
    """解析批量操作的 row_ids：直传，或按筛选条件（跨页全选）在服务端展开.

    - `select_all=False` → 直接用 `row_ids`（缺省即 400）；
    - `select_all=True` → 按 `filters` / `filter_logic` 走列表读路径（行级权限 + 软删同源）
      取出命中行 id；命中超过 `SELECT_ALL_MAX_ROWS` → 400 要求收窄。
    """
    from cndb.plugins.tables.services.core import records as rec

    if not payload.select_all:
        if not payload.row_ids:
            raise HTTPException(status_code=400, detail="row_ids 不能为空（或改用 select_all + filters）")
        return [int(rid) for rid in payload.row_ids]

    rows, total = rec.list_rows(
        db.get_bind(),
        dt,
        filters=payload.filters or None,
        filter_logic=payload.filter_logic,
        limit=0,
        db=db,
        user=current_user,
    )
    if total > SELECT_ALL_MAX_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"当前筛选命中 {total} 行，超过单次批量操作上限 {SELECT_ALL_MAX_ROWS} 行，请收窄筛选后重试",
        )
    return [int(row["id"]) for row in rows if row.get("id") is not None]


# ── 批量删行 ───────────────────────────────────────────


@router.post("/records/bulk-delete", status_code=status.HTTP_200_OK, response_model=None)
def bulk_delete_records(
    workspace_id: int,
    table_id: int,
    payload: BulkDeleteRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any] | JSONResponse:
    """批量删行：可直编者直接删除；否则生成含多个 delete item 的修改申请（202）.

    `select_all=True` 时按筛选条件在服务端展开目标行（跨页全选），上限见 `SELECT_ALL_MAX_ROWS`。
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    row_ids = _resolve_bulk_row_ids(payload, dt, db, current_user)

    if not cr_services.can_write_directly(db, dt, current_user):
        cr = cr_services.create_batch_delete_request(db, dt, current_user, row_ids)
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "change_request": cr_services.serialize_request(cr),
                "created_items": len(cr.items),
            },
        )

    if not check_action(db, dt, current_user, TableAction.EDIT_RECORDS):
        raise_permission_denied(db, dt.workspace, current_user, scope="表级")

    deleted = rec.bulk_delete(db.get_bind(), dt, row_ids, db=db, user=current_user)
    if deleted:
        _dispatch_record_updated(
            db,
            dt,
            action="deleted",
            row_ids=list(row_ids),
            count=deleted,
        )
    return {"deleted": deleted}


# ── 批量改行 ───────────────────────────────────────────


@router.post("/records/bulk-update", status_code=status.HTTP_200_OK)
def bulk_update_records(
    workspace_id: int,
    table_id: int,
    payload: BulkUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    """批量改行：`select_all=True` 时按筛选条件在服务端展开目标行（跨页全选）.

    上限与批量删除同口径（`SELECT_ALL_MAX_ROWS`），且展开走调用者读范围 —— 看不到的行不会被改。
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)
    values = payload.values or {}
    if not values:
        raise HTTPException(status_code=400, detail="values 不能为空")
    row_ids = _resolve_bulk_row_ids(payload, dt, db, current_user)

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

    if updated:
        _dispatch_record_updated(
            db,
            dt,
            action="updated",
            row_ids=list(row_ids),
            count=updated,
        )
    return {"updated": updated}


__all__ = ["router"]
