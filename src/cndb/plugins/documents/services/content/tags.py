"""标签关联与标签计数维护（ADR 0180 D1）."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.core.errors import NotFoundError
from cndb.plugins.documents.models import (
    Document,
    DocumentTag,
    Tag,
)

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User


logger = logging.getLogger("cndb.plugins.documents.services.content")


def _apply_tags(db: Session, doc: Document, tag_ids: list[int], user: User) -> None:

    valid_tags = (
        db.execute(select(Tag).where(Tag.workspace_id == doc.workspace_id, Tag.id.in_(tag_ids))).scalars().all()
    )
    valid_ids = {t.id for t in valid_tags}
    invalid = set(tag_ids) - valid_ids
    if invalid:
        raise NotFoundError(f"标签不存在: {sorted(invalid)}")

    existing = {
        row.tag_id for row in db.execute(select(DocumentTag.tag_id).where(DocumentTag.document_id == doc.id)).all()
    }
    for tid in valid_ids:
        if tid not in existing:
            db.add(DocumentTag(document_id=doc.id, tag_id=tid, tagged_by_id=user.id))
    for tid in existing - valid_ids:
        row = db.get(DocumentTag, {"document_id": doc.id, "tag_id": tid})
        if row:
            db.delete(row)
    _refresh_tag_counts(db, doc.workspace_id)


def _refresh_tag_counts(db: Session, workspace_id: int) -> None:

    db.flush()  # autoflush=False 场景下确保待插入的关联行对计数查询可见
    rows = db.execute(
        select(DocumentTag.tag_id, func.count())
        .join(Document, Document.id == DocumentTag.document_id)
        .where(Document.workspace_id == workspace_id, Document.is_deleted == False)  # noqa: E712
        .group_by(DocumentTag.tag_id)
    ).all()
    counts = {row[0]: row[1] for row in rows}
    tags = db.execute(select(Tag).where(Tag.workspace_id == workspace_id)).scalars().all()
    for t in tags:
        t.doc_count = counts.get(t.id, 0)
