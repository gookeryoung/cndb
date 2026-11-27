"""文档响应序列化与个人置顶（ADR 0180 D1）."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.plugins.documents.models import (
    DOC_STATUS_PUBLISHED,
    Document,
    DocumentPin,
    DocumentTag,
    DocumentVersion,
)

if TYPE_CHECKING:
    pass


from . import storage

logger = logging.getLogger("cndb.plugins.documents.services.content")


def _normalize_ts(ts: str) -> str:
    """时间戳宽松归一化（去时区/毫秒差异，仅保留秒级）。"""
    ts = ts.strip().replace("T", " ").rstrip("Z")
    if "+" in ts:
        ts = ts.split("+")[0]
    return ts[:19]


def serialize_document(db: Session, doc: Document, *, pinned: bool = False) -> dict[str, Any]:
    """单文档 → 响应字典（详情/写操作回包用）。"""
    tag_ids = [
        row.tag_id for row in db.execute(select(DocumentTag.tag_id).where(DocumentTag.document_id == doc.id)).all()
    ]
    total = 0 if doc.is_folder else storage.version_count(db, doc.id)
    return _serialize_document(
        doc,
        version_total=total,
        tag_ids=tag_ids,
        pinned=pinned,
    )


def pinned_document_ids(db: Session, workspace_id: int, user_id: int) -> set[int]:
    """当前用户在该工作区的置顶文档 id 集合（个人偏好，一次查询）."""
    rows = db.execute(
        select(DocumentPin.document_id)
        .join(Document, Document.id == DocumentPin.document_id)
        .where(Document.workspace_id == workspace_id, DocumentPin.user_id == user_id)
    ).all()
    return {int(row[0]) for row in rows}


def sort_pinned_first(docs: list[Document], pinned_ids: set[int]) -> list[Document]:
    """置顶文档排在前面；两组内部保持原有顺序（`sorted` 稳定）."""
    if not pinned_ids:
        return docs
    return sorted(docs, key=lambda d: 0 if d.id in pinned_ids else 1)


def set_document_pin(db: Session, doc: Document, user_id: int, pinned: bool) -> bool:
    """设置 / 取消文档置顶（幂等），返回最终状态.

    个人语义：只影响该用户自己的置顶集合，不改变其他成员看到的顺序。
    """
    existing = db.execute(
        select(DocumentPin).where(DocumentPin.document_id == doc.id, DocumentPin.user_id == user_id)
    ).scalar_one_or_none()
    if pinned and existing is None:
        db.add(DocumentPin(document_id=doc.id, user_id=user_id))
        db.commit()
    elif not pinned and existing is not None:
        db.delete(existing)
        db.commit()
    return pinned


def serialize_documents(
    db: Session, docs: list[Document], *, pinned_ids: set[int] | None = None
) -> list[dict[str, Any]]:
    """批量文档 → 响应字典（列表/树用）.

    用 2 条聚合查询替代逐文档的 ``version_count`` + ``tag_ids`` 查询，
    消除大文档树（数百节点）上的 N+1。
    """
    if not docs:
        return []
    ids = [d.id for d in docs]
    counts = {
        row[0]: row[1]
        for row in db.execute(
            select(DocumentVersion.document_id, func.count())
            .where(DocumentVersion.document_id.in_(ids))
            .group_by(DocumentVersion.document_id)
        ).all()
    }
    tag_ids: dict[int, list[int]] = defaultdict(list)
    for doc_id, tag_id in db.execute(
        select(DocumentTag.document_id, DocumentTag.tag_id).where(DocumentTag.document_id.in_(ids))
    ).all():
        tag_ids[doc_id].append(tag_id)
    pinned = pinned_ids or set()
    return [
        _serialize_document(
            doc,
            version_total=0 if doc.is_folder else int(counts.get(doc.id, 0)),
            tag_ids=tag_ids.get(doc.id, []),
            pinned=doc.id in pinned,
        )
        for doc in docs
    ]


def _document_visibility(doc: Document) -> str:
    """可见性标签：workspace（已发布）/ private（仅自己与所有者）."""
    if doc.status == DOC_STATUS_PUBLISHED:
        return "workspace"
    return "private"


def _serialize_document(
    doc: Document,
    *,
    version_total: int,
    tag_ids: list[int],
    pinned: bool = False,
) -> dict[str, Any]:
    """文档 → 响应字典主体（版本数/标签由调用方提供，避免逐条查询）."""
    return {
        "id": doc.id,
        "workspace_id": doc.workspace_id,
        "parent_id": doc.parent_id,
        "title": doc.title,
        "slug": doc.slug,
        "content_type": doc.content_type,
        "asset_mime": doc.asset_mime or "",
        "author": doc.author,
        "summary": doc.summary,
        "toc_json": doc.toc_json or [],
        "status": doc.status,
        "is_folder": doc.is_folder,
        "sort_order": doc.sort_order,
        "export_template_ref": doc.export_template_ref,
        "content_size": doc.content_size,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
        "created_by_id": doc.created_by_id,
        "updated_by_id": doc.updated_by_id,
        "tag_ids": tag_ids,
        "version_count": version_total,
        "pinned": pinned,
        # 可见性提示：前端据此展示"仅自己可见 / 已发布"
        "visibility": _document_visibility(doc),
    }
