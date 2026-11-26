"""内容模板 CRUD 服务（需求 0169）.

内容模板是工作区级 Markdown 正文骨架，供「从模板新建文档」使用。
与导出模板（ADR 0152）完全独立：不参与导出渲染、不预置内置行、无默认锚点。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError, NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import ContentTemplate


def list_content_templates(db: Session, workspace_id: int) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(ContentTemplate)
            .where(ContentTemplate.workspace_id == workspace_id)
            .order_by(ContentTemplate.sort_order, ContentTemplate.id)
        )
        .scalars()
        .all()
    )
    return [_serialize(row) for row in rows]


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
) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise BadRequestError("模板名称不能为空")
    if db.execute(
        select(ContentTemplate.id).where(
            ContentTemplate.workspace_id == workspace_id,
            ContentTemplate.name == name,
        )
    ).first():
        raise BadRequestError(f"模板名称「{name}」已存在")
    row = ContentTemplate(
        workspace_id=workspace_id,
        name=name,
        content_markdown=content_markdown,
        description=description.strip(),
        icon=icon.strip(),
        sort_order=sort_order,
        created_by_id=user.id,
    )
    db.add(row)
    _commit_or_conflict(db, name)
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
) -> dict[str, Any]:
    row = _get(db, workspace_id, template_id)
    if name is not None:
        name = name.strip()
        if not name:
            raise BadRequestError("模板名称不能为空")
        duplicate = db.execute(
            select(ContentTemplate.id).where(
                ContentTemplate.workspace_id == workspace_id,
                ContentTemplate.name == name,
                ContentTemplate.id != template_id,
            )
        ).first()
        if duplicate:
            raise BadRequestError(f"模板名称「{name}」已存在")
        row.name = name
    if content_markdown is not None:
        row.content_markdown = content_markdown
    if description is not None:
        row.description = description.strip()
    if icon is not None:
        row.icon = icon.strip()
    if sort_order is not None:
        row.sort_order = sort_order
    _commit_or_conflict(db, row.name)
    db.refresh(row)
    return _serialize(row)


def delete_content_template(db: Session, workspace_id: int, template_id: int) -> None:
    row = _get(db, workspace_id, template_id)
    db.delete(row)
    db.commit()


def resolve_template_content(db: Session, workspace_id: int, template_id: int) -> str:
    """取模板正文（供「从模板新建文档」）；跨工作区按 404。"""
    return _get(db, workspace_id, template_id).content_markdown


def _commit_or_conflict(db: Session, name: str) -> None:
    """并发创建 / 改名撞 ``(workspace_id, name)`` 唯一约束时转 400 而非 500."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise BadRequestError(f"模板名称「{name}」已存在") from exc


def _get(db: Session, workspace_id: int, template_id: int) -> ContentTemplate:
    row = db.get(ContentTemplate, template_id)
    if row is None or row.workspace_id != workspace_id:
        raise NotFoundError("内容模板不存在")
    return row


def _serialize(row: ContentTemplate) -> dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "name": row.name,
        "content_markdown": row.content_markdown,
        "description": row.description,
        "icon": row.icon,
        "sort_order": row.sort_order,
        "created_by_id": row.created_by_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


__all__ = [
    "create_content_template",
    "delete_content_template",
    "get_content_template",
    "list_content_templates",
    "resolve_template_content",
    "update_content_template",
]
