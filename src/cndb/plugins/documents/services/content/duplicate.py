"""文档副本：子树递归复制、原件字节复制与标题去重（ADR 0180 D1）."""

from __future__ import annotations

import logging
import shutil
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.core.errors import ConflictError
from cndb.plugins.documents.models import (
    Document,
    DocumentTag,
)

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User


from cndb.plugins.documents.services import content as _pkg

from . import access

# 固定全名而非 __name__：拆包后日志分类必须仍是 …services.content（ADR 0180 D7）
logger = logging.getLogger("cndb.plugins.documents.services.content")


DUPLICATE_SUFFIX = " 副本"


def _document_tag_ids(db: Session, document_id: int) -> list[int]:
    rows = db.execute(select(DocumentTag.tag_id).where(DocumentTag.document_id == document_id)).all()
    return [int(row[0]) for row in rows]


def _unique_duplicate_title(db: Session, workspace_id: int, base_title: str) -> str:
    """同工作区唯一副本标题：原名 副本 / 原名 副本 2 / 原名 副本 3 …"""
    existing = set(
        db.execute(
            select(Document.title).where(
                Document.workspace_id == workspace_id,
                Document.is_deleted == False,  # noqa: E712
            )
        )
        .scalars()
        .all()
    )
    candidate = f"{base_title}{DUPLICATE_SUFFIX}"
    seq = 2
    while candidate in existing:
        candidate = f"{base_title}{DUPLICATE_SUFFIX} {seq}"
        seq += 1
    return candidate[:500]


def _copy_asset_file(workspace_id: int, source: Document) -> tuple[str, str, int]:
    """复制原件字节到新 file_key（uuid + 原后缀），返回 (key, mime, size)."""
    from cndb.plugins.files.services import resolve_workspace_file

    source_path = resolve_workspace_file(workspace_id, source.asset_file_key or "")
    if not source_path.is_file():
        raise ConflictError("原件文件缺失，无法创建副本")
    new_key = f"{uuid.uuid4().hex}{source_path.suffix}"
    target_path = resolve_workspace_file(workspace_id, new_key)
    shutil.copy2(source_path, target_path)
    return new_key, source.asset_mime, int(source_path.stat().st_size)


def duplicate_document(
    db: Session,
    workspace_id: int,
    doc_id: int,
    user: User,
    *,
    parent_id: int | None = None,
) -> Document:
    """创建文档 / 文件夹子树的副本，返回新的根节点（需求 0172）.

    - 仅 owner/editor；源文档必须可见（由路由层 `get_visible_document_or_404` 保证）；
    - 根节点标题自动加「副本」并递增，子节点保留原标题；
    - 文件夹递归复制整棵子树；原件族复制文件字节并登记新 `FileOwner`；
    - 每个节点经 ``create_document`` 落库，因此只有 v1 版本。
    """
    access.require_editor(db, workspace_id, user)
    source = access.get_document_or_404(db, workspace_id, doc_id)
    target_parent = source.parent_id if parent_id is None else parent_id
    if target_parent is not None:
        parent = access.get_document_or_404(db, workspace_id, target_parent)
        if not parent.is_folder:
            raise ConflictError("父节点必须是文件夹")
    created = _duplicate_node(db, workspace_id, source, user, target_parent, is_root=True)
    # 副本标题以「副本」结尾，本身就是新的链接目标（需求 0182 C1）
    _pkg.invalidate_link_graph_cache(workspace_id)
    return created


def _duplicate_node(
    db: Session,
    workspace_id: int,
    source: Document,
    user: User,
    parent_id: int | None,
    *,
    is_root: bool,
) -> Document:
    title = _unique_duplicate_title(db, workspace_id, source.title) if is_root else source.title
    if source.is_folder:
        new_doc = _pkg.create_document(
            db,
            workspace_id,
            user,
            title=title,
            is_folder=True,
            parent_id=parent_id,
            status=source.status,
            sort_order=source.sort_order,
        )
        children = (
            db.execute(
                select(Document)
                .where(
                    Document.parent_id == source.id,
                    Document.is_deleted == False,  # noqa: E712
                )
                .order_by(Document.sort_order, Document.id)
            )
            .scalars()
            .all()
        )
        for child in children:
            _duplicate_node(db, workspace_id, child, user, new_doc.id, is_root=False)
        return new_doc

    tag_ids = _document_tag_ids(db, source.id)
    if source.asset_file_key:
        new_key, mime, size = _copy_asset_file(workspace_id, source)
        new_doc = _pkg.create_document(
            db,
            workspace_id,
            user,
            title=title,
            parent_id=parent_id,
            status=source.status,
            tag_ids=tag_ids,
            sort_order=source.sort_order,
            export_template_ref=source.export_template_ref,
            content_type=source.content_type,
            asset_file_key=new_key,
            asset_mime=mime,
            content_size=size,
        )
        from cndb.plugins.files.services import record_owner

        record_owner(
            db,
            file_key=new_key,
            workspace_id=workspace_id,
            document_id=new_doc.id,
            uploaded_by_id=user.id,
        )
        return new_doc

    content = _pkg.load_content(_pkg.latest_version(db, source.id), source)
    return _pkg.create_document(
        db,
        workspace_id,
        user,
        title=title,
        content=content,
        parent_id=parent_id,
        status=source.status,
        tag_ids=tag_ids,
        sort_order=source.sort_order,
        export_template_ref=source.export_template_ref,
        content_type=source.content_type,
    )
