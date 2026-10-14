"""文档修改申请服务：双轨制写入分派 + 申请生命周期 + 内容 DIFF 计算.

设计对齐数据表修改申请（change_requests 插件）：

- **直编条件**：owner 恒直编；editor 需工作区 ``allow_edit`` 开启；viewer 一律走修改申请；
- **申请只存待审正文**，不写入 ``document_versions``，合并通过后才生成新版本；
- **基准与漂移**：申请记录提交时的 ``base_version_number``，文档版本前进后其余 open
  申请置 ``stale``（见 :func:`mark_open_requests_stale`，由 content.update_content 触发），
  过期申请必须先刷新基准才能合并；
- **草稿删除**：仅待审核（open）申请可由提交人本人或工作区所有者物理删除。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import (
    DCR_STATUS_CLOSED,
    DCR_STATUS_MERGED,
    DCR_STATUS_OPEN,
    Document,
    DocumentChangeRequest,
    DocumentVersion,
)
from cndb.plugins.documents.services import content as content_service
from cndb.plugins.documents.services import parse as parse_service
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role

# 写模式三态：与数据表双轨分派（change_requests.services.resolve_write_mode）语义一致
WRITE_MODE_DIRECT = "direct"
WRITE_MODE_CHANGE_REQUEST = "change_request"
WRITE_MODE_DENIED = "denied"

# 列表 scope：open（待审核）/ merged / closed / mine（我提交的，含全部状态）/ all
SCOPES = ("open", "merged", "closed", "mine", "all")


# ── 权限与写模式 ──────────────────────────────────────


def _get_workspace(db: Session, workspace_id: int) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("工作区不存在")
    return ws


def _require_member(db: Session, workspace_id: int, user: User) -> WorkspaceRole:
    """校验用户是工作区成员（任何成员都可提交/查看修改申请）."""
    role = get_member_role(user, _get_workspace(db, workspace_id), db)
    if role is None:
        raise PermissionDeniedError("非工作区成员")
    return role


def _require_reviewer(db: Session, workspace_id: int, user: User) -> WorkspaceRole:
    """校验用户可审核（owner/editor）."""
    role = _require_member(db, workspace_id, user)
    if role not in (WorkspaceRole.OWNER, WorkspaceRole.EDITOR):
        raise PermissionDeniedError("仅编辑者及以上角色可审核修改申请")
    return role


def require_member(db: Session, workspace_id: int, user: User) -> WorkspaceRole:
    """公开的工作区成员校验（路由层复用）."""
    return _require_member(db, workspace_id, user)


def resolve_write_mode(db: Session, workspace_id: int, user: User) -> str:
    """判定当前用户对工作区文档的写模式（供保存路径双轨分派）.

    Returns:
        ``direct``：直接保存落库；``change_request``：保存转为修改申请；
        ``denied``：非工作区成员（写操作 403）。
    """
    ws = _get_workspace(db, workspace_id)
    role = get_member_role(user, ws, db)
    if role is None:
        return WRITE_MODE_DENIED
    if role == WorkspaceRole.OWNER:
        return WRITE_MODE_DIRECT
    if role == WorkspaceRole.EDITOR and bool(ws.allow_edit):
        return WRITE_MODE_DIRECT
    return WRITE_MODE_CHANGE_REQUEST


# ── 查询 ──────────────────────────────────────────────


def get_request_or_404(db: Session, workspace_id: int, request_id: int) -> DocumentChangeRequest:
    cr = db.get(DocumentChangeRequest, request_id)
    if cr is None or cr.workspace_id != workspace_id:
        raise NotFoundError("修改申请不存在")
    return cr


def _current_version_number(db: Session, document_id: int) -> int:
    version = content_service.latest_version(db, document_id)
    return version.version_number if version else 0


def _load_base_content(db: Session, cr: DocumentChangeRequest, doc: Document) -> str:
    """读取申请基准版本的正文（0 表示空文档）."""
    if cr.base_version_number <= 0:
        return ""
    version = db.execute(
        select(DocumentVersion).where(
            DocumentVersion.document_id == doc.id,
            DocumentVersion.version_number == cr.base_version_number,
        )
    ).scalar_one_or_none()
    return content_service.load_content(version, doc) if version is not None else ""


def diff_payload(db: Session, cr: DocumentChangeRequest, doc: Document) -> dict[str, Any]:
    """计算「基准正文 → 待审正文」的 unified diff 载荷."""
    base = _load_base_content(db, cr, doc)
    diff_text, added, removed = parse_service.unified_diff(base, cr.proposed_content)
    return {
        "diff": diff_text,
        "added": added,
        "removed": removed,
        "base_size": len(base.encode("utf-8")),
        "proposed_size": cr.proposed_size,
        "base_version_number": cr.base_version_number,
    }


def serialize_request(
    db: Session,
    cr: DocumentChangeRequest,
    *,
    with_diff: bool = False,
    with_content: bool = False,
) -> dict[str, Any]:
    """序列化申请；``with_diff`` 附带内容 DIFF，``with_content`` 附带待审正文全文."""
    data: dict[str, Any] = {
        "id": cr.id,
        "workspace_id": cr.workspace_id,
        "document_id": cr.document_id,
        "title": cr.title,
        "description": cr.description,
        "change_summary": cr.change_summary,
        "status": cr.status,
        "stale": cr.stale,
        "base_version_number": cr.base_version_number,
        "current_version_number": _current_version_number(db, cr.document_id),
        "proposed_size": cr.proposed_size,
        "submitted_by_id": cr.submitted_by_id,
        "reviewed_by_id": cr.reviewed_by_id,
        "reviewed_at": cr.reviewed_at.isoformat() if cr.reviewed_at else None,
        "review_comment": cr.review_comment,
        "created_at": cr.created_at.isoformat() if cr.created_at else None,
        "updated_at": cr.updated_at.isoformat() if cr.updated_at else None,
    }
    doc = db.get(Document, cr.document_id)
    if doc is not None:
        data["document_title"] = doc.title
        data["document_deleted"] = bool(doc.is_deleted)
        if with_diff:
            data["diff"] = diff_payload(db, cr, doc)
    if with_content:
        data["proposed_content"] = cr.proposed_content
    return data


def list_requests(
    db: Session,
    workspace_id: int,
    user: User,
    *,
    document_id: int | None = None,
    scope: str = "open",
) -> list[DocumentChangeRequest]:
    """按工作区 / 文档列出修改申请；``scope`` 取 open/merged/closed/mine/all."""
    _require_member(db, workspace_id, user)
    if scope not in SCOPES:
        raise BadRequestError(f"不支持的 scope: {scope}，可选 {'/'.join(SCOPES)}")

    stmt = select(DocumentChangeRequest).where(DocumentChangeRequest.workspace_id == workspace_id)
    if document_id is not None:
        stmt = stmt.where(DocumentChangeRequest.document_id == document_id)
    if scope == "mine":
        stmt = stmt.where(DocumentChangeRequest.submitted_by_id == user.id)
    elif scope in (DCR_STATUS_OPEN, DCR_STATUS_MERGED, DCR_STATUS_CLOSED):
        stmt = stmt.where(DocumentChangeRequest.status == scope)
    # scope == all 时不过滤状态
    stmt = stmt.order_by(DocumentChangeRequest.id.desc())
    return list(db.scalars(stmt).all())


# ── 生命周期 ──────────────────────────────────────────


def create_request(
    db: Session,
    workspace_id: int,
    doc_id: int,
    user: User,
    *,
    content: str,
    title: str = "",
    description: str = "",
    change_summary: str = "",
    base_version_number: int | None = None,
) -> DocumentChangeRequest:
    """创建修改申请（不落库为文档版本）.

    Args:
        content: 待审正文全文。
        base_version_number: 提交者编辑所基于的版本号；缺省取服务端当前最新版本。
    """
    _require_member(db, workspace_id, user)
    doc = content_service.get_document_or_404(db, workspace_id, doc_id)
    if doc.is_folder:
        raise ConflictError("文件夹没有内容")

    current = _current_version_number(db, doc.id)
    base = current if base_version_number is None else base_version_number
    if base > current:
        raise BadRequestError(f"基准版本不存在：v{base}（当前最新 v{current}）")

    cr = DocumentChangeRequest(
        document_id=doc.id,
        workspace_id=workspace_id,
        title=(title or f"修改文档《{doc.title}》")[:255],
        description=description[:2000],
        proposed_content=content,
        proposed_size=len(content.encode("utf-8")),
        change_summary=change_summary[:500],
        base_version_number=base,
        status=DCR_STATUS_OPEN,
        stale=base != current,
        submitted_by_id=user.id,
    )
    db.add(cr)
    db.commit()
    db.refresh(cr)
    return cr


def merge_request(
    db: Session,
    workspace_id: int,
    request_id: int,
    user: User,
    *,
    review_comment: str = "",
) -> tuple[DocumentChangeRequest, int]:
    """通过申请：把待审正文落库为新版本，返回 (申请, 新版本号).

    Raises:
        ConflictError: 申请非 open；文档已删除；基准已过期（需先刷新基准）。
    """
    _require_reviewer(db, workspace_id, user)
    cr = get_request_or_404(db, workspace_id, request_id)
    if cr.status != DCR_STATUS_OPEN:
        raise ConflictError("仅待审核的修改申请可通过")

    doc = content_service.get_document_any_state_or_404(db, workspace_id, cr.document_id)
    if doc.is_deleted:
        raise ConflictError("文档已在回收站中，请先恢复文档再处理申请")
    if doc.is_folder:
        raise ConflictError("文件夹没有内容")

    current = _current_version_number(db, doc.id)
    if current != cr.base_version_number:
        # 基准漂移：拒绝直接覆盖更新版本，需提交人刷新基准或重新提交
        cr.stale = True
        db.commit()
        raise ConflictError(
            f"文档已在提交后被修改（基准 v{cr.base_version_number}，当前 v{current}），请先刷新基准或重新提交",
            code="document_change_request_stale",
        )

    content_service.update_content(
        db,
        workspace_id,
        doc.id,
        user,
        content=cr.proposed_content,
        change_summary=cr.change_summary or f"合并修改申请 #{cr.id}",
        base_updated_at=None,
    )
    new_version = content_service.latest_version(db, doc.id)

    cr.status = DCR_STATUS_MERGED
    cr.stale = False
    cr.reviewed_by_id = user.id
    cr.reviewed_at = dt.datetime.now(dt.UTC)
    cr.review_comment = review_comment[:2000]
    db.commit()
    db.refresh(cr)
    return cr, (new_version.version_number if new_version else 0)


def close_request(
    db: Session,
    workspace_id: int,
    request_id: int,
    user: User,
    *,
    review_comment: str = "",
) -> DocumentChangeRequest:
    """驳回 / 关闭申请（owner/editor 或提交人本人）."""
    role = _require_member(db, workspace_id, user)
    cr = get_request_or_404(db, workspace_id, request_id)
    if cr.status != DCR_STATUS_OPEN:
        raise ConflictError("仅待审核的修改申请可关闭")
    is_submitter = cr.submitted_by_id is not None and cr.submitted_by_id == user.id
    if role not in (WorkspaceRole.OWNER, WorkspaceRole.EDITOR) and not is_submitter:
        raise PermissionDeniedError("仅审核者或提交人可关闭该申请")

    cr.status = DCR_STATUS_CLOSED
    cr.reviewed_by_id = user.id
    cr.reviewed_at = dt.datetime.now(dt.UTC)
    cr.review_comment = review_comment[:2000]
    db.commit()
    db.refresh(cr)
    return cr


def delete_request(db: Session, workspace_id: int, request_id: int, user: User) -> None:
    """删除草稿（物理删除未生效的待审申请）.

    仅提交人本人或工作区所有者可删除；已合并 / 已关闭的申请保留作为处理留痕。
    """
    role = _require_member(db, workspace_id, user)
    cr = get_request_or_404(db, workspace_id, request_id)
    is_submitter = cr.submitted_by_id is not None and cr.submitted_by_id == user.id
    if not is_submitter and role != WorkspaceRole.OWNER:
        raise PermissionDeniedError("仅提交人本人或工作区所有者可删除该草稿")
    if cr.status != DCR_STATUS_OPEN:
        raise ConflictError("仅待审核的修改申请可作为草稿删除")
    db.delete(cr)
    db.commit()


def update_base(
    db: Session,
    workspace_id: int,
    request_id: int,
    user: User,
    *,
    base_version_number: int | None = None,
) -> DocumentChangeRequest:
    """刷新基准：以指定版本（缺省当前最新）为新基准，清除 stale（仅提交人本人）."""
    _require_member(db, workspace_id, user)
    cr = get_request_or_404(db, workspace_id, request_id)
    if cr.status != DCR_STATUS_OPEN:
        raise ConflictError("仅待审核的修改申请可刷新基准")
    if cr.submitted_by_id is None or cr.submitted_by_id != user.id:
        raise PermissionDeniedError("仅提交人本人可刷新基准")

    current = _current_version_number(db, cr.document_id)
    target = current if base_version_number is None else base_version_number
    if target > current:
        raise BadRequestError(f"基准版本不存在：v{target}（当前最新 v{current}）")

    cr.base_version_number = target
    cr.stale = target != current
    db.commit()
    db.refresh(cr)
    return cr


def mark_open_requests_stale(db: Session, document_id: int, *, keep_request_id: int | None = None) -> int:
    """把指定文档的其它 open 申请标记为基准过期，返回本次置位的条数.

    由 ``content.update_content`` 在新版本落地后调用：同文档多个待审申请并存时，
    先合并者生效，其余申请基准即失效。
    """
    rows = list(
        db.scalars(
            select(DocumentChangeRequest).where(
                DocumentChangeRequest.document_id == document_id,
                DocumentChangeRequest.status == DCR_STATUS_OPEN,
            )
        ).all()
    )
    changed = 0
    for cr in rows:
        if keep_request_id is not None and cr.id == keep_request_id:
            continue
        if not cr.stale:
            cr.stale = True
            changed += 1
    if changed:
        db.commit()
    return changed


__all__ = [
    "SCOPES",
    "WRITE_MODE_CHANGE_REQUEST",
    "WRITE_MODE_DENIED",
    "WRITE_MODE_DIRECT",
    "close_request",
    "create_request",
    "delete_request",
    "diff_payload",
    "get_request_or_404",
    "list_requests",
    "mark_open_requests_stale",
    "merge_request",
    "require_member",
    "resolve_write_mode",
    "serialize_request",
    "update_base",
]
