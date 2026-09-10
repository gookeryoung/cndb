"""视图管理路由."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
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
