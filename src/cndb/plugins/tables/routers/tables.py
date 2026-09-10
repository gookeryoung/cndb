"""数据表元数据路由."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.ddl import create_table as ddl_create
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.schemas import (
    TableCreate,
    TableDetailResponse,
    TableResponse,
    TableUpdate,
)
from cndb.plugins.workspaces.models import ROLE_RANK, Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role

router = APIRouter(prefix="/{workspace_id}/tables", tags=["tables"])


def _check_table_permission(workspace_id: int, user: User, db: Session, min_role: WorkspaceRole) -> None:
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    role = get_member_role(user, ws, db)
    if role is None or ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise HTTPException(status_code=403, detail="权限不足")


def _get_table_or_404(table_id: int, workspace_id: int, db: Session) -> DataTable:
    dt = db.query(DataTable).filter(DataTable.id == table_id, DataTable.workspace_id == workspace_id).first()
    if dt is None:
        raise HTTPException(status_code=404, detail="表不存在")
    return dt


@router.post("", response_model=TableResponse, status_code=status.HTTP_201_CREATED)
def create_table(
    workspace_id: int,
    payload: TableCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataTable:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    dt = DataTable(workspace_id=workspace_id, name=payload.name, description=payload.description)
    dt.ensure_db_name()
    db.add(dt)
    db.commit()
    db.refresh(dt)

    # 执行物理建表
    ddl_create(db.get_bind(), dt)
    return dt


@router.get("", response_model=list[TableResponse])
def list_tables(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_trashed: bool = False,
) -> list[DataTable]:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    query = db.query(DataTable).filter(DataTable.workspace_id == workspace_id)
    if not include_trashed:
        query = query.filter(DataTable.trashed == False)  # noqa: E712
    return query.order_by(DataTable.order, DataTable.id).all()


@router.get("/{table_id}", response_model=TableDetailResponse)
def get_table(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataTable:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    dt = _get_table_or_404(table_id, workspace_id, db)
    return dt


@router.patch("/{table_id}", response_model=TableResponse)
def update_table(
    workspace_id: int,
    table_id: int,
    payload: TableUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataTable:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    dt = _get_table_or_404(table_id, workspace_id, db)
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(dt, key, value)
    db.commit()
    db.refresh(dt)
    return dt


@router.delete("/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_table(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.OWNER)
    dt = _get_table_or_404(table_id, workspace_id, db)
    dt.trashed = True
    db.commit()
