"""公开分享路由 —— 匿名访问公开视图/表单."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from cndb.core.database import get_db
from cndb.plugins.tables.models import DataField, DataTable, DataView
from cndb.plugins.tables.services.core import records as rec

router = APIRouter(prefix="/api/v1/public", tags=["public"])


def _get_public_view(db: Session, slug: str) -> tuple[DataView, DataTable]:
    """按 public_slug 查找公开视图及其表。"""
    dv = db.query(DataView).filter(DataView.public_slug == slug, DataView.is_public == True).first()  # noqa: E712
    if dv is None:
        raise HTTPException(status_code=404, detail="分享链接无效或已关闭")
    dt = db.query(DataTable).filter(DataTable.id == dv.table_id).first()
    if dt is None:
        raise HTTPException(status_code=404, detail="数据表不存在")
    return dv, dt


def _make_field_sort_key(
    field_order: list[str] | None,
) -> Callable[[DataField], int]:
    """返回一个带完整类型的排序 key 函数, 避免 pyrefly implicit-any-lambda."""
    if field_order:
        order_map: dict[str, int] = {name: i for i, name in enumerate(field_order)}

        def key_by_name(f: DataField) -> int:
            return order_map.get(f.name, 9999)

        return key_by_name

    def key_by_order(f: DataField) -> int:
        return f.order or 0

    return key_by_order


def _sorted_active_fields(fields: list[DataField], field_order: list[str] | None) -> list[DataField]:
    """提取未软删字段并按视图字段顺序（或默认 order）排序."""
    active = [f for f in fields if not f.trashed]
    active.sort(key=_make_field_sort_key(field_order))
    return active


@router.get("/share/{slug}")
def public_share_view(
    slug: str,
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """匿名只读 Grid：返回公开视图的筛选规则、表结构和行数据."""
    dv, dt = _get_public_view(db, slug)
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
    active_fields = _sorted_active_fields(dt.fields, dv.field_order or None)

    return {
        "view": {
            "id": dv.id,
            "name": dv.name,
            "view_type": dv.view_type,
            "filters": dv.filters,
            "sortings": dv.sortings,
        },
        "table": {
            "id": dt.id,
            "name": dt.name,
            "description": dt.description,
            "fields": [
                {
                    "id": f.id,
                    "name": f.name,
                    "field_type": f.field_type,
                    "config": f.config,
                    "required": f.required,
                    "is_unique": f.is_unique,
                }
                for f in active_fields
            ],
        },
        "rows": rows,
        "total": total,
    }


@router.get("/forms/{slug}")
def public_form_view(
    slug: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """公开表单元数据：返回表结构供前端渲染表单."""
    dv, dt = _get_public_view(db, slug)
    if dv.view_type != "form":
        raise HTTPException(status_code=400, detail="该视图不是表单类型")
    active_fields = _sorted_active_fields(dt.fields, dv.field_order or None)
    return {
        "view": {
            "id": dv.id,
            "name": dv.name,
            "view_type": dv.view_type,
        },
        "table": {
            "id": dt.id,
            "name": dt.name,
            "description": dt.description,
            "fields": [
                {
                    "id": f.id,
                    "name": f.name,
                    "field_type": f.field_type,
                    "config": f.config,
                    "required": f.required,
                    "is_unique": f.is_unique,
                }
                for f in active_fields
            ],
        },
    }


@router.post("/forms/{slug}")
def public_form_submit(
    slug: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """匿名提交表单行到公开表单视图."""
    dv, dt = _get_public_view(db, slug)
    if dv.view_type != "form":
        raise HTTPException(status_code=400, detail="该视图不是表单类型")
    row = rec.create_row(db.get_bind(), dt, payload, db=db)
    if row is None:
        raise HTTPException(status_code=500, detail="提交失败")
    return {"id": row.get("id"), "status": "ok"}


__all__ = ["router"]
