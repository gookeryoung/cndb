"""视图管理路由."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataView, ViewVisibility, scope_key_for
from cndb.plugins.tables.schemas import ViewCreate, ViewResponse, ViewUpdate, ViewVisibilityUpdate
from cndb.plugins.tables.services.core.access import TableAction, check_action, get_table_or_404
from cndb.plugins.tables.services.core.view_access import (
    ViewAction,
    assert_can_change_visibility,
    get_view_or_404,
    require_can_publish_to_table,
    resolve_view_action,
    view_visibility_filter,
)

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/views", tags=["views"])


def _validate_view_fields(vc: ViewCreate, table_id: int, db: Session) -> tuple[bool, str | None]:
    """校验视图配置里引用的所有 field_name 是否在目标表存在."""
    valid_fields = {f.name for f in db.query(DataField).filter(DataField.table_id == table_id).all()}
    for f in vc.filters or []:
        if f.get("field_name") not in valid_fields:
            return False, f"filter field_name='{f.get('field_name')}' 不存在"
    for s in vc.sortings or []:
        if s.get("field_name") not in valid_fields:
            return False, f"sorting field_name='{s.get('field_name')}' 不存在"
    vo = vc.view_options or {}
    for opt_key in (
        "group_field",
        "start_field",
        "title_field",
        # Gantt 甘特图（v1 未校验，此次补齐）
        "start_date_field",
        "end_date_field",
        "actual_end_field",
        "progress_field",
        "assignee_field",
        # WBS 工作分解结构
        "parent_field",
        "status_field",
        # Matrix 矩阵视图（纵横轴字段）
        "row_field",
        "column_field",
        # Chart 图表视图（维度/度量/散点双轴字段；group_field 已在上方）
        "dimension_field",
        "measure_field",
        "x_field",
        "y_field",
    ):
        opt_val = vo.get(opt_key)
        if opt_val and opt_val not in valid_fields:
            return False, f"view_options.{opt_key}='{opt_val}' 不存在"
    # chart 多图形态：charts[] 逐条目校验字段引用（detail 定位到 charts[i].<key>）
    charts = vo.get("charts")
    if isinstance(charts, list):
        for i, entry in enumerate(charts):
            if not isinstance(entry, dict):
                return False, f"view_options.charts[{i}] 不是对象"
            for opt_key in ("dimension_field", "measure_field", "x_field", "y_field", "group_field"):
                opt_val = entry.get(opt_key)
                if opt_val and opt_val not in valid_fields:
                    return False, f"view_options.charts[{i}].{opt_key}='{opt_val}' 不存在"
    return True, None


def _scoped_name_conflict(db: Session, table_id: int, scope_key: int, name: str) -> bool:
    """同名视图是否已存在于**同一命名空间**（ADR 0003 缺陷 #7 的修复点）."""
    return (
        db.query(DataView)
        .filter(DataView.table_id == table_id, DataView.scope_key == scope_key, DataView.name == name)
        .first()
        is not None
    )


def _create_view_obj(
    db: Session,
    table_id: int,
    payload: ViewCreate,
    owner_id: int,
) -> DataView:
    """创建单个 DataView 对象（不含 commit）.

    ``owner_id`` 恒为创建者（I4：授权不转移归属）；可见性由 ``payload.visibility``
    决定（新建默认 ``private``），命名空间由 :func:`scope_key_for` 推导。
    档位合法性（``table`` 档需表 ``EDIT_VIEWS``、``is_default`` 仅限 ``table`` 档）
    由调用方在创建前校验。
    """
    if payload.is_default:
        db.query(DataView).filter(DataView.table_id == table_id).update({"is_default": False})
    # 未显式指定顺序时追加到末尾（现有最大 order + 1），避免新视图排在最前
    if payload.order is None:
        max_order = db.query(func.max(DataView.order)).filter(DataView.table_id == table_id).scalar()
        order = (max_order or 0) + 1
    else:
        order = payload.order
    return DataView(
        table_id=table_id,
        owner_id=owner_id,
        name=payload.name,
        view_type=payload.view_type,
        filter_type=payload.filter_type,
        filters=payload.filters,
        sortings=payload.sortings,
        field_options=payload.field_options,
        field_order=payload.field_order,
        view_options=payload.view_options,
        is_default=payload.is_default,
        order=order,
        visibility=payload.visibility,
        scope_key=scope_key_for(payload.visibility, owner_id),
    )


