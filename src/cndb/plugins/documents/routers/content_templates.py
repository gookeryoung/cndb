"""documents 插件路由：内容模板（需求 0169）.

端点挂 ``/{workspace_id}/document-content-templates``，与导出排版模板
``/{workspace_id}/documents/templates``（ADR 0152）完全独立。

- GET    ""        列表（成员可读）
- GET    /{id}     单个模板（成员可读；跨工作区 404）
- POST   ""        新建（editor+，工作区内名称唯一）
- PATCH  /{id}     更新（editor+）
- DELETE /{id}     删除（editor+）

模板是配置而非文档：不参与文档可见性 H33 过滤，也不新开文档写路径。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents import services
from cndb.plugins.documents.schemas import ContentTemplateCreate, ContentTemplateUpdate
from cndb.plugins.workspaces.permissions import raise_permission_denied, workspace_data_role

router = APIRouter(prefix="/{workspace_id}/document-content-templates", tags=["documents"])


def _require_member(db: Session, workspace_id: int, user: User) -> None:
    """读权限：工作区成员（与文档读取同口径）."""
    from cndb.plugins.workspaces.models import Workspace

    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("工作区不存在")
    if workspace_data_role(user, ws, db) is None:
        raise_permission_denied(db, ws, user)


@router.get("")
def list_content_templates(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """列出工作区内容模板（成员可读）."""
    _require_member(db, workspace_id, current_user)
    items = services.content_templates.list_content_templates(db, workspace_id)
    return {"items": items, "total": len(items)}


@router.get("/{template_id}")
def get_content_template(
    workspace_id: int,
    template_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """单个内容模板详情（成员可读；跨工作区 404）."""
    _require_member(db, workspace_id, current_user)
    return services.content_templates.get_content_template(db, workspace_id, template_id)


@router.post("", status_code=201)
def create_content_template(
    workspace_id: int,
    payload: ContentTemplateCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """新建内容模板（editor+；工作区内重名 400）."""
    services.content.require_editor(db, workspace_id, current_user)
    return services.content_templates.create_content_template(
        db,
        workspace_id,
        current_user,
        name=payload.name,
        content_markdown=payload.content_markdown,
        description=payload.description,
        icon=payload.icon,
        sort_order=payload.sort_order,
    )


@router.patch("/{template_id}")
def update_content_template(
    workspace_id: int,
    template_id: int,
    payload: ContentTemplateUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """更新内容模板（editor+；字段可选）."""
    services.content.require_editor(db, workspace_id, current_user)
    return services.content_templates.update_content_template(
        db,
        workspace_id,
        template_id,
        name=payload.name,
        content_markdown=payload.content_markdown,
        description=payload.description,
        icon=payload.icon,
        sort_order=payload.sort_order,
    )


@router.delete("/{template_id}")
def delete_content_template(
    workspace_id: int,
    template_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """删除内容模板（editor+）."""
    services.content.require_editor(db, workspace_id, current_user)
    services.content_templates.delete_content_template(db, workspace_id, template_id)
    return {"ok": True}
