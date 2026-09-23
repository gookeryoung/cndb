"""视图管理路由."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataView
from cndb.plugins.tables.schemas import ViewCreate, ViewResponse, ViewUpdate
from cndb.plugins.tables.services.core.access import TableAction, get_table_or_404

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
    ):
        opt_val = vo.get(opt_key)
        if opt_val and opt_val not in valid_fields:
            return False, f"view_options.{opt_key}='{opt_val}' 不存在"
    return True, None


def _create_view_obj(db: Session, user: User, table_id: int, payload: ViewCreate) -> DataView:
    """创建单个 DataView 对象（不含 commit）."""
    if payload.is_default:
        db.query(DataView).filter(DataView.table_id == table_id).update({"is_default": False})
    return DataView(
        table_id=table_id,
        owner_id=user.id,
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


@router.post("", response_model=ViewResponse, status_code=status.HTTP_201_CREATED)
def create_view(
    workspace_id: int,
    table_id: int,
    payload: ViewCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataView:
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    # 同表视图名唯一
    existing = db.query(DataView).filter(DataView.table_id == table_id, DataView.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="视图名已存在")

    ok, err = _validate_view_fields(payload, table_id, db)
    if not ok:
        raise HTTPException(status_code=400, detail=f"视图字段校验失败: {err}")

    dv = _create_view_obj(db, current_user, table_id, payload)
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
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    existing_names = {r[0] for r in db.query(DataView.name).filter(DataView.table_id == table_id).all()}
    created: list[DataView] = []
    skipped: list[str] = []

    for vc in payload:
        if vc.name in existing_names:
            skipped.append(f"已存在: {vc.name}")
            continue
        ok, err = _validate_view_fields(vc, table_id, db)
        if not ok:
            skipped.append(f"跳过 {vc.name}: {err}")
            continue
        dv = _create_view_obj(db, current_user, table_id, vc)
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
    return db.query(DataView).filter(DataView.table_id == table_id).order_by(DataView.order, DataView.id).all()


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

    q = db.query(DataView).filter(DataView.table_id == table_id)
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
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    dv = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == table_id).first()
    if dv is None:
        raise HTTPException(status_code=404, detail="视图不存在")
    return dv


@router.patch("/{view_id}", response_model=ViewResponse)
def update_view(
    workspace_id: int,
    table_id: int,
    view_id: int,
    payload: ViewUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataView:
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
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
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_VIEWS)
    dv = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == table_id).first()
    if dv is None:
        raise HTTPException(status_code=404, detail="视图不存在")

    was_default = dv.is_default
    db.delete(dv)
    db.flush()
    if was_default:
        # 删除的是默认视图 → 把默认标记转移给同表剩余视图（按 order/id 取第一个），避免出现"无默认视图"
        next_default = (
            db.query(DataView).filter(DataView.table_id == table_id).order_by(DataView.order, DataView.id).first()
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
    """批量调整视图顺序（按传入顺序赋值 order 字段）."""
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_VIEWS)

    views = (
        db.query(DataView)
        .filter(
            DataView.table_id == table_id,
            DataView.id.in_(view_ids),
        )
        .all()
    )

    view_map = {v.id: v for v in views}
    for idx, vid in enumerate(view_ids):
        if vid in view_map:
            view_map[vid].order = idx

    db.commit()
    return db.query(DataView).filter(DataView.table_id == table_id).order_by(DataView.order, DataView.id).all()


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
    dv = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == table_id).first()
    if dv is None:
        raise HTTPException(status_code=404, detail="视图不存在")

    rows, total = rec.list_rows(
        db.get_bind(),
        dt,
        filters=dv.filters or None,
        filter_logic=dv.filter_type,
        sorts=dv.sortings or None,
        limit=limit,
        offset=offset,
        db=db,
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
    dv = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == table_id).first()
    if dv is None:
        raise HTTPException(status_code=404, detail="视图不存在")

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
    dv = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == table_id).first()
    if dv is None:
        raise HTTPException(status_code=404, detail="视图不存在")

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
    )
    return {"rows": rows, "total": total, "start_field": start_field}


# ── 公开分享（P4） ───────────────────────────────────


@router.post("/{view_id}/share")
def create_view_share(
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """为视图生成公开分享 slug."""
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_VIEWS)
    dv = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == table_id).first()
    if dv is None:
        raise HTTPException(status_code=404, detail="视图不存在")

    dv.is_public = True
    dv.public_slug = uuid.uuid4().hex[:12]
    db.commit()
    db.refresh(dv)
    return {
        "slug": dv.public_slug,
        "share_url": f"/api/v1/public/share/{dv.public_slug}",
        "form_url": f"/api/v1/public/forms/{dv.public_slug}" if dv.view_type == "form" else None,
        "is_public": dv.is_public,
    }


@router.delete("/{view_id}/share")
def revoke_view_share(
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """撤销视图公开分享."""
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_VIEWS)
    dv = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == table_id).first()
    if dv is None:
        raise HTTPException(status_code=404, detail="视图不存在")

    dv.is_public = False
    dv.public_slug = None
    db.commit()
    return {"ok": True, "is_public": dv.is_public}
