"""documents 插件路由：图表实例与渲染 API（ADR 0048）.

端点（挂 /{workspace_id}/charts）：
- GET    /templates          两级清单（类别 → 模板，成员）
- POST   /render-preview     不落库渲染（成员，宽松归一，设计器实时预览 D5）
- GET    ""                  实例列表（成员，?category= 按模板类别过滤）
- POST   ""                  建实例（editor+，config 严格校验）
- GET    /{chart_id}/render  渲染 SVG（成员；ETag 304，D10）
- GET    /{chart_id}         实例读（成员）
- PUT    /{chart_id}         全量覆盖（editor+）
- DELETE /{chart_id}         物理删除（editor+，D12）

路由声明顺序：字面段（/templates、/render-preview）必须先于 /{chart_id}。
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import BadRequestError, NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import DocumentChart
from cndb.plugins.documents.schemas import ChartCreate, ChartRenderPreview, ChartUpdate
from cndb.plugins.documents.services import charts
from cndb.plugins.documents.services.content import require_editor
from cndb.plugins.workspaces.models import Workspace
from cndb.plugins.workspaces.permissions import get_member_role, raise_permission_denied

router = APIRouter(prefix="/{workspace_id}/charts", tags=["documents"])

#: render 响应的 SVG 媒体类型
SVG_MEDIA_TYPE = "image/svg+xml"


def _require_member(db: Session, workspace_id: int, user: User) -> None:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("工作区不存在")
    if get_member_role(user, ws, db) is None:
        # ADR 0047：403 文案带角色与拥有者指引
        raise_permission_denied(db, ws, user)


def _get_chart_or_404(db: Session, workspace_id: int, chart_id: int) -> DocumentChart:
    chart = db.get(DocumentChart, chart_id)
    if chart is None or chart.workspace_id != workspace_id:
        raise NotFoundError("图表不存在")
    return chart


def _category_of(template_key: str) -> str | None:
    template = charts.get_template(template_key)
    return template.category if template is not None else None


def _chart_out(chart: DocumentChart) -> dict[str, Any]:
    return {
        "id": chart.id,
        "workspace_id": chart.workspace_id,
        "title": chart.title,
        "template_key": chart.template_key,
        "category": _category_of(chart.template_key),
        "config": chart.config or {},
        "created_by_id": chart.created_by_id,
        "updated_by_id": chart.updated_by_id,
        "created_at": chart.created_at,
        "updated_at": chart.updated_at,
    }


def _render_svg_or_degraded(chart: DocumentChart) -> str:
    """实例渲染：模板下线降级为占位整幅图（边界 3，I5/I6）."""
    try:
        doc = charts.render_chart(chart.template_key, chart.config or {})
    except charts.BadRequestTemplateError:
        return charts.to_svg(charts.render_degraded(chart.id, "[图表引用无效：模板已下线]"))
    return charts.to_svg(doc)


def _etag_for(chart: DocumentChart) -> str:
    """ETag = 实例 id + updated_at + 模板指纹（D10：不落缓存，304 支持即可）."""
    updated = chart.updated_at
    updated_text = updated.isoformat() if isinstance(updated, dt.datetime) else str(updated)
    raw = f"{chart.id}|{updated_text}|{charts.template_fingerprint(chart.template_key)}"
    return '"' + hashlib.sha1(raw.encode("utf-8")).hexdigest() + '"'


@router.get("/templates")
def list_templates(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """两级清单：类别 → 模板（成员，只读注册表）。"""
    _require_member(db, workspace_id, current_user)
    return charts.templates_payload()


@router.post("/render-preview")
def render_preview(
    workspace_id: int,
    payload: ChartRenderPreview,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """不落库渲染（成员，无副作用，D5）：宽松归一、坏值回退默认，供设计器实时预览."""
    _require_member(db, workspace_id, current_user)
    if charts.get_template(payload.template_key) is None:
        raise BadRequestError(f"模板 {payload.template_key} 不存在或已下线")
    doc = charts.render_chart(payload.template_key, payload.config)
    return Response(content=charts.to_svg(doc), media_type=SVG_MEDIA_TYPE)


@router.get("")
def list_charts(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    category: Annotated[str | None, Query(max_length=32)] = None,
) -> dict[str, Any]:
    """实例列表（成员）；``?category=`` 按模板类别过滤。"""
    _require_member(db, workspace_id, current_user)
    stmt = (
        select(DocumentChart)
        .where(DocumentChart.workspace_id == workspace_id)
        .order_by(DocumentChart.updated_at.desc())
    )
    items = db.execute(stmt).scalars().all()
    if category is not None:
        items = [c for c in items if _category_of(c.template_key) == category]
    return {"items": [_chart_out(c) for c in items]}


@router.post("", status_code=201)
def create_chart(
    workspace_id: int,
    payload: ChartCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """建实例（editor+）：template_key 须在注册表内，config 严格校验后归一落库."""
    require_editor(db, workspace_id, current_user)
    normalized = charts.require_valid_config(payload.template_key, payload.config)
    chart = DocumentChart(
        workspace_id=workspace_id,
        title=payload.title,
        template_key=payload.template_key,
        config=normalized,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
    )
    db.add(chart)
    db.commit()
    db.refresh(chart)
    return _chart_out(chart)


@router.get("/{chart_id}/render")
def render_chart_by_id(
    workspace_id: int,
    chart_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> Response:
    """实例渲染（成员）：SVG + ETag 304（D10）。"""
    _require_member(db, workspace_id, current_user)
    chart = _get_chart_or_404(db, workspace_id, chart_id)
    etag = _etag_for(chart)
    if if_none_match is not None and if_none_match.strip() == etag:
        return Response(status_code=304, headers={"ETag": etag})
    svg = _render_svg_or_degraded(chart)
    return Response(content=svg, media_type=SVG_MEDIA_TYPE, headers={"ETag": etag})


@router.get("/{chart_id}")
def get_chart(
    workspace_id: int,
    chart_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """实例读（成员）。"""
    _require_member(db, workspace_id, current_user)
    chart = _get_chart_or_404(db, workspace_id, chart_id)
    return _chart_out(chart)


@router.put("/{chart_id}")
def update_chart(
    workspace_id: int,
    chart_id: int,
    payload: ChartUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """全量覆盖（editor+，边界 8）：title / template_key / config 整体替换."""
    require_editor(db, workspace_id, current_user)
    chart = _get_chart_or_404(db, workspace_id, chart_id)
    normalized = charts.require_valid_config(payload.template_key, payload.config)
    chart.title = payload.title
    chart.template_key = payload.template_key
    chart.config = normalized
    chart.updated_by_id = current_user.id
    db.commit()
    db.refresh(chart)
    return _chart_out(chart)


@router.delete("/{chart_id}")
def delete_chart(
    workspace_id: int,
    chart_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """物理删除（editor+，D12）：正文引用处按 I5 降级，不阻止删除."""
    require_editor(db, workspace_id, current_user)
    chart = _get_chart_or_404(db, workspace_id, chart_id)
    db.delete(chart)
    db.commit()
    return {"id": chart_id, "deleted": True}


__all__ = ["router"]
