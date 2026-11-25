"""documents 插件路由：导出模板（ADR 0152）.

端点一览（挂 ``/{workspace_id}/documents/templates``，必须在 ``/{doc_id}`` 一族之前挂载）：

- GET    ""              列表（内置只读预设 + 工作区自定义 + 当前默认引用），成员可读
- GET    /{ref}          单个模板（``builtin:<key>`` 或行 id）
- POST   ""              新建 / 从内置预设另存为（editor+）
- PUT    /{id}           更新名称 / 描述 / 配置 / 设为默认（editor+）
- DELETE /{id}           删除自定义模板（editor+；默认模板删除后回落内置 standard）
- POST   /preview        用未保存配置渲染示例 docx / pdf（成员，不落库）

内置预设只能被引用或另存为：任何指向 ``builtin:<key>`` 的写操作都返回 400（I4）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import BadRequestError, NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents import services
from cndb.plugins.documents.schemas import (
    ExportTemplateCreate,
    ExportTemplatePreview,
    ExportTemplateUpdate,
)
from cndb.plugins.workspaces.permissions import get_member_role, raise_permission_denied

router = APIRouter(prefix="/{workspace_id}/documents/templates", tags=["documents"])

_PREVIEW_CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


def _require_member(db: Session, workspace_id: int, user: User) -> None:
    """读权限：工作区成员（与文档读取同口径）."""
    from cndb.plugins.workspaces.models import Workspace

    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("工作区不存在")
    if get_member_role(user, ws, db) is None:
        raise_permission_denied(db, ws, user)


@router.get("")
def list_export_templates(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """列出内置预设与工作区自定义模板（成员可读）."""
    _require_member(db, workspace_id, current_user)
    return services.export_template_store.list_templates(db, workspace_id)


@router.get("/{ref}")
def get_export_template(
    workspace_id: int,
    ref: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """单个模板详情（内置 key 或行 id；跨工作区 404）."""
    _require_member(db, workspace_id, current_user)
    return services.export_template_store.get_template(db, workspace_id, ref)


@router.post("", status_code=201)
def create_export_template(
    workspace_id: int,
    payload: ExportTemplateCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """新建模板：``preset_key`` 另存为内置预设，或直接提交完整 ``config``（editor+）."""
    services.content.require_editor(db, workspace_id, current_user)
    return services.export_template_store.create_template(
        db,
        workspace_id,
        current_user,
        name=payload.name,
        description=payload.description,
        preset_key=payload.preset_key,
        config=payload.config,
    )


@router.put("/{template_id}")
def update_export_template(
    workspace_id: int,
    template_id: int,
    payload: ExportTemplateUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """更新模板 / 设为默认（editor+）."""
    services.content.require_editor(db, workspace_id, current_user)
    return services.export_template_store.update_template(
        db,
        workspace_id,
        template_id,
        name=payload.name,
        description=payload.description,
        config=payload.config,
        is_default=payload.is_default,
    )


@router.delete("/{template_id}")
def delete_export_template(
    workspace_id: int,
    template_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """删除自定义模板（editor+）；删除默认模板后回落内置 standard."""
    services.content.require_editor(db, workspace_id, current_user)
    return services.export_template_store.delete_template(db, workspace_id, template_id)


@router.post("/preview")
def preview_export_template(
    workspace_id: int,
    payload: ExportTemplatePreview,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    fmt: Annotated[str, Query(alias="format")] = "docx",
) -> Response:
    """用未保存配置（或已存在模板）渲染示例件，不落库、不写审计（成员）."""
    _require_member(db, workspace_id, current_user)
    content_type = _PREVIEW_CONTENT_TYPES.get(fmt.strip().lower())
    if content_type is None:
        raise BadRequestError("示例预览只支持 docx / pdf")
    data = services.export_template_store.render_preview(
        db, workspace_id, fmt=fmt.strip().lower(), config=payload.config, ref=payload.ref
    )
    filename = "template-preview." + fmt.strip().lower()
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
