"""字段管理路由."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.ddl import (
    _column_needs_rebuild,
    add_column,
    add_unique_constraint,
    drop_column,
    drop_unique_constraint,
    rebuild_column,
)
from cndb.plugins.tables.field_types import FieldTypeConfig, LinkFieldConfig, default_registry, normalize_field_type
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.routers.tables import _check_table_permission, _get_table_or_404
from cndb.plugins.tables.schemas import FieldCreate, FieldResponse, FieldUpdate
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/fields", tags=["fields"])


def _validate_field_config(field_type: str, payload_config: dict[str, Any], db: Session) -> dict[str, Any]:
    """用字段类型对应的 config_schema 校验并归一化 config.

    link 字段额外校验 target_table_id 存在性。未知/缺失 config_schema 的类型走直通。
    """
    ft = default_registry.get(field_type)
    if ft is None:
        raise HTTPException(status_code=400, detail=f"未知字段类型: {field_type}")

    # 用 pydantic 校验
    schema_cls: type[FieldTypeConfig] = ft.config_schema
    try:
        cfg = schema_cls.model_validate(payload_config or {})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{field_type} 字段 config 校验失败: {exc}") from exc

    # link 字段额外校验 target_table_id
    if field_type == "link":
        assert isinstance(cfg, LinkFieldConfig)
        target = db.get(DataTable, cfg.target_table_id)
        if target is None or target.trashed:
            raise HTTPException(status_code=400, detail=f"关联目标表不存在: {cfg.target_table_id}")

    # 归一化输出（去掉基类 FieldTypeConfig 的通用字段）
    exclude = set()
    base_fields = {"description", "placeholder"}
    exclude.update(base_fields - set(schema_cls.model_fields.keys()))  # 去掉 schema 里没有的
    return cfg.model_dump(exclude_unset=False)


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

    # 用字段类型专属 schema 校验并归一化 config
    config = _validate_field_config(payload.field_type, payload.config or {}, db)

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
        # is_unique：创建后同步加物理唯一索引
        if df.is_unique:
            add_unique_constraint(db.get_bind(), dt, df)
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
def update_field(
    workspace_id: int,
    table_id: int,
    field_id: int,
    payload: FieldUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataField:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    dt = _get_table_or_404(table_id, workspace_id, db)
    df = db.query(DataField).filter(DataField.id == field_id, DataField.table_id == table_id).first()
    if df is None:
        raise HTTPException(status_code=404, detail="字段不存在")

    # 归一化传入的 field_type（兼容历史别名）
    update_data = payload.model_dump(exclude_unset=True)
    if "field_type" in update_data and update_data["field_type"] is not None:
        update_data["field_type"] = normalize_field_type(update_data["field_type"])

    # 备份旧状态（用于后续物理变更检测）
    old_field_type = df.field_type
    old_required = df.required
    old_is_unique = df.is_unique
    old_db_column_name = df.db_column_name
    old_field = DataField(
        id=df.id,
        table_id=df.table_id,
        name=df.name,
        field_type=old_field_type,
        db_column_name=old_db_column_name,
        config=df.config,
        required=old_required,
        is_unique=old_is_unique,
        default_value=df.default_value,
        order=df.order,
    )

    for key, value in update_data.items():
        setattr(df, key, value)

    db.commit()
    db.refresh(df)

    # ── 物理变更检测与执行 ──
    engine = db.get_bind()

    # 1. field_type / required 变更 → 列重建
    if _column_needs_rebuild(old_field, df):
        try:
            rebuild_column(engine, dt, old_field, df)
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"物理列重建失败: {exc}") from exc

    # 2. is_unique 切换
    if old_is_unique != df.is_unique:
        try:
            if df.is_unique:
                add_unique_constraint(engine, dt, df)
            else:
                drop_unique_constraint(engine, dt, df)
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"唯一约束变更失败: {exc}") from exc

    return df


@router.post("/reorder", response_model=list[FieldResponse])
def reorder_fields(
    workspace_id: int,
    table_id: int,
    field_ids: Annotated[list[int], Body(embed=True)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DataField]:
    """批量调整字段顺序（按传入顺序赋值 order 字段）."""
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    _get_table_or_404(table_id, workspace_id, db)  # 校验表存在

    fields = (
        db.query(DataField)
        .filter(
            DataField.table_id == table_id,
            DataField.id.in_(field_ids),
        )
        .all()
    )

    field_map = {f.id: f for f in fields}
    for idx, fid in enumerate(field_ids):
        if fid in field_map:
            field_map[fid].order = idx

    db.commit()
    return db.query(DataField).filter(DataField.table_id == table_id).order_by(DataField.order, DataField.id).all()


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
