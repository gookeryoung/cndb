"""字段管理路由."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.ddl import add_column, drop_column
from cndb.plugins.tables.field_types import LinkFieldConfig, default_registry
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.routers.tables import _check_table_permission, _get_table_or_404
from cndb.plugins.tables.schemas import FieldCreate, FieldResponse, FieldUpdate
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/fields", tags=["fields"])


def _validate_link_config(payload_config: dict[str, Any], db: Session) -> dict[str, Any]:
    """link 字段 config 保存期校验：target_table_id 为正整数且目标表存在."""
    try:
        cfg = LinkFieldConfig(**(payload_config or {}))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"link 字段 config 校验失败: {exc}") from exc
    target = db.get(DataTable, cfg.target_table_id)
    if target is None or target.trashed:
        raise HTTPException(status_code=400, detail=f"关联目标表不存在: {cfg.target_table_id}")
    return cfg.model_dump(exclude={"description", "placeholder"})


@router.post("", response_model=FieldResponse, status_code=status.HTTP_201_CREATED)
def create_field(
    workspace_id: int,
    table_id: int,
    payload: FieldCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataField:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    dt = _get_table_or_404(table_id, workspace_id, db)

    # 校验 field_type 是否存在
    ft = default_registry.get(payload.field_type)
    if ft is None:
        raise HTTPException(status_code=400, detail=f"未知字段类型: {payload.field_type}")

    # 校验同表名字唯一
    existing = db.query(DataField).filter(DataField.table_id == table_id, DataField.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="字段名已存在")

    config = payload.config
    if payload.field_type == "link":
        config = _validate_link_config(payload.config, db)

    df = DataField(
        table_id=table_id,
        name=payload.name,
        field_type=payload.field_type,
        config=config,
        required=payload.required,
        is_unique=payload.is_unique,
        default_value=payload.default_value,
        order=payload.order,
    )
    df.ensure_db_name()
    db.add(df)
    db.commit()
    db.refresh(df)

    # 物理加列
    try:
        add_column(db.get_bind(), dt, df)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"物理加列失败: {exc}") from exc

    return df


@router.get("", response_model=list[FieldResponse])
def list_fields(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_trashed: bool = False,
) -> list[DataField]:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    _get_table_or_404(table_id, workspace_id, db)
    query = db.query(DataField).filter(DataField.table_id == table_id)
    if not include_trashed:
        query = query.filter(DataField.trashed == False)  # noqa: E712
    return query.order_by(DataField.order, DataField.id).all()


@router.patch("/{field_id}", response_model=FieldResponse)
def update_field(  # noqa: PLR0913, PLR0917
    workspace_id: int,
    table_id: int,
    field_id: int,
    payload: FieldUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataField:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    _ = _get_table_or_404(table_id, workspace_id, db)
    df = db.query(DataField).filter(DataField.id == field_id, DataField.table_id == table_id).first()
    if df is None:
        raise HTTPException(status_code=404, detail="字段不存在")
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(df, key, value)
    db.commit()
    db.refresh(df)
    return df


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_field(
    workspace_id: int,
    table_id: int,
    field_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    dt = _get_table_or_404(table_id, workspace_id, db)
    df = db.query(DataField).filter(DataField.id == field_id, DataField.table_id == table_id).first()
    if df is None:
        raise HTTPException(status_code=404, detail="字段不存在")

    # 软删除 metadata
    df.trashed = True
    db.commit()

    # 物理删列（失败则回滚 metadata）
    try:
        drop_column(db.get_bind(), dt, df)
    except Exception as exc:
        df.trashed = False
        db.commit()
        raise HTTPException(status_code=500, detail=f"物理删列失败: {exc}") from exc
