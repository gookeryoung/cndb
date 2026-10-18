"""analytics 模板路由：工作区级分析模板 CRUD.

端点（前缀 /{workspace_id}/analytics/templates）：
- GET    ""                 列出模板（工作区成员即可）
- POST   ""                 新建模板（editor+）
- GET    "/{template_id}"   模板详情（成员即可）
- PUT    "/{template_id}"   更新模板（editor+）
- POST   "/{template_id}/duplicate"  复制模板（editor+）
- DELETE "/{template_id}"   删除模板（editor+）
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.analytics import services
from cndb.plugins.analytics.models import AnalyticsTemplate
from cndb.plugins.analytics.schemas import (
    TemplateCreate,
    TemplateDuplicateRequest,
    TemplateResponse,
    TemplateUpdate,
)
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/analytics/templates", tags=["analytics"])


def _require(db: Session, workspace_id: int, user: User, role: WorkspaceRole) -> None:
    """工作区级角色门槛检查."""
    check_workspace_permission(db, workspace_id, user, role)


@router.get("", response_model=list[TemplateResponse])
def list_templates(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[AnalyticsTemplate]:
    """列出该工作区的分析模板（按更新时间倒序）."""
    _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    return (
        db.query(AnalyticsTemplate)
        .filter(AnalyticsTemplate.workspace_id == workspace_id)
        .order_by(AnalyticsTemplate.updated_at.desc(), AnalyticsTemplate.id.desc())
        .all()
    )


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(
    workspace_id: int,
    payload: TemplateCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AnalyticsTemplate:
    """新建分析模板."""
    _require(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    return services.templates.create_template(
        db,
        current_user,
        workspace_id=workspace_id,
        name=payload.name,
        description=payload.description,
        table_id=payload.table_id,
        config=payload.config,
    )


@router.get("/{template_id}", response_model=TemplateResponse)
def get_template(
    workspace_id: int,
    template_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AnalyticsTemplate:
    """模板详情."""
    _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    return services.templates.get_template(db, workspace_id, template_id)


@router.put("/{template_id}", response_model=TemplateResponse)
def update_template(
    workspace_id: int,
    template_id: int,
    payload: TemplateUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AnalyticsTemplate:
    """更新模板."""
    _require(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    tpl = services.templates.get_template(db, workspace_id, template_id)
    return services.templates.update_template(
        db,
        current_user,
        tpl,
        name=payload.name,
        description=payload.description,
        table_id=payload.table_id,
        config=payload.config,
    )


@router.post("/{template_id}/duplicate", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
def duplicate_template(
    workspace_id: int,
    template_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: TemplateDuplicateRequest | None = None,
) -> AnalyticsTemplate:
    """复制模板（不传 name 时自动命名「原名 副本」，重名自动追加序号）."""
    _require(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    tpl = services.templates.get_template(db, workspace_id, template_id)
    return services.templates.duplicate_template(
        db,
        current_user,
        tpl,
        name=payload.name if payload is not None else None,
    )


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    workspace_id: int,
    template_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除模板."""
    _require(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    tpl = services.templates.get_template(db, workspace_id, template_id)
    services.templates.delete_template(db, tpl)


__all__ = ["router"]
