"""表级权限管理路由."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import TablePermission
from cndb.plugins.tables.routers.tables import _check_table_permission, _get_table_or_404
from cndb.plugins.tables.schemas import PermissionCreate, PermissionResponse, PermissionUpdate
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/permissions", tags=["permissions"])


def _get_or_create_permission(db: Session, table_id: int) -> TablePermission:
    """获取已有的 TablePermission，不存在则创建."""
    tp = db.query(TablePermission).filter(TablePermission.table_id == table_id).first()
    if tp is None:
        tp = TablePermission(table_id=table_id)
        db.add(tp)
        db.flush()
    return tp


@router.get("", response_model=PermissionResponse)
def get_permission(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TablePermission:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    _get_table_or_404(table_id, workspace_id, db)
    return _get_or_create_permission(db, table_id)


@router.put("", response_model=PermissionResponse)
def upsert_permission(
    workspace_id: int,
    table_id: int,
    payload: PermissionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TablePermission:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    _get_table_or_404(table_id, workspace_id, db)
    tp = _get_or_create_permission(db, table_id)

    tp.read_role = payload.read_role
    tp.edit_records_role = payload.edit_records_role
    tp.edit_views_role = payload.edit_views_role
    tp.edit_schema_role = payload.edit_schema_role
    tp.comment_role = payload.comment_role
    tp.hidden_fields = payload.hidden_fields
    tp.row_filters = payload.row_filters
    tp.row_filter_type = payload.row_filter_type
    db.commit()
    db.refresh(tp)
    return tp


@router.patch("", response_model=PermissionResponse)
def patch_permission(
    workspace_id: int,
    table_id: int,
    payload: PermissionUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TablePermission:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    _get_table_or_404(table_id, workspace_id, db)
    tp = _get_or_create_permission(db, table_id)

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(tp, key, value)
    db.commit()
    db.refresh(tp)
    return tp
