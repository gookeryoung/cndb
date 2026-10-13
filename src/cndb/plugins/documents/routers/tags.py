"""documents 插件路由：标签管理 API.

端点（挂 /{workspace_id}/document-tags，独立于 documents 路径避免与 /{doc_id} 冲突）：
- POST   ""            创建标签（editor+）
- GET    ""            标签列表（成员）
- PATCH  /{tag_id}     更新标签（editor+）
- DELETE /{tag_id}     删除标签（editor+，级联解除文档关联）
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import ConflictError, NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import DocumentTag, Tag
from cndb.plugins.documents.schemas import TagCreate, TagUpdate
from cndb.plugins.documents.services.content import _refresh_tag_counts, require_editor
from cndb.plugins.workspaces.models import Workspace
from cndb.plugins.workspaces.permissions import get_member_role

router = APIRouter(prefix="/{workspace_id}/document-tags", tags=["documents"])


def _require_member(db: Session, workspace_id: int, user: User) -> None:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("工作区不存在")
    if get_member_role(user, ws, db) is None:
        from cndb.core.errors import PermissionDeniedError

        raise PermissionDeniedError("非工作区成员")


def _get_tag_or_404(db: Session, workspace_id: int, tag_id: int) -> Tag:
    tag = db.get(Tag, tag_id)
    if tag is None or tag.workspace_id != workspace_id:
        raise NotFoundError("标签不存在")
    return tag


@router.post("", status_code=201)
def create_tag(
    workspace_id: int,
    payload: TagCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """创建标签（editor+）。"""
    require_editor(db, workspace_id, current_user)
    exists = db.execute(
        select(Tag).where(Tag.workspace_id == workspace_id, Tag.name == payload.name)
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictError(f"标签 {payload.name!r} 已存在")
    tag = Tag(
        workspace_id=workspace_id,
        name=payload.name,
        color=payload.color,
        description=payload.description,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return _tag_out(tag)


@router.get("")
def list_tags(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """标签列表（成员，按 doc_count 倒序）。"""
    _require_member(db, workspace_id, current_user)
    tags = (
        db.execute(select(Tag).where(Tag.workspace_id == workspace_id).order_by(Tag.doc_count.desc(), Tag.name))
        .scalars()
        .all()
    )
    return {"items": [_tag_out(t) for t in tags]}


@router.patch("/{tag_id}")
def update_tag(
    workspace_id: int,
    tag_id: int,
    payload: TagUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """更新标签（editor+）。"""
    require_editor(db, workspace_id, current_user)
    tag = _get_tag_or_404(db, workspace_id, tag_id)
    if payload.name is not None and payload.name != tag.name:
        exists = db.execute(
            select(Tag).where(Tag.workspace_id == workspace_id, Tag.name == payload.name)
        ).scalar_one_or_none()
        if exists is not None:
            raise ConflictError(f"标签 {payload.name!r} 已存在")
        tag.name = payload.name
    if payload.color is not None:
        tag.color = payload.color
    if payload.description is not None:
        tag.description = payload.description
    db.commit()
    db.refresh(tag)
    return _tag_out(tag)


@router.delete("/{tag_id}")
def delete_tag(
    workspace_id: int,
    tag_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """删除标签（editor+，关联关系级联清除）。"""
    require_editor(db, workspace_id, current_user)
    tag = _get_tag_or_404(db, workspace_id, tag_id)
    db.execute(
        DocumentTag.__table__.delete().where(DocumentTag.tag_id == tag.id)  # type: ignore[attr-defined]
    )
    db.delete(tag)
    db.commit()
    return {"id": tag_id, "deleted": True}


def _tag_out(tag: Tag) -> dict[str, Any]:
    return {
        "id": tag.id,
        "workspace_id": tag.workspace_id,
        "name": tag.name,
        "color": tag.color,
        "description": tag.description,
        "doc_count": tag.doc_count,
    }


# _refresh_tag_counts 供文档打标后刷新计数（复用 content 服务实现）
__all__ = ["router"]
_ = _refresh_tag_counts
