"""视图管理路由."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataView
from cndb.plugins.tables.routers.tables import _check_table_permission, _get_table_or_404
from cndb.plugins.tables.schemas import ViewCreate, ViewResponse, ViewUpdate
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/views", tags=["views"])


@router.post("", response_model=ViewResponse, status_code=status.HTTP_201_CREATED)
def create_view(
    workspace_id: int,
    table_id: int,
    payload: ViewCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataView:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    _get_table_or_404(table_id, workspace_id, db)

    # 同表视图名唯一
    existing = db.query(DataView).filter(DataView.table_id == table_id, DataView.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="视图名已存在")

    # 如果标记为 default，先把同表其他视图的 default 清掉
    if payload.is_default:
        db.query(DataView).filter(DataView.table_id == table_id).update({"is_default": False})

    dv = DataView(
        table_id=table_id,
        owner_id=current_user.id,
        name=payload.name,
        view_type=payload.view_type,
        filter_type=payload.filter_type,
        filters=payload.filters,
        sortings=payload.sortings,
        field_options=payload.field_options,
        field_order=payload.field_order,
        view_options=payload.view_options,
        is_default=payload.is_default,
        order=payload.order,
    )
    db.add(dv)
    db.commit()
    db.refresh(dv)
    return dv


@router.get("", response_model=list[ViewResponse])
def list_views(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DataView]:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    _get_table_or_404(table_id, workspace_id, db)
    return db.query(DataView).filter(DataView.table_id == table_id).order_by(DataView.order, DataView.id).all()


@router.get("/{view_id}", response_model=ViewResponse)
def get_view(
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataView:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    _get_table_or_404(table_id, workspace_id, db)
    dv = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == table_id).first()
    if dv is None:
        raise HTTPException(status_code=404, detail="视图不存在")
    return dv


@router.patch("/{view_id}", response_model=ViewResponse)
def update_view(  # noqa: PLR0913, PLR0917
    workspace_id: int,
    table_id: int,
    view_id: int,
    payload: ViewUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataView:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    _get_table_or_404(table_id, workspace_id, db)
    dv = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == table_id).first()
    if dv is None:
        raise HTTPException(status_code=404, detail="视图不存在")

    # 如果标记为 default，先把同表其他视图的 default 清掉
    if payload.is_default:
        db.query(DataView).filter(DataView.table_id == table_id).update({"is_default": False})

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(dv, key, value)
    db.commit()
    db.refresh(dv)
    return dv


@router.delete("/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_view(
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    _get_table_or_404(table_id, workspace_id, db)
    dv = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == table_id).first()
    if dv is None:
        raise HTTPException(status_code=404, detail="视图不存在")
    db.delete(dv)
    db.commit()


# ── 视图驱动的行查询 ──────────────────────────────────


@router.get("/{view_id}/rows")
def get_view_rows(  # noqa: PLR0913, PLR0917
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    """按视图的 filters + sortings 查询行."""
    from cndb.plugins.tables import records as rec

    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    dt = _get_table_or_404(table_id, workspace_id, db)
    dv = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == table_id).first()
    if dv is None:
        raise HTTPException(status_code=404, detail="视图不存在")

    rows, total = rec.list_rows(
        db.get_bind(),
        dt,
        filters=dv.filters or None,
        filter_logic=dv.filter_type,
        sorts=dv.sortings or None,
        limit=limit,
        offset=offset,
    )
    return {"rows": rows, "total": total, "view_id": view_id}


@router.get("/{view_id}/kanban")
def get_view_kanban(  # noqa: PLR0913, PLR0917
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=500, ge=1, le=10000),
) -> dict[str, object]:
    """看板视图：按 view_options.group_field 分组返回行."""
    from collections import defaultdict

    from cndb.plugins.tables import records as rec

    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    dt = _get_table_or_404(table_id, workspace_id, db)
    dv = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == table_id).first()
    if dv is None:
        raise HTTPException(status_code=404, detail="视图不存在")

    group_field = dv.view_options.get("group_field") if dv.view_options else None
    if not group_field:
        raise HTTPException(status_code=400, detail="看板视图需配置 group_field")

    rows, total = rec.list_rows(
        db.get_bind(),
        dt,
        filters=dv.filters or None,
        filter_logic=dv.filter_type,
        sorts=dv.sortings or None,
        limit=limit,
    )
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        key = str(row.get(group_field) or "未分组")
        grouped[key].append(row)

    return {"columns": dict(grouped), "total": total, "group_field": group_field}


@router.get("/{view_id}/calendar")
def get_view_calendar(  # noqa: PLR0913, PLR0917
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    start: str | None = Query(default=None, description="ISO 日期起始 (YYYY-MM-DD)"),
    end: str | None = Query(default=None, description="ISO 日期结束"),
    limit: int = Query(default=500, ge=1, le=10000),
) -> dict[str, object]:
    """日历视图：按日期字段过滤并返回行列表."""
    from cndb.plugins.tables import records as rec

    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    dt = _get_table_or_404(table_id, workspace_id, db)
    dv = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == table_id).first()
    if dv is None:
        raise HTTPException(status_code=404, detail="视图不存在")

    start_field = dv.view_options.get("start_field") if dv.view_options else None
    if not start_field:
        raise HTTPException(status_code=400, detail="日历视图需配置 start_field")

    filters: list[dict[str, object]] = list(dv.filters or [])
    if start:
        filters.append({"field_name": start_field, "op": ">=", "value": start})
    if end:
        filters.append({"field_name": start_field, "op": "<=", "value": end})

    sorts = list(dv.sortings or [])
    sorts.append({"field_name": start_field, "direction": "asc"})

    rows, total = rec.list_rows(
        db.get_bind(),
        dt,
        filters=filters,
        filter_logic=dv.filter_type,
        sorts=sorts,
        limit=limit,
    )
    return {"rows": rows, "total": total, "start_field": start_field}
