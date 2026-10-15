"""documents 插件公开路由：分享链接匿名访问（无需登录）.

端点：
- GET /api/v1/documents/share/{token}          匿名读取分享文档
- GET /api/v1/documents/share/{token}/verify   密码校验（有密码分享）
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

import bcrypt
from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cndb.core.database import get_db
from cndb.core.errors import BadRequestError, NotFoundError, PermissionDeniedError
from cndb.plugins.documents import services
from cndb.plugins.documents.models import DOC_STATUS_PUBLISHED, DocumentShare
from cndb.plugins.documents.schemas import ShareAccessRequest

public_router = APIRouter(prefix="/api/v1/documents/share", tags=["documents"])


def _get_active_share(db: Session, token: str) -> DocumentShare:
    """取有效分享（激活且未过期），无效抛 404。"""
    share = db.execute(
        select(DocumentShare).where(
            DocumentShare.token == token,
            DocumentShare.is_active == True,  # noqa: E712
        )
    ).scalar_one_or_none()
    if share is None:
        raise NotFoundError("分享链接不存在或已被撤销")
    if share.expires_at is not None:
        expires = share.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=dt.UTC)
        if expires < dt.datetime.now(dt.UTC):
            raise PermissionDeniedError("分享链接已过期")
    return share


@public_router.get("/{token}")
def access_shared_document(
    token: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """匿名访问分享文档（无密码分享直接返回；有密码返回 401 提示）."""
    share = _get_active_share(db, token)
    if share.password_hash:
        raise PermissionDeniedError("此分享需要密码访问", code="share_password_required")

    doc = services.content.get_document_or_404(db, _doc_workspace(db, share), share.document_id)
    # 未发布（草稿/归档）文档的分享链接一律视为失效：避免"分享后取消发布"仍能访问未发布内容
    if doc.status != DOC_STATUS_PUBLISHED:
        raise NotFoundError("分享链接已失效")
    db.execute(update(DocumentShare).where(DocumentShare.id == share.id).values(view_count=share.view_count + 1))
    db.commit()

    data = services.content.serialize_document(db, doc)
    if not doc.is_folder:
        v = services.content.latest_version(db, doc.id)
        data["content"] = services.content.load_content(v, doc)
    data.pop("created_by_id", None)
    data.pop("updated_by_id", None)
    return data


@public_router.post("/{token}")
def access_shared_with_password(
    token: str,
    payload: ShareAccessRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """带密码访问分享文档."""
    share = _get_active_share(db, token)
    if not share.password_hash:
        raise BadRequestError("此分享无需密码")
    if not payload.password or not bcrypt.checkpw(
        payload.password.encode("utf-8"), share.password_hash.encode("utf-8")
    ):
        raise PermissionDeniedError("密码错误")

    doc = services.content.get_document_or_404(db, _doc_workspace(db, share), share.document_id)
    # 与无密码入口一致：未发布内容不得通过分享链接访问
    if doc.status != DOC_STATUS_PUBLISHED:
        raise NotFoundError("分享链接已失效")
    db.execute(update(DocumentShare).where(DocumentShare.id == share.id).values(view_count=share.view_count + 1))
    db.commit()

    data = services.content.serialize_document(db, doc)
    if not doc.is_folder:
        v = services.content.latest_version(db, doc.id)
        data["content"] = services.content.load_content(v, doc)
    data.pop("created_by_id", None)
    data.pop("updated_by_id", None)
    return data


def _doc_workspace(db: Session, share: DocumentShare) -> int:
    """通过分享关联的文档取工作区 ID。"""
    from cndb.plugins.documents.models import Document

    ws_id = db.execute(select(Document.workspace_id).where(Document.id == share.document_id)).scalar_one_or_none()
    if ws_id is None:
        raise NotFoundError("文档不存在")
    return int(ws_id)


@public_router.get("/{token}/meta")
def share_meta(token: str, db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """分享元信息（标题/是否需要密码），供前端访问页预检."""
    share = _get_active_share(db, token)
    from cndb.plugins.documents.models import Document

    title = db.execute(select(Document.title).where(Document.id == share.document_id)).scalar_one_or_none()
    return {"title": title or "", "has_password": bool(share.password_hash)}


__all__ = ["public_router", "router"]

# tables 插件公开路由约定别名（app.py 统一 import router）
router = public_router