@router.post("", response_model=ViewResponse, status_code=status.HTTP_201_CREATED)
def create_view(
    workspace_id: int,
    table_id: int,
    payload: ViewCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataView:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    # 定档校验：table 档（表内所有人可见）需表 EDIT_VIEWS（D4）；
    # shared/private 档只需本人是创建者（由 VIEW_MANAGE 语义保证，创建时天然满足）
    visibility = payload.visibility
    require_can_publish_to_table(db, dt, current_user, visibility)
    # is_default 是**表级**标记（会清掉同表其它默认视图）：只有 table 档视图才代表
    # "全表成员的落地页"，private/shared 视图持有它会抢占他人视角（ADR 0003 §2）
    if payload.is_default and visibility != ViewVisibility.TABLE:
        raise HTTPException(status_code=400, detail="仅表内可见视图可设为默认视图")

    # 同表视图名唯一 —— 按命名空间判定（私有视图只在本人空间内唯一，修缺陷 #7）
    scope_key = scope_key_for(visibility, current_user.id)
    if _scoped_name_conflict(db, table_id, scope_key, payload.name):
        raise HTTPException(status_code=400, detail="视图名已存在")

    ok, err = _validate_view_fields(payload, table_id, db)
    if not ok:
        raise HTTPException(status_code=400, detail=f"视图字段校验失败: {err}")

    dv = _create_view_obj(db, table_id, payload, owner_id=current_user.id)
    db.add(dv)
    db.commit()
    db.refresh(dv)
    return dv


@router.post("/import", response_model=list[ViewResponse])
def import_views(
    workspace_id: int,
    table_id: int,
    payload: list[ViewCreate],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DataView]:
    """批量导入视图配置（上传 JSON 数组）.

    同名视图自动跳过，字段引用不存在时跳过并返回 warnings.
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    # 已占用的命名空间键（scope_key, name）—— 私有视图只与本人空间的同名冲突（缺陷 #7）
    existing_keys = {
        (int(r[0]), str(r[1]))
        for r in db.query(DataView.scope_key, DataView.name).filter(DataView.table_id == table_id).all()
    }
    created: list[DataView] = []
    skipped: list[str] = []

    # 导入者无 EDIT_VIEWS → 只能落 private 档（与 create_view 的 D4 门槛一致）
    can_edit_views = check_action(db, dt, current_user, TableAction.EDIT_VIEWS)

    for vc in payload:
        visibility = vc.visibility
        if visibility == ViewVisibility.TABLE and not can_edit_views:
            visibility = ViewVisibility.PRIVATE
        # is_default 是表级标记，仅 table 档视图可持有（个人视图会抢占全表落地页）
        is_default = vc.is_default and visibility == ViewVisibility.TABLE
        if visibility != vc.visibility or is_default != vc.is_default:
            vc = vc.model_copy(update={"visibility": visibility, "is_default": is_default})
        scope_key = scope_key_for(visibility, current_user.id)
        if (scope_key, vc.name) in existing_keys:
            skipped.append(f"已存在: {vc.name}")
            continue
        ok, err = _validate_view_fields(vc, table_id, db)
        if not ok:
            skipped.append(f"跳过 {vc.name}: {err}")
            continue
        dv = _create_view_obj(db, table_id, vc, owner_id=current_user.id)
        db.add(dv)
        created.append(dv)
        existing_keys.add((scope_key, vc.name))

    db.commit()
    for dv in created:
        db.refresh(dv)
    if skipped:
        import json as _json

        print(
            f"[视图导入] table_id={table_id}: {len(created)} 成功, {len(skipped)} 跳过: {_json.dumps(skipped, ensure_ascii=False)}"
        )
    return created


@router.get("", response_model=list[ViewResponse])
def list_views(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DataView]:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 可见性统一由 view_access 判定：table 档全表可见 + shared 档名单内 + private 档仅本人
    return (
        db.query(DataView)
        .filter(DataView.table_id == table_id, view_visibility_filter(db, dt, current_user))
        .order_by(DataView.order, DataView.id)
        .all()
    )


@router.get("/export", response_model=list[ViewCreate])
def export_views(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    ids: Annotated[list[int] | None, Query()] = None,
) -> list[dict[str, object]]:
    """导出视图配置（返回 ViewCreate 兼容的 JSON 数组，不含 id / 时间戳等内部元数据）.

    - 不传 ids → 导出该表全部视图
    - 传 ids → 仅导出指定视图（不存在的 id 自动跳过）
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    q = db.query(DataView).filter(
        DataView.table_id == table_id,
        # 可见性：与 list_views 一致 —— table 档 + shared 名单内 + 本人 private
        view_visibility_filter(db, dt, current_user),
    )
    if ids:
        q = q.filter(DataView.id.in_(ids))
    views = q.order_by(DataView.order, DataView.id).all()

    stripped: list[dict[str, object]] = []
    keep_fields = {
        "name",
        "view_type",
        "filter_type",
        "filters",
        "sortings",
        "field_options",
        "field_order",
        "view_options",
        "is_default",
        "visibility",
        "order",
    }
    for v in views:
        raw = DataView.__table__.columns.keys()
        obj = {k: getattr(v, k) for k in raw if k in keep_fields}
        stripped.append(obj)
    return stripped


@router.get("/{view_id}", response_model=ViewResponse)
def get_view(
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataView:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 公共视图仅需表 READ 即可查看（此前误要求 EDIT_VIEWS，导致"列表可见但点开 403"）
    return get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_READ)


@router.patch("/{view_id}", response_model=ViewResponse)
def update_view(
    workspace_id: int,
    table_id: int,
    view_id: int,
    payload: ViewUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataView:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 改配置需 VIEW_EDIT：本人个人视图放行；公共视图需表 EDIT_VIEWS（I7）
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_EDIT)

    # is_default 是**表级**标记（会清掉同表其它默认视图）：只有 table 档视图代表
    # "全表成员的落地页"，private/shared 档持有它会让其他成员进表看到空白（ADR 0003 §2）
    if payload.is_default and dv.visibility != ViewVisibility.TABLE:
        raise HTTPException(status_code=400, detail="仅表内可见视图可设为默认视图")

    # 如果标记为 default，先把同表其他视图的 default 清掉
    if payload.is_default:
        db.query(DataView).filter(DataView.table_id == table_id).update({"is_default": False})

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(dv, key, value)
    db.commit()
    db.refresh(dv)
    return dv


@router.post("/{view_id}/visibility", response_model=ViewResponse)
def set_view_visibility(
    workspace_id: int,
    table_id: int,
    view_id: int,
    payload: ViewVisibilityUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataView:
    """切换视图可见性档位（ADR 0003 §6，P2 承载档位切换；名单读写属 P3）.

    - 需 ``VIEW_MANAGE``：创建者本人，或非私有档下的表内管理视角
    - 开放为 ``table`` 档（表内所有人可见）额外需表 ``EDIT_VIEWS``（决策 D4）
    - **每张表至少保留一个 ``table`` 档视图**：把最后一个转出 → 400（决策 D1）
    - 同名冲突按**目标档位**的命名空间判定（private 与共享空间互不干扰）
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_MANAGE)

    new_visibility = payload.visibility
    require_can_publish_to_table(db, dt, current_user, new_visibility)
    assert_can_change_visibility(db, dt, dv, new_visibility)

    new_scope = scope_key_for(new_visibility, dv.owner_id)
    if new_scope != dv.scope_key and _scoped_name_conflict(db, table_id, new_scope, dv.name):
        raise HTTPException(status_code=400, detail="目标可见范围内的同名视图已存在")

    if new_visibility != ViewVisibility.TABLE and dv.is_default:
        # 表级默认位只属于 table 档视图：转出时先摘掉，避免"默认视图他人看不见"
        dv.is_default = False
    dv.visibility = new_visibility
    dv.scope_key = new_scope
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
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 删除需 VIEW_MANAGE：本人个人视图放行；公共视图需表 EDIT_VIEWS（I7）
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_MANAGE)

    was_default = dv.is_default
    db.delete(dv)
    db.flush()
    if was_default:
        # 删除的是默认视图 → 把默认标记转移给同表剩余视图（按 order/id 取第一个），避免出现"无默认视图".
        # 候选必须是 table 档视图：private/shared 档对全表不可见，让它持有 is_default 会让其他成员进表看到空白（缺陷 ⑥）.
        next_default = (
            db.query(DataView)
            .filter(DataView.table_id == table_id, DataView.visibility == ViewVisibility.TABLE)
            .order_by(DataView.order, DataView.id)
            .first()
        )
        if next_default is not None:
            next_default.is_default = True
    db.commit()


@router.post("/reorder", response_model=list[ViewResponse])
def reorder_views(
    workspace_id: int,
    table_id: int,
    view_ids: list[int],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DataView]:
    """批量调整视图顺序（按传入顺序赋值 order 字段）.

    只重排**当前用户可改**的视图子集：他人的个人视图（本就不可见）与仅可读的公共视图
    一律跳过；响应也只返回当前用户**可见**的视图。修复：原实现返回该表**全部**视图，
    等于借重排接口枚举他人个人视图的完整配置（缺陷 ②）。
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_VIEWS)

    requested = (
        db.query(DataView)
        .filter(
            DataView.table_id == table_id,
            DataView.id.in_(view_ids),
        )
        .all()
    )
    view_map = {v.id: v for v in requested}

    idx = 0
    for vid in view_ids:
        view = view_map.get(vid)
        if view is None:
            continue  # 不存在的 id / 不属于本表 → 跳过（保持既有容错语义）
        if not resolve_view_action(db, dt, view, current_user, ViewAction.VIEW_EDIT):
            continue  # 他人个人视图 / 仅可读 → 不参与重排，也不出现在响应里
        view.order = idx
        idx += 1

    db.commit()
    return (
        db.query(DataView)
        .filter(DataView.table_id == table_id, view_visibility_filter(db, dt, current_user))
        .order_by(DataView.order, DataView.id)
        .all()
    )


# ── 视图驱动的行查询 ──────────────────────────────────


@router.get("/{view_id}/rows")
def get_view_rows(
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    """按视图的 filters + sortings 查询行."""
    from cndb.plugins.tables.services.core import records as rec

    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 补 VIEW_READ 校验：此前只校验表 READ，凭他人个人视图 id 即可按其筛选规则取数（缺陷 ①）
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_READ)

    rows, total = rec.list_rows(
        db.get_bind(),
        dt,
        filters=dv.filters or None,
        filter_logic=dv.filter_type,
        sorts=dv.sortings or None,
        limit=limit,
        offset=offset,
        db=db,
        user=current_user,
    )
    return {"rows": rows, "total": total, "view_id": view_id}


@router.get("/{view_id}/kanban")
def get_view_kanban(
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=500, ge=1, le=10000),
) -> dict[str, object]:
    """看板视图：按 view_options.group_field 分组返回行.

    view_options 支持：
    - group_field (str, 必填): 分组字段名（DataField.name）
    - group_order (list[str], 可选): 显式分组顺序，未在列表里的分组追加在末尾
    - ungrouped_label (str, 可选): 空值分组的显示名，默认 "未分组"
    """
    from collections import defaultdict

    from cndb.plugins.tables.services.core import records as rec

    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 补 VIEW_READ 校验（缺陷 ①）
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_READ)

    opts = dv.view_options or {}
    group_field = opts.get("group_field")
    if not group_field:
        raise HTTPException(status_code=400, detail="看板视图需配置 group_field")

    group_order: list[str] = opts.get("group_order") or []
    ungrouped_label: str = opts.get("ungrouped_label") or "未分组"

    rows, total = rec.list_rows(
        db.get_bind(),
        dt,
        filters=dv.filters or None,
        filter_logic=dv.filter_type,
        sorts=dv.sortings or None,
        limit=limit,
        db=db,
        user=current_user,
    )
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        raw_val = row.get(group_field)
        key = str(raw_val) if raw_val not in (None, "") else ungrouped_label
        grouped[key].append(row)

    # 按 group_order 排序分组，未列出的追加在末尾
    if group_order:
        ordered_keys = [k for k in group_order if k in grouped]
        extra_keys = [k for k in grouped if k not in group_order]
        # ungrouped_label 放最后（如果不在 group_order 里）
        if ungrouped_label in extra_keys:
            extra_keys.remove(ungrouped_label)
            extra_keys.append(ungrouped_label)
        ordered_keys.extend(extra_keys)
        grouped = {k: grouped[k] for k in ordered_keys}

    return {
        "columns": grouped,
        "total": total,
        "group_field": group_field,
        "group_order": list(grouped.keys()),
        "ungrouped_label": ungrouped_label,
    }


@router.get("/{view_id}/calendar")
def get_view_calendar(
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
    from cndb.plugins.tables.services.core import records as rec

    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 补 VIEW_READ 校验（缺陷 ①）
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_READ)

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
        db=db,
        user=current_user,
    )
    return {"rows": rows, "total": total, "start_field": start_field}
