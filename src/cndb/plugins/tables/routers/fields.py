"""字段管理路由."""

from __future__ import annotations

import contextlib
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.field_types import FieldTypeConfig, LinkFieldConfig, default_registry, normalize_field_type
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.schemas import (
    FieldCreate,
    FieldDetectOptionsRequest,
    FieldDetectOptionsResponse,
    FieldImportRequest,
    FieldImportResponse,
    FieldResponse,
    FieldUpdate,
)
from cndb.plugins.tables.services.core.access import TableAction, check_action, get_table_or_404
from cndb.plugins.tables.services.core.ddl import (
    _column_needs_rebuild,
    add_column,
    add_unique_constraint,
    column_exists,
    create_link_table,
    drop_column,
    drop_link_table,
    drop_unique_constraint,
    find_duplicate_values,
    find_null_rows,
    rebuild_column,
    table_has_rows,
)
from cndb.plugins.tables.services.core.links import (
    find_duplicate_link_values,
    find_null_link_rows,
    is_link_field,
)
from cndb.plugins.tables.services.fields.field_ops import (
    clone_fields_between_tables,
    detect_options_from_field_data,
    import_fields_as_lookup,
    rename_trashed_field_aside,
    resolve_source_fields,
    sync_link_reference_fields,
    sync_select_data_on_options_change,
)
from cndb.plugins.workspaces.models import Workspace

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/fields", tags=["fields"])


def _validate_link_business_key(cfg: LinkFieldConfig, target: DataTable) -> None:
    """校验 link 字段配置的业务键（显示字段 / 匹配字段）合法.

    业务键必须是目标表中未回收、且有物理列的字段：显示字段为空值回退启发式、
    匹配字段为导入解析依据，配置失效都会让读取/导入语义静默退化，因此在保存期拒绝。
    """
    for label, key_id in (("显示字段", cfg.display_field_id), ("匹配字段", cfg.match_field_id)):
        if key_id is None:
            continue
        key_field = next((f for f in target.active_fields() if f.id == key_id), None)
        if key_field is None:
            raise HTTPException(status_code=400, detail=f"link 字段配置的{label}不属于目标表: {key_id}")
        ft = default_registry.get(key_field.field_type)
        if ft is None or not ft.has_physical_column:
            raise HTTPException(
                status_code=400, detail=f"link 字段配置的{label}「{key_field.name}」无物理列，不能作为业务键"
            )

    # 引用字段：额外投影的目标表字段，必须属于目标表且有物理列（lookup 只能读物理列值）
    seen_ref: set[int] = set()
    for ref_id in cfg.reference_fields:
        if ref_id in seen_ref:
            raise HTTPException(status_code=400, detail=f"link 字段配置的引用字段重复: {ref_id}")
        seen_ref.add(ref_id)
        ref_field = next((f for f in target.active_fields() if f.id == ref_id), None)
        if ref_field is None:
            raise HTTPException(status_code=400, detail=f"link 字段配置的引用字段不属于目标表: {ref_id}")
        ft = default_registry.get(ref_field.field_type)
        if ft is None or not ft.has_physical_column:
            raise HTTPException(
                status_code=400, detail=f"link 字段配置的引用字段「{ref_field.name}」无物理列，不能作为引用字段"
            )


