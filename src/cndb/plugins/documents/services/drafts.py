"""文档个人草稿服务：保存与提交解耦.

产品语义（替代此前的「保存即提交」）：

- **保存草稿**：只写 ``documents_draft``，不创建版本、不生成修改申请，
  正式内容完全不受影响；
- **提交修改**：显式动作，有直编资格时落库为新版本，否则生成修改申请；
- **未修改不可提交**：正文与当前最新版本一致时返回 409（code=``no_changes``），
  前端据此禁用提交按钮；
- **基准合并**：草稿记录开始编辑时的 ``base_version_number``，提交时若文档已
  前进版本，先做段落级三方合并（不同段落可合并、同段落冲突）。

草稿是**个人**数据：每位用户一份，只有本人能读写；管理员也看不到他人草稿。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError, ConflictError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import Document, DocumentDraft, DocumentVersion
from cndb.plugins.documents.services import change_requests as change_request_service
from cndb.plugins.documents.services import content as content_service
from cndb.plugins.documents.services import paragraph_lock
from cndb.plugins.documents.services import parse as parse_service
from cndb.plugins.documents.services import visibility as visibility_service

# ── 读取 ──────────────────────────────────────────────


def get_draft(db: Session, document_id: int, user_id: int) -> DocumentDraft | None:
    """取个人草稿（不存在返回 None）."""
    return db.execute(
        select(DocumentDraft).where(
            DocumentDraft.document_id == document_id,
            DocumentDraft.user_id == user_id,
        )
    ).scalar_one_or_none()


def _latest_content(db: Session, doc: Document) -> tuple[str, int]:
    """当前最新版本正文与版本号（无版本时为空串 / 0）."""
    version = content_service.latest_version(db, doc.id)
    return content_service.load_content(version, doc), (version.version_number if version else 0)


def _version_content(db: Session, doc: Document, version_number: int) -> str:
    """指定版本正文；版本不存在时返回空串."""
    if version_number <= 0:
        return ""
    version = db.execute(
        select(DocumentVersion).where(
            DocumentVersion.document_id == doc.id,
            DocumentVersion.version_number == version_number,
        )
    ).scalar_one_or_none()
    return content_service.load_content(version, doc) if version is not None else ""


def draft_payload(db: Session, doc: Document, user: User) -> dict[str, Any] | None:
    """当前用户在该文档上的草稿载荷；草稿与最新版本内容一致时视为不存在."""
    draft = get_draft(db, doc.id, user.id)
    if draft is None:
        return None
    latest_text, latest_num = _latest_content(db, doc)
    if draft.content_hash == parse_service.content_hash(latest_text):
        return None
    return {
        "content": draft.content,
        "content_size": draft.content_size,
        "base_version_number": draft.base_version_number,
        "current_version_number": latest_num,
        "stale": draft.base_version_number < latest_num,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }


# ── 写入 ──────────────────────────────────────────────


def _delete_draft_row(db: Session, document_id: int, user_id: int) -> None:
    db.execute(
        delete(DocumentDraft).where(
            DocumentDraft.document_id == document_id,
            DocumentDraft.user_id == user_id,
        )
    )


def save_draft(
    db: Session,
    workspace_id: int,
    doc_id: int,
    user: User,
    *,
    content: str,
    base_version_number: int | None = None,
) -> DocumentDraft | None:
    """保存个人草稿（不生成版本）.

    - 内容与当前最新版本一致：删除已有草稿（等价于「没有修改」），返回 None；
    - ``base_version_number`` 缺省取当前最新版本；超过当前最新版本视为非法。
    """
    change_request_service.require_member(db, workspace_id, user)
    doc = visibility_service.get_visible_document_or_404(db, workspace_id, doc_id, user)
    if doc.is_folder:
        raise ConflictError("文件夹没有内容")

    latest_text, latest_num = _latest_content(db, doc)
    base = latest_num if base_version_number is None else base_version_number
    if base > latest_num:
        raise BadRequestError(f"基准版本不存在：v{base}（当前最新 v{latest_num}）")

    content_hash = parse_service.content_hash(content)
    if content_hash == parse_service.content_hash(latest_text):
        _delete_draft_row(db, doc.id, user.id)
        db.commit()
        return None

    draft = get_draft(db, doc.id, user.id)
    if draft is None:
        draft = DocumentDraft(document_id=doc.id, user_id=user.id)
        db.add(draft)
    draft.content = content
    draft.content_size = len(content.encode("utf-8"))
    draft.content_hash = content_hash
    draft.base_version_number = base
    db.commit()
    db.refresh(draft)
    return draft


def delete_draft(db: Session, workspace_id: int, doc_id: int, user: User) -> None:
    """丢弃个人草稿（幂等）."""
    change_request_service.require_member(db, workspace_id, user)
    doc = visibility_service.get_visible_document_or_404(db, workspace_id, doc_id, user)
    _delete_draft_row(db, doc.id, user.id)
    db.commit()


def serialize_draft(draft: DocumentDraft | None) -> dict[str, Any] | None:
    """草稿的接口载荷（不含正文的元数据场景用）；完整读取走 draft_payload."""
    if draft is None:
        return None
    return {
        "content": draft.content,
        "content_size": draft.content_size,
        "base_version_number": draft.base_version_number,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }


# ── 显式提交 ──────────────────────────────────────────


def _merge_conflict_error(doc_id: int, user: User, outcome: Any) -> ConflictError:
    """把段落级三方合并冲突转换为带持锁人信息的 409."""
    holders = paragraph_lock.paragraph_lock_registry.conflicts_for_indices(
        doc_id, outcome.conflicts, getattr(user, "id", 0)
    )
    detail = "、".join(
        f"第 {paragraph_lock.key_to_index(lock.key)} 段（{lock.username} 正在编辑）" for lock in holders
    ) or "、".join(f"第 {i} 段" for i in sorted(outcome.conflicts))
    return ConflictError(
        f"以下段落已被他人修改，请复制你的改动后刷新：{detail}",
        code="paragraph_conflict",
        context={"conflict_keys": outcome.conflict_keys},
    )


def submit_draft(
    db: Session,
    workspace_id: int,
    doc_id: int,
    user: User,
    *,
    content: str | None = None,
    change_summary: str = "",
    base_version_number: int | None = None,
) -> dict[str, Any]:
    """显式提交修改：直编落库为新版本，否则生成修改申请.

    Args:
        content: 待提交正文；缺省取服务端已保存的个人草稿。
        base_version_number: 编辑基准版本；缺省取草稿记录，再缺省取当前最新版本。

    Raises:
        ConflictError: 没有可提交内容 / 内容未变化 / 段落冲突。
    """
    change_request_service.require_member(db, workspace_id, user)
    doc = visibility_service.get_visible_document_or_404(db, workspace_id, doc_id, user)
    if doc.is_folder:
        raise ConflictError("文件夹没有内容")

    draft = get_draft(db, doc.id, user.id)
    incoming = content if content is not None else (draft.content if draft is not None else None)
    if incoming is None:
        raise ConflictError("没有可提交的修改", code="no_changes")

    latest_text, latest_num = _latest_content(db, doc)
    if parse_service.content_hash(incoming) == parse_service.content_hash(latest_text):
        _delete_draft_row(db, doc.id, user.id)
        db.commit()
        raise ConflictError("内容未发生变化，无需提交", code="no_changes")

    base = base_version_number
    if base is None and draft is not None:
        base = draft.base_version_number
    if base is None:
        base = latest_num
    if base > latest_num:
        raise BadRequestError(f"基准版本不存在：v{base}（当前最新 v{latest_num}）")

    mode = change_request_service.resolve_document_write_mode(db, workspace_id, doc.id, user)

    # ── 无直编资格：生成修改申请（正文不落库） ──
    if mode == change_request_service.WRITE_MODE_CHANGE_REQUEST:
        cr = change_request_service.create_request(
            db,
            workspace_id,
            doc.id,
            user,
            content=incoming,
            change_summary=change_summary,
            base_version_number=base,
        )
        _delete_draft_row(db, doc.id, user.id)
        db.commit()
        return {
            "mode": "change_request",
            "change_request": change_request_service.serialize_request(db, cr, with_diff=True),
            "message": f"已提交修改申请 #{cr.id}，审核通过后生效",
        }

    # ── 直编：必要时先做段落级三方合并，再落库为新版本 ──
    if base < latest_num:
        outcome = paragraph_lock.merge_incoming(_version_content(db, doc, base), latest_text, incoming)
        if not outcome.merged:
            raise _merge_conflict_error(doc.id, user, outcome)
        incoming = outcome.text
        if parse_service.content_hash(incoming) == parse_service.content_hash(latest_text):
            _delete_draft_row(db, doc.id, user.id)
            db.commit()
            raise ConflictError("内容未发生变化，无需提交", code="no_changes")

    from cndb.plugins.documents.services import document_permissions

    granted = document_permissions.is_editor_granted(db, doc.id, user.id)
    updated = content_service.update_content(
        db,
        workspace_id,
        doc.id,
        user,
        content=incoming,
        change_summary=change_summary or "提交修改",
        base_updated_at=None,
        enforce_role=not granted,
    )
    _delete_draft_row(db, doc.id, user.id)
    db.commit()

    version = content_service.latest_version(db, doc.id)
    data = content_service.serialize_document(db, updated)
    data["content"] = incoming
    data["version_number"] = version.version_number if version else 0
    return {
        "mode": "direct",
        "document": data,
        "content": incoming,
        "version_number": data["version_number"],
        "message": f"已提交修改，生成 v{data['version_number']}",
    }


__all__ = [
    "delete_draft",
    "draft_payload",
    "get_draft",
    "save_draft",
    "serialize_draft",
    "submit_draft",
]
