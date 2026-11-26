"""documents 插件路由：内容模板（需求 0169 / ADR 0177）.

端点挂 ``/{workspace_id}/document-content-templates``。内容模板是「从模板新建文档」的
正文骨架，与导出模板 ``/{workspace_id}/documents/templates``（ADR 0152）**模型独立**，
只共用 ``services/templates_common`` 的契约层（名称唯一 / 404 / 列表 envelope / 门控）。

- GET    ""          列表（成员可读；`{items, total}`）
- GET    /{id}       单个模板（成员可读；跨工作区 404）
- POST   ""          新建（editor+，工作区内名称唯一）
- PATCH  /{id}       更新（editor+）
- PUT    /{id}       更新（editor+，与 PATCH 等价，ADR 0177 D6）
- POST   /{id}/duplicate  创建副本（editor+，ADR 0177 C5）
- DELETE /{id}       删除（editor+）

模板是配置而非文档：不参与文档可见性 H33 过滤，也不新开文档写路径。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.documents import services
from cndb.plugins.documents.schemas import ContentTemplateCreate, ContentTemplateUpdate
from cndb.plugins.documents.services import templates_common

router = APIRouter(prefix="/{workspace_id}/document-content-templates", tags=["documents"])


def _require_member(db: Session, workspace_id: int, user: User) -> None:
    """读权限：工作区成员（与文档读取同口径，H64）."""
    templates_common.require_member(db, workspace_id, user)


@router.get("")
def list_content_templates(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """列出工作区内容模板（成员可读）."""
    _require_member(db, workspace_id, current_user)
    return services.content_templates.list_content_templates(db, workspace_id)


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
        export_template_ref=payload.export_template_ref,
    )


def _apply_update(
    db: Session,
    workspace_id: int,
    template_id: int,
    payload: ContentTemplateUpdate,
) -> dict[str, Any]:
    return services.content_templates.update_content_template(
        db,
        workspace_id,
        template_id,
        name=payload.name,
        content_markdown=payload.content_markdown,
        description=payload.description,
        icon=payload.icon,
        sort_order=payload.sort_order,
        export_template_ref=payload.export_template_ref,
        # 「传 null = 清除绑定」靠字段是否出现在请求体判定（省略 = 不变）
        clear_export_template_ref=(
            "export_template_ref" in payload.model_fields_set and payload.export_template_ref is None
        ),
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
    return _apply_update(db, workspace_id, template_id, payload)


@router.put("/{template_id}")
def replace_content_template(
    workspace_id: int,
    template_id: int,
    payload: ContentTemplateUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """与 PATCH 等价的别名（ADR 0177 D6：两类模板的更新动词保持同一套）."""
    services.content.require_editor(db, workspace_id, current_user)
    return _apply_update(db, workspace_id, template_id, payload)


@router.post("/{template_id}/duplicate", status_code=201)
def duplicate_content_template(
    workspace_id: int,
    template_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """创建副本（editor+；名称「原名 副本」并递增）."""
    services.content.require_editor(db, workspace_id, current_user)
    return services.content_templates.duplicate_content_template(db, workspace_id, current_user, template_id)


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
