"""documents 插件路由：文档管理 API.

端点一览（均挂 /{workspace_id}/documents 前缀）：
- POST   ""                          创建文档/文件夹（editor+）
- GET    ""                          列表（成员，支持 parent/status/tag 筛选）
- GET    /tree                       树形列表（含子节点计数）
- GET    /{doc_id}                   详情（不含内容）
- GET    /{doc_id}/content           详情 + 最新内容
- PUT    /{doc_id}/content           更新内容（乐观锁，editor+）
- PATCH  /{doc_id}                   更新元数据（标题/状态/移动/标签，editor+）
- DELETE /{doc_id}                   软删除（editor+）
- GET    /{doc_id}/versions          版本列表
- GET    /{doc_id}/versions/{num}    版本详情（含内容）
- GET    /{doc_id}/diff              版本差异
- POST   /{doc_id}/rollback          回滚（editor+）
- POST   /{doc_id}/lock              获取编辑锁
- DELETE /{doc_id}/lock              释放编辑锁
- GET    /{doc_id}/lock              查询锁状态
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import ConflictError, NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents import services
from cndb.plugins.documents.models import Document, DocumentVersion, Tag
from cndb.plugins.documents.schemas import (
    ContentUpdate,
    DocumentCreate,
    DocumentUpdate,
    RollbackRequest,
    TagIdsRequest,
)
from cndb.plugins.workspaces.permissions import get_member_role

router = APIRouter(prefix="/{workspace_id}/documents", tags=["documents"])


def _require_member(db: Session, workspace_id: int, user: User) -> None:
    """校验当前用户是工作区成员（读权限最低要求）。"""
    from cndb.plugins.workspaces.models import Workspace

    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("工作区不存在")
    if get_member_role(user, ws, db) is None:
        from cndb.core.errors import PermissionDeniedError

        raise PermissionDeniedError("非工作区成员")


# ── 文档 CRUD ──


@router.post("", status_code=201)
def create_document(
    workspace_id: int,
    payload: DocumentCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """创建文档或文件夹（editor+）。"""
    services.content.require_editor(db, workspace_id, current_user)
    doc = services.content.create_document(
        db,
        workspace_id,
        current_user,
        title=payload.title,
        content=payload.content,
        is_folder=payload.is_folder,
        parent_id=payload.parent_id,
        status=payload.status,
        tag_ids=payload.tag_ids,
        sort_order=payload.sort_order,
    )
    return services.content.serialize_document(db, doc)


@router.get("")
def list_documents(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    parent_id: int | None = Query(default=None),
    status: str | None = Query(default=None, pattern="^(draft|published|archived)$"),
    tag_id: int | None = Query(default=None),
    q_title: str | None = Query(default=None, max_length=200),
    order: str = Query(default="sort", pattern="^(sort|updated|created|title)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """文档列表（工作区成员）。"""
    _require_member(db, workspace_id, current_user)

    # 共享筛选条件（数据查询与 total 计数一致）
    filters: list[ColumnElement[bool]] = [
        Document.workspace_id == workspace_id,
        Document.is_deleted == False,  # noqa: E712
    ]
    if parent_id is not None:
        filters.append(Document.parent_id == parent_id)
    if status:
        filters.append(Document.status == status)
    if q_title:
        filters.append(Document.title.contains(q_title))
    if tag_id is not None:
        from cndb.plugins.documents.models import DocumentTag

        filters.append(Document.id.in_(select(DocumentTag.document_id).where(DocumentTag.tag_id == tag_id)))

    total = int(db.execute(select(func.count()).select_from(Document).where(*filters)).scalar_one())

    order_col = {
        "sort": (Document.sort_order, Document.id),
        "updated": (Document.updated_at.desc(),),
        "created": (Document.created_at.desc(),),
        "title": (Document.title,),
    }[order]
    stmt = select(Document).where(*filters).order_by(*order_col).limit(limit).offset(offset)
    docs = db.execute(stmt).scalars().all()
    return {
        "items": [services.content.serialize_document(db, d) for d in docs],
        "total": total,
    }


@router.get("/tree")
def document_tree(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """全量文档树（工作区成员，含文件夹层级）。"""
    _require_member(db, workspace_id, current_user)
    docs = (
        db.execute(
            select(Document)
            .where(Document.workspace_id == workspace_id, Document.is_deleted == False)  # noqa: E712
            .order_by(Document.sort_order, Document.id)
        )
        .scalars()
        .all()
    )
    return {"items": [services.content.serialize_document(db, d) for d in docs]}


@router.get("/tags")
def list_tags(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """工作区内所有标签（按 doc_count 倒序）。

    注意：必须定义在 /{doc_id} 之前，否则 "tags" 会被解析为 doc_id。
    """
    _require_member(db, workspace_id, current_user)
    tags = (
        db.execute(select(Tag).where(Tag.workspace_id == workspace_id).order_by(Tag.doc_count.desc(), Tag.name))
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": t.id,
                "workspace_id": t.workspace_id,
                "name": t.name,
                "color": t.color,
                "description": t.description,
                "doc_count": t.doc_count,
            }
            for t in tags
        ]
    }


@router.get("/search")
def search(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: str = Query(min_length=1, max_length=200, description="FTS5 查询串"),
    tag_id: int | None = Query(default=None),
    status: str | None = Query(default=None, pattern="^(draft|published|archived)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """FTS5 全文检索（工作区成员）。

    注意：必须定义在 /{doc_id} 之前，否则 "search" 会被解析为 doc_id。
    """
    _require_member(db, workspace_id, current_user)
    services.search.ensure_fts_schema(db)
    items, total = services.search.search_documents(
        db,
        q,
        workspace_id=workspace_id,
        tag_ids=[tag_id] if tag_id else None,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "query": q}


@router.get("/{doc_id}")
def get_document(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """文档详情（不含正文）。"""
    _require_member(db, workspace_id, current_user)
    doc = services.content.get_document_or_404(db, workspace_id, doc_id)
    return services.content.serialize_document(db, doc)


@router.get("/{doc_id}/content")
def get_document_content(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """文档详情 + 最新版本正文。"""
    _require_member(db, workspace_id, current_user)
    doc = services.content.get_document_or_404(db, workspace_id, doc_id)
    data = services.content.serialize_document(db, doc)
    if doc.is_folder:
        data["content"] = ""
    else:
        v = services.content.latest_version(db, doc.id)
        data["content"] = services.content.load_content(v, doc)
        data["version_number"] = v.version_number if v else 0
    lock = services.edit_lock.edit_lock_registry.status(doc.id)
    data["edit_lock"] = (
        {"user_id": lock.user_id, "username": lock.username, "elapsed_seconds": lock.elapsed_seconds} if lock else None
    )
    return data


@router.put("/{doc_id}/content")
def update_document_content(
    workspace_id: int,
    doc_id: int,
    payload: ContentUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """更新内容（乐观锁：base_updated_at 失配返回 409）。"""
    doc = services.content.update_content(
        db,
        workspace_id,
        doc_id,
        current_user,
        content=payload.content,
        change_summary=payload.change_summary,
        base_updated_at=payload.base_updated_at,
    )
    data = services.content.serialize_document(db, doc)
    v = services.content.latest_version(db, doc.id)
    data["content"] = payload.content
    data["version_number"] = v.version_number if v else 0
    return data


@router.patch("/{doc_id}")
def update_document_meta(
    workspace_id: int,
    doc_id: int,
    payload: DocumentUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """更新元数据（标题/状态/移动/排序/标签）。"""
    doc = services.content.get_document_or_404(db, workspace_id, doc_id)
    services.content.require_editor(db, workspace_id, current_user)

    if payload.title is not None:
        doc.title = payload.title
        doc.slug = services.parse.generate_slug(payload.title, doc.id)
    if payload.status is not None:
        doc.status = payload.status
    if payload.sort_order is not None:
        doc.sort_order = payload.sort_order
    if payload.parent_id is not None and payload.parent_id != doc.parent_id:
        if payload.parent_id == doc.id:
            raise ConflictError("不能将文档移动到自身")
        parent = services.content.get_document_or_404(db, workspace_id, payload.parent_id)
        if not parent.is_folder:
            raise ConflictError("父节点必须是文件夹")
        doc.parent_id = payload.parent_id
    if payload.tag_ids is not None:
        services.content._apply_tags(db, doc, payload.tag_ids, current_user)

    doc.updated_by_id = current_user.id
    db.commit()
    db.refresh(doc)
    return services.content.serialize_document(db, doc)


@router.delete("/{doc_id}")
def delete_document(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """软删除（文件夹递归删除子节点）。"""
    doc = services.content.soft_delete_document(db, workspace_id, doc_id, current_user)
    return {"id": doc.id, "deleted": True}


# ── 版本 ──


@router.get("/{doc_id}/versions")
def list_versions(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """版本列表（倒序）。"""
    _require_member(db, workspace_id, current_user)
    services.content.get_document_or_404(db, workspace_id, doc_id)
    stmt = (
        select(DocumentVersion)
        .where(DocumentVersion.document_id == doc_id)
        .order_by(DocumentVersion.version_number.desc())
        .limit(limit)
        .offset(offset)
    )
    versions = db.execute(stmt).scalars().all()
    total = int(db.execute(select(func.count()).where(DocumentVersion.document_id == doc_id)).scalar_one())
    return {
        "items": [
            {
                "id": v.id,
                "document_id": v.document_id,
                "version_number": v.version_number,
                "content_size": v.content_size,
                "content_hash": v.content_hash,
                "change_summary": v.change_summary,
                "change_type": v.change_type,
                "created_at": v.created_at,
                "created_by_id": v.created_by_id,
            }
            for v in versions
        ],
        "total": total,
    }


@router.get("/{doc_id}/versions/{version_number}")
def get_version(
    workspace_id: int,
    doc_id: int,
    version_number: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """版本详情（含正文）。"""
    _require_member(db, workspace_id, current_user)
    doc = services.content.get_document_or_404(db, workspace_id, doc_id)
    v = db.execute(
        select(DocumentVersion).where(
            DocumentVersion.document_id == doc_id,
            DocumentVersion.version_number == version_number,
        )
    ).scalar_one_or_none()
    if v is None:
        raise NotFoundError(f"版本 v{version_number} 不存在")
    return {
        "id": v.id,
        "document_id": v.document_id,
        "version_number": v.version_number,
        "content_size": v.content_size,
        "content_hash": v.content_hash,
        "change_summary": v.change_summary,
        "change_type": v.change_type,
        "created_at": v.created_at,
        "created_by_id": v.created_by_id,
        "content": services.content.load_content(v, doc),
    }


@router.get("/{doc_id}/diff")
def diff_versions(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    base: int = Query(description="基准版本号"),
    head: int = Query(description="对比版本号"),
) -> dict[str, Any]:
    """两版本 unified diff 对比。"""
    _require_member(db, workspace_id, current_user)
    doc = services.content.get_document_or_404(db, workspace_id, doc_id)

    def _load(num: int) -> str:
        v = db.execute(
            select(DocumentVersion).where(
                DocumentVersion.document_id == doc_id,
                DocumentVersion.version_number == num,
            )
        ).scalar_one_or_none()
        if v is None:
            raise NotFoundError(f"版本 v{num} 不存在")
        return services.content.load_content(v, doc)

    diff_text, added, removed = services.parse.unified_diff(_load(base), _load(head))
    return {
        "document_id": doc_id,
        "base_version": base,
        "head_version": head,
        "diff": diff_text,
        "added": added,
        "removed": removed,
    }


@router.post("/{doc_id}/rollback")
def rollback(
    workspace_id: int,
    doc_id: int,
    payload: RollbackRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """回滚到指定版本（创建 rollback 类型新版本）。"""
    doc = services.content.rollback_version(db, workspace_id, doc_id, current_user, payload.target_version)
    return services.content.serialize_document(db, doc)


# ── 编辑锁 ──


@router.post("/{doc_id}/lock", status_code=200)
def acquire_lock(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """获取编辑锁（进入编辑器时调用）。"""
    _require_member(db, workspace_id, current_user)
    services.content.get_document_or_404(db, workspace_id, doc_id)
    info = services.edit_lock.edit_lock_registry.acquire(
        doc_id, current_user.id, getattr(current_user, "username", f"user{current_user.id}")
    )
    return {"locked": True, "elapsed_seconds": info.elapsed_seconds}


@router.delete("/{doc_id}/lock")
def release_lock(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """释放编辑锁（保存/关闭编辑器时调用）。"""
    services.content.get_document_or_404(db, workspace_id, doc_id)
    services.edit_lock.edit_lock_registry.release(doc_id, current_user.id)
    return {"locked": False}


@router.get("/{doc_id}/lock")
def lock_status(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """查询编辑锁状态。"""
    _require_member(db, workspace_id, current_user)
    services.content.get_document_or_404(db, workspace_id, doc_id)
    info = services.edit_lock.edit_lock_registry.status(doc_id)
    return {
        "locked": info is not None,
        "user_id": info.user_id if info else None,
        "username": info.username if info else None,
        "elapsed_seconds": info.elapsed_seconds if info else 0,
    }


# ── 标签 ──


@router.post("/{doc_id}/tags")
def set_document_tags(
    workspace_id: int,
    doc_id: int,
    payload: TagIdsRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """设置文档标签（全量替换）。"""
    doc = services.content.get_document_or_404(db, workspace_id, doc_id)
    services.content.require_editor(db, workspace_id, current_user)
    services.content._apply_tags(db, doc, payload.tag_ids, current_user)
    db.commit()
    return services.content.serialize_document(db, doc)


__all__ = ["router"]
