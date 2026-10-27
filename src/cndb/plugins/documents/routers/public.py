"""documents 插件公开路由：分享链接匿名访问（无需登录）.

端点：
- GET  /api/v1/documents/share/{token}                匿名读取分享文档
- POST /api/v1/documents/share/{token}                密码校验并读取
- GET  /api/v1/documents/share/{token}/meta           分享元信息（标题 / 是否需要密码）
- GET  /api/v1/documents/share/{token}/files/{key}    正文站内图片（免登录）
- GET  /api/v1/documents/share/{token}/charts/{id}/render
                                                      正文引用图表免登录渲染（D9 白名单）

所有端点共用 ``resolve_public_share`` 作为唯一判定入口：未知 token、已撤销、
已过期、文档已软删 / 未发布一律 404，且文案一致（不泄露链接是否存在）。
"""

from __future__ import annotations

import datetime as dt
import mimetypes
from pathlib import Path as PathLib
from typing import Annotated, Any

import bcrypt
from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cndb.core.database import get_db
from cndb.core.errors import BadRequestError, NotFoundError, PermissionDeniedError
from cndb.plugins.documents import services
from cndb.plugins.documents.models import DOC_STATUS_PUBLISHED, Document, DocumentChart, DocumentShare
from cndb.plugins.documents.schemas import ShareAccessRequest
from cndb.plugins.documents.services import charts
from cndb.plugins.documents.services.export import chart_refs
from cndb.plugins.files import services as files_service

public_router = APIRouter(prefix="/api/v1/documents/share", tags=["documents"])

# 失效统一文案：不区分「从未存在 / 已撤销 / 已过期 / 已下线 / 已在回收站」
_SHARE_GONE = "分享链接不存在或已失效"

# 公开页只放行栅格图片：svg / html / xml 可内嵌脚本，匿名页不渲染
_PUBLIC_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tiff"}
)


def resolve_public_share(db: Session, token: str) -> tuple[DocumentShare, Document]:
    """匿名分享唯一判定入口；任何失败一律 404，不区分原因.

    判定顺序固定：token 存在且激活 → 未过期 → 文档未软删且已发布。
    """
    share = db.execute(
        select(DocumentShare).where(
            DocumentShare.token == token,
            DocumentShare.is_active == True,  # noqa: E712
        )
    ).scalar_one_or_none()
    if share is None:
        raise NotFoundError(_SHARE_GONE)
    if share.expires_at is not None:
        expires = share.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=dt.UTC)
        if expires < dt.datetime.now(dt.UTC):
            raise NotFoundError(_SHARE_GONE)
    doc = db.execute(
        select(Document).where(
            Document.id == share.document_id,
            Document.is_deleted == False,  # noqa: E712
            Document.status == DOC_STATUS_PUBLISHED,
        )
    ).scalar_one_or_none()
    if doc is None:
        raise NotFoundError(_SHARE_GONE)
    return share, doc


def serialize_public_document(db: Session, doc: Document) -> dict[str, Any]:
    """公开响应白名单：只暴露标题 / 正文 / 更新时间，不随内部序列化扩张."""
    data: dict[str, Any] = {"title": doc.title, "updated_at": doc.updated_at}
    if not doc.is_folder:
        data["content"] = services.content.load_content(services.content.latest_version(db, doc.id), doc)
    return data


def _count_view(db: Session, share: DocumentShare) -> None:
    """访问计数原子 +1，避免并发读改写丢失."""
    db.execute(
        update(DocumentShare).where(DocumentShare.id == share.id).values(view_count=DocumentShare.view_count + 1)
    )
    db.commit()


def _no_store(response: Response) -> None:
    """匿名响应不可缓存：撤销 / 下线后浏览器不得继续展示旧内容."""
    response.headers["Cache-Control"] = "no-store"


@public_router.get("/{token}")
def access_shared_document(
    token: str,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """匿名访问分享文档（无密码分享直接返回；有密码返回 403 提示）."""
    share, doc = resolve_public_share(db, token)
    if share.password_hash:
        raise PermissionDeniedError("此分享需要密码访问", code="share_password_required")

    _count_view(db, share)
    _no_store(response)
    return serialize_public_document(db, doc)


@public_router.post("/{token}")
def access_shared_with_password(
    token: str,
    payload: ShareAccessRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """带密码访问分享文档."""
    share, doc = resolve_public_share(db, token)
    if not share.password_hash:
        raise BadRequestError("此分享无需密码")
    if not payload.password or not bcrypt.checkpw(
        payload.password.encode("utf-8"), share.password_hash.encode("utf-8")
    ):
        raise PermissionDeniedError("密码错误")

    _count_view(db, share)
    _no_store(response)
    return serialize_public_document(db, doc)


@public_router.get("/{token}/meta")
def share_meta(
    token: str,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """分享元信息（标题 / 是否需要密码），供前端访问页预检；不计数."""
    share, doc = resolve_public_share(db, token)
    _no_store(response)
    return {"title": doc.title, "has_password": bool(share.password_hash)}


@public_router.get("/{token}/files/{file_key}")
def access_shared_file(
    token: str,
    file_key: str,
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    """匿名读取正文里的站内图片.

    只放行归属当前分享文档的栅格图片：借 token 读不到工作区其它附件 / 表附件。
    """
    _, doc = resolve_public_share(db, token)
    ext = PathLib(file_key).suffix.lower()
    if ext not in _PUBLIC_IMAGE_EXTENSIONS:
        raise NotFoundError(_SHARE_GONE)

    owner = files_service.owner_of(db, file_key)
    if owner is None or owner.workspace_id != doc.workspace_id or owner.document_id != doc.id:
        raise NotFoundError(_SHARE_GONE)

    target = files_service.resolve_workspace_file(doc.workspace_id, file_key)
    if not target.is_file():
        raise NotFoundError(_SHARE_GONE)

    media_type = mimetypes.guess_type(file_key)[0] or "application/octet-stream"
    return FileResponse(
        path=str(target),
        media_type=media_type,
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@public_router.get("/{token}/charts/{chart_id}/render")
def access_shared_chart_render(
    token: str,
    chart_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """匿名渲染正文引用的图表（D9 免登录）.

    白名单判定：token 有效且 ``chart_id`` 出现在该分享文档正文的 ``{{chart:…}}``
    引用集合内才放行（防跨图表 ID 探测）；集合外 / 实例已删 / 跨工作区一律 404。
    模板下线降级为占位整幅图（与成员 render 同口径，I5/I6）。
    """
    _, doc = resolve_public_share(db, token)
    content = ""
    if not doc.is_folder:
        content = services.content.load_content(services.content.latest_version(db, doc.id), doc)
    if chart_id not in chart_refs.referenced_chart_ids(content):
        raise NotFoundError(_SHARE_GONE)
    chart = db.get(DocumentChart, chart_id)
    if chart is None or chart.workspace_id != doc.workspace_id:
        raise NotFoundError(_SHARE_GONE)

    svg = charts.render_instance_svg(chart.template_key, chart.config, chart.id)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


__all__ = ["public_router", "resolve_public_share", "router", "serialize_public_document"]

# tables 插件公开路由约定别名（app.py 统一 import router）
router = public_router
