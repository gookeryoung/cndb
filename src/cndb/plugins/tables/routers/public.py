"""公开分享路由 —— 匿名访问公开视图/表单."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from cndb.core.database import get_db
from cndb.plugins.tables import records as rec
from cndb.plugins.tables.models import DataTable, DataView

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


@router.get("/share/{slug}")
def public_share_view(
    slug: str,
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """匿名只读 Grid：返回公开视图的筛选规则和行数据."""
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
    return {
        "view": {
            "id": dv.id,
            "name": dv.name,
            "view_type": dv.view_type,
            "filters": dv.filters,
            "sortings": dv.sortings,
        },
        "rows": rows,
        "total": total,
        "table_name": dt.name,
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
