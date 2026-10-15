"""表级权限管理路由."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import TablePermission
from cndb.plugins.tables.schemas import PermissionCreate, PermissionResponse, PermissionUpdate
from cndb.plugins.tables.services.core.access import TableAction, get_table_or_404

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/permissions", tags=["permissions"])


def _get_or_create_permission(db: Session, table_id: int) -> TablePermission:
    """获取已有的 TablePermission，不存在则创建."""
    tp = db.query(TablePermission).filter(TablePermission.table_id == table_id).first()
    if tp is None:
        tp = TablePermission(table_id=table_id)
        db.add(tp)
        db.flush()
    return tp


def _invalidate_table_list_cache(workspace_id: int) -> None:
    """权限/成员变更后失效表列表缓存.

    表列表按 TableAction.READ 过滤，缓存按用户隔离；但权限变更必须让**所有用户**的
    列表缓存失效，否则收紧权限后别人仍能从缓存里看到旧列表（5s TTL 兜底但不该依赖它）。
    """
    from cndb.core.cache import cache_key, list_cache

    list_cache.clear(cache_key("tables", workspace_id))


@router.get("", response_model=PermissionResponse)
def get_permission(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TablePermission:
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    return _get_or_create_permission(db, table_id)


@router.put("", response_model=PermissionResponse)
def upsert_permission(
    workspace_id: int,
    table_id: int,
    payload: PermissionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TablePermission:
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)
    tp = _get_or_create_permission(db, table_id)

    tp.read_role = payload.read_role
    tp.edit_records_role = payload.edit_records_role
    tp.edit_views_role = payload.edit_views_role
    tp.edit_schema_role = payload.edit_schema_role
    tp.manage_data_role = payload.manage_data_role
    tp.hidden_fields = payload.hidden_fields
    tp.row_filters = payload.row_filters
    tp.row_filter_type = payload.row_filter_type
    db.commit()
    _invalidate_table_list_cache(workspace_id)
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
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)
    tp = _get_or_create_permission(db, table_id)

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(tp, key, value)
    db.commit()
    _invalidate_table_list_cache(workspace_id)
    db.refresh(tp)
    return tp
