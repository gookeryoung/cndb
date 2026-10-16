"""视图管理路由."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataView
from cndb.plugins.tables.schemas import ViewCreate, ViewResponse, ViewUpdate
from cndb.plugins.tables.services.core.access import TableAction, check_action, get_table_or_404
from cndb.plugins.tables.services.core.view_access import (
    ViewAction,
    get_view_or_404,
    resolve_view_action,
    visible_view_filter,
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


def _create_view_obj(
    db: Session,
    table_id: int,
    payload: ViewCreate,
    owner_id: int | None,
) -> DataView:
    """创建单个 DataView 对象（不含 commit）.

    owner_id=None 表示公共视图（有 EDIT_VIEWS 权限者创建）；
    owner_id=创建者 id 表示个人视图（仅创建者可见可改）.
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

    # 同表视图名唯一
    existing = db.query(DataView).filter(DataView.table_id == table_id, DataView.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="视图名已存在")

    ok, err = _validate_view_fields(payload, table_id, db)
    if not ok:
        raise HTTPException(status_code=400, detail=f"视图字段校验失败: {err}")

    # 权限归类：有 EDIT_VIEWS → 公共视图（owner_id=None）；仅 READ → 个人视图（归属创建者）
    is_public = check_action(db, dt, current_user, TableAction.EDIT_VIEWS)
    # is_default 是**表级**标记（会清掉同表其它默认视图）：个人视图对全表不可见，
    # 若允许其持有默认位，等价于仅 READ 用户即可"抢走"全表落地页（ADR 0003 §2）
    if payload.is_default and not is_public:
        raise HTTPException(status_code=400, detail="仅具备视图编辑权限者可设置默认视图")
    dv = _create_view_obj(db, table_id, payload, owner_id=None if is_public else current_user.id)
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

    existing_names = {r[0] for r in db.query(DataView.name).filter(DataView.table_id == table_id).all()}
    created: list[DataView] = []
    skipped: list[str] = []

    # 权限归类：与 create_view 一致 —— 有 EDIT_VIEWS 导入为公共视图，否则个人视图
    is_public = check_action(db, dt, current_user, TableAction.EDIT_VIEWS)
    owner_id: int | None = None if is_public else current_user.id

    for vc in payload:
        if vc.name in existing_names:
            skipped.append(f"已存在: {vc.name}")
            continue
        ok, err = _validate_view_fields(vc, table_id, db)
        if not ok:
            skipped.append(f"跳过 {vc.name}: {err}")
            continue
        if not is_public and vc.is_default:
            # 导入者无 EDIT_VIEWS → 只能落个人视图，个人视图不可占表级默认位（同 create_view）
            vc = vc.model_copy(update={"is_default": False})
        dv = _create_view_obj(db, table_id, vc, owner_id=owner_id)
        db.add(dv)
        created.append(dv)
        existing_names.add(vc.name)

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
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 可见性统一由 view_access 判定：公共视图（owner_id IS NULL）+ 本人个人视图
    return (
        db.query(DataView)
        .filter(DataView.table_id == table_id, visible_view_filter(current_user.id))
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
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    q = db.query(DataView).filter(
        DataView.table_id == table_id,
        # 可见性：与 list_views 一致 —— 公共视图 + 本人个人视图
        visible_view_filter(current_user.id),
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

    # is_default 是**表级**标记（会清掉同表其它默认视图）：个人视图对全表不可见，
    # 允许其持有默认位等价于仅 READ 用户即可"抢走"全表落地页（ADR 0003 §2）
    if payload.is_default and dv.owner_id is not None:
        raise HTTPException(status_code=400, detail="仅具备视图编辑权限者可设置默认视图")

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
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 删除需 VIEW_MANAGE：本人个人视图放行；公共视图需表 EDIT_VIEWS（I7）
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_MANAGE)

    was_default = dv.is_default
    db.delete(dv)
    db.flush()
    if was_default:
        # 删除的是默认视图 → 把默认标记转移给同表剩余视图（按 order/id 取第一个），避免出现"无默认视图".
        # 候选必须是公共视图：个人视图对全表不可见，让它持有 is_default 会让其他成员进表看到空白（缺陷 ⑥）.
        next_default = (
            db.query(DataView)
            .filter(DataView.table_id == table_id, DataView.owner_id.is_(None))
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
        .filter(DataView.table_id == table_id, visible_view_filter(current_user.id))
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
