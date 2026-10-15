"""documents 插件：分享链接管理（需登录，editor+）.

端点：
- POST  /{workspace_id}/documents/{doc_id}/share          创建分享
- GET   /{workspace_id}/documents/{doc_id}/share          分享列表
- DELETE /{workspace_id}/documents/{doc_id}/share/{share_id}  撤销分享
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any

import bcrypt
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import ConflictError, NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents import services
from cndb.plugins.documents.models import DOC_STATUS_PUBLISHED, DocumentShare
from cndb.plugins.documents.schemas import ShareCreate

share_router = APIRouter(prefix="/{workspace_id}/documents", tags=["documents"])


@share_router.post("/{doc_id}/share", status_code=201)
def create_share(
    workspace_id: int,
    doc_id: int,
    payload: ShareCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """创建分享链接（editor+）。

    仅**已发布**文档可分享：草稿/未发布内容一旦生成公开链接，等于把未发布版本放给外部，
    且后续取消发布也不会收回（线上线下都遇到过）。取消/下线后既有链接随即失效（见 public 路由）。
    """
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    services.content.require_editor(db, workspace_id, current_user)
    if doc.status != DOC_STATUS_PUBLISHED:
        raise ConflictError("仅已发布文档可创建分享链接；请先发布该文档")

    password_hash = None
    if payload.password:
        password_hash = bcrypt.hashpw(payload.password.encode("utf-8"), bcrypt.gensalt()).decode()

    share = DocumentShare(
        document_id=doc_id,
        token=secrets.token_urlsafe(32),
        permission=payload.permission,
        password_hash=password_hash,
        expires_at=payload.expires_at,
        created_by_id=current_user.id,
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return _share_out(share)


@share_router.get("/{doc_id}/share")
def list_shares(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """文档的分享列表（editor+）。"""
    services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    services.content.require_editor(db, workspace_id, current_user)
    shares = (
        db.execute(
            select(DocumentShare).where(DocumentShare.document_id == doc_id).order_by(DocumentShare.created_at.desc())
        )
        .scalars()
        .all()
    )
    return {"items": [_share_out(s) for s in shares]}


@share_router.delete("/{doc_id}/share/{share_id}")
def revoke_share(
    workspace_id: int,
    doc_id: int,
    share_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """撤销分享链接（editor+）。"""
    services.content.require_editor(db, workspace_id, current_user)
    share = db.get(DocumentShare, share_id)
    if share is None or share.document_id != doc_id:
        raise NotFoundError("分享不存在")
    share.is_active = False
    db.commit()
    return {"id": share_id, "revoked": True}


def _share_out(share: DocumentShare) -> dict[str, Any]:
    return {
        "id": share.id,
        "document_id": share.document_id,
        "token": share.token,
        "permission": share.permission,
        "has_password": bool(share.password_hash),
        "expires_at": share.expires_at,
        "view_count": share.view_count,
        "is_active": share.is_active,
        "created_at": share.created_at,
    }


__all__ = ["share_router"]
