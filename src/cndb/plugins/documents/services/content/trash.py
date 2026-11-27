"""文档删除与回收站：软删除 / 恢复 / 彻底删除（ADR 0180 D1）."""

from __future__ import annotations

import datetime as dt
import logging
import shutil
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from cndb.core.errors import ConflictError, NotFoundError
from cndb.plugins.documents.models import (
    Document,
    DocumentChangeRequest,
    DocumentIssue,
    DocumentIssueComment,
    DocumentIssueEvent,
    DocumentPin,
    DocumentShare,
    DocumentTag,
    DocumentVersion,
)

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User

from cndb.plugins.documents.services import content as _pkg

from . import access, storage

# 固定全名而非 __name__：拆包后日志分类必须仍是 …services.content（ADR 0180 D7）
logger = logging.getLogger("cndb.plugins.documents.services.content")


def soft_delete_documents(db: Session, workspace_id: int, docs: list[Document], user: User) -> int:
    """批量软删除（同一删除时间戳，最后统一刷新标签计数）；返回处理的根节点数."""
    access.require_editor(db, workspace_id, user)
    deleted_at = dt.datetime.now(dt.UTC)
    count = 0
    for doc in docs:
        if doc.is_deleted:
            continue
        _mark_deleted_subtree(db, doc, user, deleted_at)
        count += 1
    if count:
        _pkg._refresh_tag_counts(db, workspace_id)
    db.commit()
    if count:
        _pkg.invalidate_link_graph_cache(workspace_id)
    return count


def soft_delete_document(db: Session, workspace_id: int, doc_id: int, user: User) -> Document:
    """软删除文档（文件夹级联整棵子树，同一删除批次；刷新标签计数）."""
    doc = access.get_document_or_404(db, workspace_id, doc_id)
    access.require_editor(db, workspace_id, user)

    deleted_at = dt.datetime.now(dt.UTC)
    _mark_deleted_subtree(db, doc, user, deleted_at)
    _pkg._refresh_tag_counts(db, workspace_id)
    db.commit()
    db.refresh(doc)
    _pkg.invalidate_link_graph_cache(workspace_id)
    return doc


def _mark_deleted_subtree(
    db: Session,
    node: Document,
    user: User,
    deleted_at: dt.datetime,
    visited: set[int] | None = None,
) -> int:
    """把 node 及其未删除子孙标记为已删除（同一 deleted_at），返回标记节点数.

    - ``visited`` 防御历史脏数据已有环时的无限递归；
    - 已删除节点整体跳过：不覆盖其 deleted_at，恢复时才能区分删除批次。
    """
    visited = set() if visited is None else visited
    if node.id in visited:
        return 0
    visited.add(node.id)
    if node.is_deleted:
        return 0

    node.is_deleted = True
    node.deleted_at = deleted_at
    node.deleted_by_id = user.id
    node.updated_by_id = user.id
    if not node.is_folder:
        _pkg._sync_fts_delete(db, node.id)

    children = (
        db.execute(
            select(Document).where(
                Document.parent_id == node.id,
                Document.is_deleted == False,  # noqa: E712
            )
        )
        .scalars()
        .all()
    )
    marked = 1
    for child in children:
        marked += _mark_deleted_subtree(db, child, user, deleted_at, visited)
    return marked