def _validate_field_config(field_type: str, payload_config: dict[str, Any], db: Session) -> dict[str, Any]:
    """用字段类型对应的 config_schema 校验并归一化 config.

    link 字段额外校验 target_table_id 存在性；lookup 字段从源字段派生
    ``source_field_type``（引用字段跟随源字段类型的缓存）。未知/缺失
    config_schema 的类型走直通。
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
        if not isinstance(cfg, LinkFieldConfig):
            raise HTTPException(status_code=400, detail="link 字段 config 缺少 target_table_id")
        target = db.get(DataTable, cfg.target_table_id)
        if target is None or target.trashed:
            raise HTTPException(status_code=400, detail=f"关联目标表不存在: {cfg.target_table_id}")
        _validate_link_business_key(cfg, target)

    # lookup 字段：从源字段派生并缓存 source_field_type，保证引用字段跟随源字段类型。
    # 源字段不存在时留空（读取侧既有容错回退 None），不额外拒绝历史/跨库配置。
    if field_type == "lookup":
        source_field_id = (payload_config or {}).get("source_field_id")
        source = db.get(DataField, source_field_id) if isinstance(source_field_id, int) else None
        if source is not None:
            cfg.source_field_type = source.field_type  # type: ignore[attr-defined]

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
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)

    # 校验 field_type 是否存在
    ft = default_registry.get(payload.field_type)
    if ft is None:
        raise HTTPException(status_code=400, detail=f"未知字段类型: {payload.field_type}")

    # 校验同表名字唯一（软删除字段不占名字，见下方让位兜底）
    existing = (
        db.query(DataField)
        .filter(
            DataField.table_id == table_id,
            DataField.name == payload.name,
            DataField.trashed == False,  # noqa: E712
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="字段名已存在")

    # 存量兜底：历史软删除字段仍占用同名唯一约束时改名让位，释放名字供复用
    # （改名与新增字段同事务提交，物理 DDL 失败时不会留下已让位却无新字段的状态）
    trashed_dups = (
        db.query(DataField)
        .filter(
            DataField.table_id == table_id,
            DataField.name == payload.name,
            DataField.trashed == True,  # noqa: E712
        )
        .all()
    )

    # 用字段类型专属 schema 校验并归一化 config
    config = _validate_field_config(payload.field_type, payload.config or {}, db)

    engine = db.get_bind()

    # 物理 NOT NULL 列要求 ADD COLUMN 自带非 NULL 默认值（SQLite / PostgreSQL 一致）；
    # 新字段无法为存量行提供真实值，用占位默认值会污染必填语义，故直接拒绝并给出可操作路径。
    if payload.required and ft.has_physical_column and table_has_rows(engine, dt.db_table_name):
        raise HTTPException(
            status_code=400,
            detail=f"表「{dt.name}」已有数据，无法直接新增必填字段；请先新增可空字段并补齐数据，再设为必填",
        )

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

    # ── 物理 DDL 先行：失败时物理表保持原状，不产生「有 metadata、无物理列」的孤儿字段 ──
    db.rollback()  # 结束前面的只读事务，避免与物理 DDL 事务交织
    try:
        add_column(engine, dt, df)
        # is_unique：创建后同步加物理唯一索引
        if df.is_unique:
            add_unique_constraint(engine, dt, df)
    except Exception as exc:
        # 逆向清理本次请求已建成的物理对象（唯一索引需先删，否则 SQLite 不允许删被索引列）
        with contextlib.suppress(Exception):
            if df.is_unique:
                drop_unique_constraint(engine, dt, df)
        with contextlib.suppress(Exception):
            drop_column(engine, dt, df)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"物理加列失败: {exc}") from exc

    # ── 物理变更全部成功后再提交 metadata（与字段克隆同一事务策略） ──
    db.add(df)
    try:
        for dup in trashed_dups:
            dup.name = rename_trashed_field_aside(db, dup)
        db.commit()
    except Exception as exc:
        # metadata 落库失败（如让位名冲突）同样需要撤销刚建成的物理对象，否则反向留下孤儿列
        db.rollback()
        with contextlib.suppress(Exception):
            if df.is_unique:
                drop_unique_constraint(engine, dt, df)
        with contextlib.suppress(Exception):
            drop_column(engine, dt, df)
        raise HTTPException(status_code=500, detail=f"字段创建失败: {exc}") from exc
    db.refresh(df)

    # link 字段的引用字段在关联配置内管理：按 config.reference_fields 同步其名下 lookup
    if is_link_field(df):
        target = db.get(DataTable, (df.config or {}).get("target_table_id"))
        if target is not None:
            sync_link_reference_fields(db, df, target)

    return df


@router.get("", response_model=list[FieldResponse])
def list_fields(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_trashed: bool = False,
) -> list[DataField]:
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
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
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)
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
    needs_select_data_sync = False
    if needs_config_validation:
        effective_field_type = update_data.get("field_type", old_field_type)
        raw_config = update_data.get("config", df.config or {})
        update_data["config"] = _validate_field_config(effective_field_type, raw_config, db)
        # select/multiselect 选项变更 → 需同步存量数据（改名改写/删除清空）；
        # 纯新增/重排/配色 diff 为空，同步函数内部直接短路
        needs_select_data_sync = old_field_type in ("select", "multiselect") and effective_field_type in (
            "select",
            "multiselect",
        )

    # ── 保存前数据预检：已有数据违反必填/唯一时拒绝保存（metadata 尚未变更） ──
    engine = db.get_bind()
    effective_required = update_data.get("required", old_required)
    effective_is_unique = update_data.get("is_unique", old_is_unique)

    # lookup 字段值由关联源实时解析决定，行级约束无法在物理层强制，明确拒绝而非静默放行
    if df.field_type == "lookup" and (
        (effective_required and not old_required) or (effective_is_unique and not old_is_unique)
    ):
        raise HTTPException(status_code=400, detail=f"引用字段「{df.name}」的值由关联解析决定，不支持设置必填/唯一约束")

    # link → 物理列且必填：等价于「为非空表新增 NOT NULL 列」，物理层无法为存量行补值，
    # 直接给出可操作路径而不是让 DDL 抛 OperationalError 后靠回退收拾残局。
    new_ft = default_registry.get(update_data.get("field_type", old_field_type))
    if (
        is_link_field(old_field)
        and new_ft is not None
        and new_ft.has_physical_column
        and effective_required
        and table_has_rows(engine, dt.db_table_name)
    ):
        raise HTTPException(
            status_code=400,
            detail=f"字段「{df.name}」从关联改为必填物理列失败：表「{dt.name}」已有数据，无法为存量行补充取值；"
            "请先改为可空字段，补齐数据后再启用必填",
        )

    if effective_required and not old_required:
        if is_link_field(df):
            null_ids = find_null_link_rows(engine, dt, df)
        else:
            null_ids = find_null_rows(engine, dt, df)
        if null_ids:
            shown = "、".join(f"行 {i}" for i in null_ids)
            suffix = "（仅展示前 20 行）" if len(null_ids) >= 20 else ""
            raise HTTPException(
                status_code=400, detail=f"字段「{df.name}」设为必填失败，以下行该字段为空：{shown}{suffix}"
            )

    if effective_is_unique and not old_is_unique:
        if is_link_field(df):
            dups = find_duplicate_link_values(engine, df)
        else:
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

    # ── 选项变更 → 存量数据同步：与 config 保存同一事务，原子生效 ──
    # old_field.config 是变更前的 config 快照（setattr 后 df.config 已是新 dict）
    if needs_select_data_sync:
        try:
            sync_select_data_on_options_change(db, dt, df, old_field.config)
        except HTTPException:
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"选项变更同步存量数据失败: {exc}") from exc

    db.commit()
    db.refresh(df)

    # ── 物理变更检测与执行 ──

    old_is_link = is_link_field(old_field)
    new_is_link = is_link_field(df)

    # 1. field_type / required 变更 → 列重建
    if _column_needs_rebuild(old_field, df):
        try:
            rebuild_column(engine, dt, old_field, df)
        except Exception as exc:
            _revert_metadata()
            raise HTTPException(status_code=500, detail=f"物理列重建失败: {exc}") from exc

    # 1b. 物理列 ↔ link 互转：无物理列重建路径，需显式切换物理结构 ——
    #     改为 link 时创建关联表再删旧物理列；改回物理列时补物理列再删关联表。
    #     先建后删保证失败时原结构（数据/关联）仍在：metadata 回退后不会出现
    #     「metadata 说关联/物理列存在，但物理对象已丢」的半成品状态。
    elif old_is_link != new_is_link:
        try:
            if new_is_link:
                create_link_table(engine, df)
                drop_column(engine, dt, old_field)
            else:
                add_column(engine, dt, df)
                drop_link_table(engine, old_field)
        except Exception as exc:
            _revert_metadata()
            raise HTTPException(status_code=500, detail=f"字段类型切换物理结构变更失败: {exc}") from exc

    # 源字段类型变更 → 同步引用它的 lookup 字段（跨表）：类型跟随源字段；
    # 新类型无物理列（link/lookup）时才标记 broken，读取回退 None
    if old_field_type != df.field_type:
        from cndb.plugins.tables.services.core.lookups import sync_dependent_lookups_on_source_type_change

        sync_dependent_lookups_on_source_type_change(db, df)

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

    # 3. link 字段：按 config.reference_fields 同步名下 lookup 引用字段（增/删/排序）。
    #    仅当本次请求显式提供了 reference_fields 时才视为权威配置，避免仅改名字/业务键的
    #    编辑误删已有关联引入产生的 lookup 字段。
    incoming_refs = isinstance(payload.config, dict) and "reference_fields" in payload.config
    if is_link_field(df) and incoming_refs:
        target = db.get(DataTable, (df.config or {}).get("target_table_id"))
        if target is not None:
            sync_link_reference_fields(db, df, target)

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
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)  # 校验表存在

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


@router.post("/{field_id}/detect-options", response_model=FieldDetectOptionsResponse)
def detect_field_options(
    workspace_id: int,
    table_id: int,
    field_id: int,
    payload: FieldDetectOptionsRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FieldDetectOptionsResponse:
    """扫描字段物理列存量数据，识别可作为单选/多选选项的唯一值（只读，不持久化）.

    用于编辑字段把类型改为 select/multiselect 时：物理列存的仍是旧类型数据，
    按请求的 target_type 识别（multiselect 按用户指定 delimiter 拆分，默认逗号），
    结果由前端填入选项编辑器、用户确认后随 config 一并保存。
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)
    df = db.query(DataField).filter(DataField.id == field_id, DataField.table_id == table_id).first()
    if df is None:
        raise HTTPException(status_code=404, detail="字段不存在")

    target_type = normalize_field_type(payload.target_type)
    try:
        options = detect_options_from_field_data(db, dt, df, target_type=target_type, delimiter=payload.delimiter)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FieldDetectOptionsResponse(options=options)


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_field(
    workspace_id: int,
    table_id: int,
    field_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)
    df = db.query(DataField).filter(DataField.id == field_id, DataField.table_id == table_id).first()
    if df is None:
        raise HTTPException(status_code=404, detail="字段不存在")

    # 软删除 metadata + 改名让位：释放 uniq_table_field_name 约束位，
    # 同名字段可立即重建（回收站字段不可恢复，改名不影响任何功能）
    df.trashed = True
    original_name = df.name
    df.name = rename_trashed_field_aside(db, df)
    db.commit()

    # 物理删列（失败则回滚 metadata，含让位名）
    engine = db.get_bind()
    ft = default_registry.get(df.field_type)
    needs_physical_drop = ft is not None and ft.has_physical_column
    try:
        # 历史 DDL 失败残留的字段可能本就没有物理列：按已删除处理，保证可以清理
        if not needs_physical_drop or column_exists(engine, dt.db_table_name, df.db_column_name):
            drop_column(engine, dt, df)
    except Exception as exc:
        df.trashed = False
        df.name = original_name
        db.commit()
        raise HTTPException(status_code=500, detail=f"物理删列失败: {exc}") from exc

    # 引用该字段的 lookup 字段标记失效（物理删列成功后再标记，
    # 避免删列失败、字段回滚后遗留错误的失效状态）
    from cndb.plugins.tables.services.core.lookups import mark_dependent_lookups_broken

    mark_dependent_lookups_broken(db, df.id)


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

    dst = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)

    # 源表必须存在（允许跨工作区，但用户必须对源工作区有读权限）
    src = db.get(DataTable, payload.source_table_id)
    if src is None:
        raise HTTPException(status_code=400, detail=f"源表不存在: {payload.source_table_id}")
    if src.trashed:
        raise HTTPException(status_code=400, detail="源表已进回收站，不能引入字段")
    src_ws = db.get(Workspace, src.workspace_id)
    if not check_action(db, src, current_user, TableAction.READ):
        # 不泄露源表字段信息：detail 只到工作区级
        ws_name = src_ws.name if src_ws is not None else "未知"
        raise HTTPException(status_code=400, detail=f"没有源工作区「{ws_name}」的读取权限，无法引入其字段")

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
    from cndb.plugins.tables.services.importing.field_mapping import (
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

    # ── 预览模式：直接返回，不执行引入 ──
    if payload.preview_only:
        if payload.import_mode == "link":
            # link 模式：给出将创建的字段清单（自动 link 字段 + 每个可关联源字段一个 lookup 字段）
            existing_names = {f.name for f in dst.fields if not f.trashed}
            has_link = any(
                f.field_type == "link" and (f.config or {}).get("target_table_id") == src.id
                for f in dst.active_fields()
            )
            planned: list[dict[str, Any]] = []
            if not has_link:
                planned.append({"name": f"关联 {src.name}", "field_type": "link"})
            for sf in src_fields:
                if sf.field_type in ("link", "lookup"):
                    continue
                if sf.name in existing_names:
                    continue
                planned.append({"name": sf.name, "field_type": "lookup"})
            gap_analysis = dict(gap_analysis) if gap_analysis else {}
            gap_analysis["planned_fields"] = planned
        return FieldImportResponse(
            created=[],
            skipped=[],
            total_source_count=len(src_fields),
            gap_analysis=gap_analysis,
            suggestions=suggestions,
        )

    # ── 执行引入：link=字段关联模式；copy（默认）=字段定义复制模式 ──
    engine = db.get_bind()
    if payload.import_mode == "link":
        try:
            created, skipped = import_fields_as_lookup(engine, db, src, dst, src_fields)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"字段关联引入失败: {exc}") from exc
    else:
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
