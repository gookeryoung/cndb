"""内容模板 CRUD 服务（需求 0169）.

内容模板是工作区级 Markdown 正文骨架，供「从模板新建文档」使用。
与导出模板（ADR 0152）完全独立：不参与导出渲染、不预置内置行、无默认锚点。

内置库（ADR 0185）是**代码常量**：不落表、不进备份、无写端点，因此本模块只有
读入口 ``list_builtin_content_templates``，不参与任何写路径。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import ContentTemplate
from cndb.plugins.documents.services import templates_common
from cndb.plugins.documents.services.content_builtins import (
    BuiltinContentTemplate,
    builtin_content_library,
    builtin_content_template,
)
from cndb.plugins.documents.services.export import templates as template_cfg

_TABLE = ContentTemplate


def list_builtin_content_templates() -> dict[str, Any]:
    """内置库（ADR 0185 D1 / D4）：代码常量，只读、不入库、不分页.

    返回 ``{"categories": [...]}``；分类与模板都已按 ``sort_order`` 排序并校验 I2 / I4。
    与自定义列表端点分离，避免 ``id`` 从 ``int`` 变字符串（D4）。
    """
    return builtin_content_library()


def get_builtin_content_template(key: str) -> BuiltinContentTemplate | None:
    """按 key 取内置模板（I3：``ref = builtin:<key>`` 的 key 部分）."""
    return builtin_content_template(key)


def _validated_ref(db: Session, workspace_id: int, ref: str | None) -> str | None:
    """写入口校验绑定引用（ADR 0177 C7）：非法 / 跨区 → 400（ValueError 转 BadRequest）."""
    try:
        return template_cfg.validate_export_template_ref(db, workspace_id, ref)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc


def list_content_templates(db: Session, workspace_id: int) -> dict[str, Any]:
    """列表载荷统一为 `{items, total}`（ADR 0177 C4）."""
    rows = (
        db.execute(
            select(ContentTemplate)
            .where(ContentTemplate.workspace_id == workspace_id)
            .order_by(ContentTemplate.sort_order, ContentTemplate.id)
        )
        .scalars()
        .all()
    )
    return templates_common.list_envelope([_serialize(row) for row in rows])


def get_content_template(db: Session, workspace_id: int, template_id: int) -> dict[str, Any]:
    row = _get(db, workspace_id, template_id)
    return _serialize(row)


def create_content_template(
    db: Session,
    workspace_id: int,
    user: User,
    *,
    name: str,
    content_markdown: str,
    description: str = "",
    icon: str = "",
    sort_order: int = 0,
    export_template_ref: str | None = None,
) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise BadRequestError("模板名称不能为空")
    templates_common.ensure_name_free(db, _TABLE, workspace_id, name)
    bound_ref = _validated_ref(db, workspace_id, export_template_ref)
    row = ContentTemplate(
        workspace_id=workspace_id,
        name=name,
        content_markdown=content_markdown,
        description=description.strip(),
        icon=icon.strip(),
        sort_order=sort_order,
        export_template_ref=bound_ref,
        created_by_id=user.id,
    )
    db.add(row)
    templates_common.commit_or_conflict(db, name)
    db.refresh(row)
    return _serialize(row)


def update_content_template(
    db: Session,
    workspace_id: int,
    template_id: int,
    *,
    name: str | None = None,
    content_markdown: str | None = None,
    description: str | None = None,
    icon: str | None = None,
    sort_order: int | None = None,
    export_template_ref: str | None = None,
    clear_export_template_ref: bool = False,
) -> dict[str, Any]:
    row = _get(db, workspace_id, template_id)
    if name is not None:
        name = name.strip()
        if not name:
            raise BadRequestError("模板名称不能为空")
        templates_common.ensure_name_free(db, _TABLE, workspace_id, name, exclude_id=template_id)
        row.name = name
    if content_markdown is not None:
        row.content_markdown = content_markdown
    if description is not None:
        row.description = description.strip()
    if icon is not None:
        row.icon = icon.strip()
    if sort_order is not None:
        row.sort_order = sort_order
    if clear_export_template_ref:
        row.export_template_ref = None
    elif export_template_ref is not None:
        row.export_template_ref = _validated_ref(db, workspace_id, export_template_ref)
    templates_common.commit_or_conflict(db, row.name)
    db.refresh(row)
    return _serialize(row)


def delete_content_template(db: Session, workspace_id: int, template_id: int) -> None:
    row = _get(db, workspace_id, template_id)
    db.delete(row)
    db.commit()


def resolve_template_content(db: Session, workspace_id: int, template_id: int) -> str:
    """取模板正文（供「从模板新建文档」）；跨工作区按 404。"""
    return _get(db, workspace_id, template_id).content_markdown


def duplicate_content_template(db: Session, workspace_id: int, user: User, template_id: int) -> dict[str, Any]:
    """创建副本（ADR 0177 C5）：名称 `原名 副本`，重名递增（与需求 0172 同口径）。"""
    source = _get(db, workspace_id, template_id)
    base = f"{source.name} 副本"
    name = base
    serial = 2
    while db.execute(
        select(ContentTemplate.id).where(
            ContentTemplate.workspace_id == workspace_id,
            ContentTemplate.name == name,
        )
    ).first():
        name = f"{base} {serial}"
        serial += 1
    row = ContentTemplate(
        workspace_id=workspace_id,
        name=name,
        content_markdown=source.content_markdown,
        description=source.description,
        icon=source.icon,
        sort_order=source.sort_order,
        export_template_ref=source.export_template_ref,
        created_by_id=user.id,
    )
    db.add(row)
    templates_common.commit_or_conflict(db, name)
    db.refresh(row)
    return _serialize(row)


def _get(db: Session, workspace_id: int, template_id: int) -> ContentTemplate:
    return templates_common.get_or_404(db, _TABLE, workspace_id, template_id, message="内容模板不存在")


def _serialize(row: ContentTemplate) -> dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "name": row.name,
        "content_markdown": row.content_markdown,
        "description": row.description,
        "icon": row.icon,
        "sort_order": row.sort_order,
        "export_template_ref": row.export_template_ref,
        "created_by_id": row.created_by_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


__all__ = [
    "create_content_template",
    "delete_content_template",
    "duplicate_content_template",
    "get_builtin_content_template",
    "get_content_template",
    "list_builtin_content_templates",
    "list_content_templates",
    "resolve_template_content",
    "update_content_template",
]
