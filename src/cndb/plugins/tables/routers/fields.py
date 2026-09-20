"""字段管理路由."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.access import TableAction
from cndb.plugins.tables.ddl import (
    _column_needs_rebuild,
    add_column,
    add_unique_constraint,
    drop_column,
    drop_unique_constraint,
    find_duplicate_values,
    find_null_rows,
    rebuild_column,
)
from cndb.plugins.tables.field_ops import clone_fields_between_tables, resolve_source_fields
from cndb.plugins.tables.field_types import FieldTypeConfig, LinkFieldConfig, default_registry, normalize_field_type
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.routers.tables import _get_table_or_404
from cndb.plugins.tables.schemas import FieldCreate, FieldImportRequest, FieldImportResponse, FieldResponse, FieldUpdate

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
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)

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
        hidden=payload.hidden,
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
    _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
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
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)
    df = db.query(DataField).filter(DataField.id == field_id, DataField.table_id == table_id).first()
    if df is None:
        raise HTTPException(status_code=404, detail="字段不存在")

    # 归一化传入的 field_type（兼容历史别名）
    update_data = payload.model_dump(exclude_unset=True)
    if "field_type" in update_data and update_data["field_type"] is not None:
        update_data["field_type"] = normalize_field_type(update_data["field_type"])

    # 备份旧状态（用于后续物理变更检测与失败回退）
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

    # ── config 校验：create_field 已覆盖，update_field 需补齐 ──
    # 当 config 或 field_type 发生变化时，用字段类型专属 schema 校验并归一化 config
    needs_config_validation = "config" in update_data or (
        "field_type" in update_data and update_data["field_type"] != old_field_type
    )
    if needs_config_validation:
        effective_field_type = update_data.get("field_type", old_field_type)
        raw_config = update_data.get("config", df.config or {})
        update_data["config"] = _validate_field_config(effective_field_type, raw_config, db)

    # ── 保存前数据预检：已有数据违反必填/唯一时拒绝保存（metadata 尚未变更） ──
    engine = db.get_bind()
    effective_required = update_data.get("required", old_required)
    effective_is_unique = update_data.get("is_unique", old_is_unique)

    if effective_required and not old_required:
        null_ids = find_null_rows(engine, dt, df)
        if null_ids:
            shown = "、".join(f"行 {i}" for i in null_ids)
            suffix = "（仅展示前 20 行）" if len(null_ids) >= 20 else ""
            raise HTTPException(
                status_code=400, detail=f"字段「{df.name}」设为必填失败，以下行该字段为空：{shown}{suffix}"
            )

    if effective_is_unique and not old_is_unique:
        dups = find_duplicate_values(engine, dt, df)
        if dups:
            shown = "、".join(f"'{value}'（行 {'、'.join(str(i) for i in ids)}）" for value, ids in dups)
            suffix = "（仅展示前 10 组）" if len(dups) >= 10 else ""
            raise HTTPException(status_code=400, detail=f"字段「{df.name}」启用唯一失败，存在重复值：{shown}{suffix}")

    # 记录变更前旧值（物理 DDL 失败时恢复 metadata，保证与物理状态一致）
    old_values = {key: getattr(df, key) for key in update_data}

    def _revert_metadata() -> None:
        """物理 DDL 失败兜底：把已提交的 metadata 恢复为旧值（rollback 撤销不了已 commit 的状态）."""
        db.rollback()
        for key, value in old_values.items():
            setattr(df, key, value)
        db.commit()

    for key, value in update_data.items():
        setattr(df, key, value)

    db.commit()
    db.refresh(df)

    # ── 物理变更检测与执行 ──

    # 1. field_type / required 变更 → 列重建
    if _column_needs_rebuild(old_field, df):
        try:
            rebuild_column(engine, dt, old_field, df)
        except Exception as exc:
            _revert_metadata()
            raise HTTPException(status_code=500, detail=f"物理列重建失败: {exc}") from exc

    # 2. is_unique 切换
    if old_is_unique != df.is_unique:
        try:
            if df.is_unique:
                add_unique_constraint(engine, dt, df)
            else:
                drop_unique_constraint(engine, dt, df)
        except Exception as exc:
            _revert_metadata()
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
    _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)  # 校验表存在

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
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)
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


@router.post("/import", response_model=FieldImportResponse, status_code=status.HTTP_201_CREATED)
def import_fields(
    workspace_id: int,
    table_id: int,
    payload: FieldImportRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FieldImportResponse:
    """从其他表引入字段 schema 到当前表（不复制数据，只复制字段定义）.

    - 新字段拥有独立的生命周期（修改/删除不影响源表）.
    - link 字段的 config.target_table_id 保留原值（天然支持跨工作区关联）.
    - 同名冲突时默认 400，skip_conflicts=True 时跳过冲突字段并返回说明.
    - field_mapping 支持源字段 → 目标字段重命名 / 跳过：
      payload.field_mapping={"源字段名": "目标字段名", "另一个": null}
    - preview_only=True 时只返回建议映射/缺口分析，不实际创建字段（供前端先展示参照对比面板）.
    """

    dst = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)

    # 源表必须存在（允许跨工作区，但用户必须在目标表工作区有 ADMIN 权限）
    src = db.get(DataTable, payload.source_table_id)
    if src is None:
        raise HTTPException(status_code=400, detail=f"源表不存在: {payload.source_table_id}")
    if src.trashed:
        raise HTTPException(status_code=400, detail="源表已进回收站，不能引入字段")

    # 解析源字段 —— 三种模式互斥
    if payload.import_all_fields:
        field_ids = None
        field_names = None
    elif payload.field_ids:
        field_ids = payload.field_ids
        field_names = None
    elif payload.field_names:
        field_ids = None
        field_names = payload.field_names
    else:
        raise HTTPException(status_code=400, detail="需指定 import_all_fields / field_ids / field_names 其中之一")

    try:
        src_fields = resolve_source_fields(
            src,
            field_ids=field_ids,
            field_names=field_names,
            exclude_trashed=payload.exclude_trashed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not src_fields:
        return FieldImportResponse(created=[], skipped=["源表没有可克隆的字段"], total_source_count=0)

    # 校验用户 field_mapping 里没有源表不存在的字段名
    if payload.field_mapping:
        src_names = {f.name for f in src_fields}
        unknown = set(payload.field_mapping.keys()) - src_names
        if unknown:
            raise HTTPException(status_code=400, detail=f"field_mapping 中存在源表没有的字段: {sorted(unknown)}")

    # ── 构造缺口分析 + 智能建议（无论 preview 与否都返回，供前端渲染） ──
    from cndb.plugins.tables.field_mapping import (
        analyze_field_gaps,
        apply_user_mapping,
        build_default_mapping,
        suggest_field_mapping,
    )

    dst_names = [f.name for f in dst.fields if not f.trashed]
    dst_fields_list = [f for f in dst.fields if not f.trashed]
    src_names_list = [f.name for f in src_fields]

    if payload.field_mapping is not None:
        # 用户显式传了 mapping → 用用户的
        base = build_default_mapping(src_names_list)
        merged = apply_user_mapping(base, payload.field_mapping, src_names_list)
        gap_analysis = analyze_field_gaps(merged, src_names_list, dst_names)
        suggestions: list[dict[str, Any]] | None = None
    else:
        # 未传 field_mapping → 用 suggest_field_mapping 自动推一个默认（供前端预览用）
        auto_mapping, suggestions = suggest_field_mapping(src_fields, dst_fields_list)
        base = build_default_mapping(src_names_list)
        merged = apply_user_mapping(base, auto_mapping, src_names_list)
        gap_analysis = analyze_field_gaps(merged, src_names_list, dst_names)

    # ── 预览模式：直接返回，不执行克隆 ──
    if payload.preview_only:
        return FieldImportResponse(
            created=[],
            skipped=[],
            total_source_count=len(src_fields),
            gap_analysis=gap_analysis,
            suggestions=suggestions,
        )

    # ── 执行克隆（field_mapping 仅在用户显式传入时才应用；否则沿用 legacy 同名默认） ──
    engine = db.get_bind()
    try:
        created, skipped = clone_fields_between_tables(
            engine,
            db,
            src,
            dst,
            field_ids=[f.id for f in src_fields],
            skip_conflicts=payload.skip_conflicts,
            field_mapping=payload.field_mapping,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"字段导入失败: {exc}") from exc

    return FieldImportResponse(
        created=[FieldResponse.model_validate(f, from_attributes=True) for f in created],
        skipped=skipped,
        total_source_count=len(src_fields),
        gap_analysis=gap_analysis,
        suggestions=suggestions,
    )