def list_deleted_documents(
    db: Session,
    workspace_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
    viewer: Any = None,
    is_admin: bool = False,
) -> tuple[list[Document], int]:
    """回收站列表（按删除时间倒序；迁移前删除的 deleted_at 为空排最后）."""
    filters = [
        Document.workspace_id == workspace_id,
        Document.is_deleted == True,  # noqa: E712
    ]
    # 可见性：他人草稿/未发布内容的删除记录同样不外泄
    if viewer is not None and not is_admin:
        from cndb.plugins.documents.services.visibility import visible_condition

        filters.append(visible_condition(db, workspace_id, viewer, is_admin=False))
    total = int(db.execute(select(func.count()).select_from(Document).where(*filters)).scalar_one())
    docs = (
        db.execute(
            select(Document)
            .where(*filters)
            .order_by(Document.deleted_at.desc(), Document.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return list(docs), total


def restore_document(db: Session, workspace_id: int, doc_id: int, user: User) -> tuple[Document, int, bool]:
    """从回收站恢复文档，返回 ``(文档, 恢复节点数, 是否重挂根目录)``.

    - 文件夹：连同 **同一删除批次**（deleted_at 相同）的级联子项一起恢复，
      独立删除的子项保留在回收站；
    - 迁移前历史数据 deleted_at 为空：按整棵子树宽松恢复；
    - 父节点仍处于删除态时重挂到根目录，避免产生"可见但父级不可见"的悬空层级。
    """
    doc = access.get_deleted_document_or_404(db, workspace_id, doc_id)
    access.require_editor(db, workspace_id, user)

    restored = _restore_subtree(db, doc, batch=doc.deleted_at)
    reparented = False
    if doc.parent_id is not None:
        parent = db.get(Document, doc.parent_id)
        if parent is None or parent.is_deleted:
            doc.parent_id = None
            reparented = True
    doc.updated_by_id = user.id
    _pkg._refresh_tag_counts(db, workspace_id)
    db.commit()
    db.refresh(doc)
    _pkg.invalidate_link_graph_cache(workspace_id)
    return doc, restored, reparented


def _restore_subtree(db: Session, node: Document, batch: dt.datetime | None, visited: set[int] | None = None) -> int:
    """恢复 node 及同批次子孙，重建 FTS 索引，返回恢复节点数."""
    visited = set() if visited is None else visited
    if node.id in visited:
        return 0
    visited.add(node.id)

    node.is_deleted = False
    node.deleted_at = None
    node.deleted_by_id = None
    if not node.is_folder:
        _pkg.sync_fts(db, node, _pkg.load_content(_pkg.latest_version(db, node.id), node))

    children = (
        db.execute(
            select(Document).where(
                Document.parent_id == node.id,
                Document.is_deleted == True,  # noqa: E712
            )
        )
        .scalars()
        .all()
    )
    restored = 1
    for child in children:
        if batch is not None and not _same_delete_batch(child.deleted_at, batch):
            continue  # 独立删除批次，保留在回收站
        restored += _restore_subtree(db, child, batch, visited)
    return restored


def _same_delete_batch(a: dt.datetime | None, b: dt.datetime | None) -> bool:
    """判断两次删除是否为同一批次（同一请求写入的 deleted_at 完全相同）.

    不做时间容差：容差会把"先被单独删除"的子项误并入父级删除批次，恢复父目录时
    连带复活不该复活的节点。
    """
    if a is None or b is None:
        return a is None and b is None
    return a.replace(tzinfo=None) == b.replace(tzinfo=None)


def purge_document(db: Session, workspace_id: int, doc_id: int, user: User) -> dict[str, int]:
    """彻底删除回收站文档（不可恢复），返回清理统计.

    - 两段式：仅允许彻底删除 **已进入回收站** 的文档，未删除的文档返回 409；
    - 文件夹连同仍处于删除态的子孙一并销毁；已恢复的子项脱离父节点挂到根目录，
      不随父节点一起销毁；
    - 一并清理版本 / 标签关联 / 分享 / FTS 索引与外存内容目录。
    """
    doc = access.get_document_any_state_or_404(db, workspace_id, doc_id)
    # 先判可见性再判角色：彻底删除不可逆，「看不见的草稿」不允许被销毁。
    # 已发布文档在回收站中仍按文档策略对全员可见，故不受影响。
    from cndb.plugins.documents.services import visibility

    if not visibility.can_view_document(db, doc, user):
        raise NotFoundError("文档不存在")
    access.require_editor(db, workspace_id, user)
    if not doc.is_deleted:
        raise ConflictError("文档尚未删除，请先移入回收站再彻底删除", code="doc_not_deleted")

    targets: list[Document] = []
    detached = _collect_purge_targets(db, doc, targets, visited=set())
    ids = [t.id for t in targets]

    db.execute(delete(DocumentVersion).where(DocumentVersion.document_id.in_(ids)))
    db.execute(delete(DocumentTag).where(DocumentTag.document_id.in_(ids)))
    db.execute(delete(DocumentShare).where(DocumentShare.document_id.in_(ids)))
    # 待审修改申请随文档一并销毁，避免留下指向已清空文档的孤儿申请
    db.execute(delete(DocumentChangeRequest).where(DocumentChangeRequest.document_id.in_(ids)))
    # 个人置顶随文档销毁，避免留下指向已清空文档的孤儿行
    db.execute(delete(DocumentPin).where(DocumentPin.document_id.in_(ids)))
    # 文档问题清单及其评论 / 事件流水同样随文档销毁（不依赖 SQLite 外键级联是否开启）
    issue_ids = select(DocumentIssue.id).where(DocumentIssue.document_id.in_(ids))
    db.execute(delete(DocumentIssueComment).where(DocumentIssueComment.issue_id.in_(issue_ids)))
    db.execute(delete(DocumentIssueEvent).where(DocumentIssueEvent.issue_id.in_(issue_ids)))
    db.execute(delete(DocumentIssue).where(DocumentIssue.document_id.in_(ids)))
    for target in targets:
        _pkg._sync_fts_delete(db, target.id)
    db.execute(delete(Document).where(Document.id.in_(ids)))
    _pkg._refresh_tag_counts(db, workspace_id)
    # 原件族（ADR 0025）：原件文件与归属记录随文档一并清理，避免残留占用配额
    from cndb.plugins.files.models import FileOwner

    asset_keys = [t.asset_file_key for t in targets if t.asset_file_key]
    db.execute(delete(FileOwner).where(FileOwner.document_id.in_(ids)))
    db.commit()

    # 外存文件在事务提交后删除：DB 侧已作废，避免"文件已删但事务回滚"
    files_removed = 0
    for doc_id_ in ids:
        external = storage._external_dir(doc_id_)
        if external.is_dir():
            shutil.rmtree(external, ignore_errors=True)
            files_removed += 1
    files_removed += _remove_asset_files(workspace_id, asset_keys)
    _pkg.invalidate_link_graph_cache(workspace_id)
    return {"purged_count": len(ids), "files_removed": files_removed, "detached": detached}


def _remove_asset_files(workspace_id: int, keys: list[str]) -> int:
    """删原件落盘文件（路径非法 / 已不存在时静默跳过），返回删除数."""
    from cndb.plugins.documents.services.preview import pptx_pdf
    from cndb.plugins.files.services import remove_workspace_file

    removed = 0
    for key in keys:
        if remove_workspace_file(workspace_id, key):
            removed += 1
        # 原件彻底删除后衍生 PDF 一并失效（ADR 0129 I4），残留由补扫按 TTL 兜底
        pptx_pdf.invalidate_pptx_pdf(workspace_id, key)
    return removed


def _collect_purge_targets(db: Session, node: Document, targets: list[Document], visited: set[int]) -> int:
    """收集待彻底删除的子树节点（环保护），返回从子树中脱钩的存活子项数."""
    if node.id in visited:
        return 0
    visited.add(node.id)
    targets.append(node)
    detached = 0
    children = db.execute(select(Document).where(Document.parent_id == node.id)).scalars().all()
    for child in children:
        if child.is_deleted:
            detached += _collect_purge_targets(db, child, targets, visited)
        else:
            child.parent_id = None  # 已恢复的子项挂根，不销毁
            detached += 1
    return detached
