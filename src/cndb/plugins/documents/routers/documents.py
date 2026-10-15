"""documents 插件路由：文档管理 API.

端点一览（均挂 /{workspace_id}/documents 前缀）：
- POST   ""                          创建文档/文件夹（editor+）
- GET    ""                          列表（成员，支持 parent/status/tag 筛选）
- GET    /tree                       树形列表（含子节点计数）
- GET    /search                     FTS5 全文检索（工作区成员）
- POST   /daily-note                 每日笔记（幂等：当日复用同一篇）
- GET    /trash                      回收站列表（按删除时间倒序）
- GET    /{doc_id}                   详情（不含内容）
- GET    /{doc_id}/backlinks         反向链接列表（谁引用了本文档）
- GET    /{doc_id}/links             出链解析（[[标题]] 命中与断链）
- POST   /{doc_id}/links/repair      断链修复（改指现存文档，editor+）
- GET    /{doc_id}/content           详情 + 最新内容
- GET    /{doc_id}/export            导出 Markdown / Word / PDF 文件（成员）
- PUT    /{doc_id}/content           保存内容（双轨制：直编落库 / 转修改申请 202）
- PATCH  /{doc_id}                   更新元数据（标题/状态/移动/标签，editor+）
- DELETE /{doc_id}                   软删除（editor+，进回收站）
- POST   /{doc_id}/restore           从回收站恢复（editor+）
- DELETE /{doc_id}/purge             彻底删除（editor+，不可恢复）
- GET    /{doc_id}/versions          版本列表
- GET    /{doc_id}/versions/{num}    版本详情（含内容）
- GET    /{doc_id}/diff              版本差异
- POST   /{doc_id}/rollback          回滚（editor+）
- POST   /{doc_id}/lock              获取编辑锁
- DELETE /{doc_id}/lock              释放编辑锁
- GET    /{doc_id}/lock              查询锁状态
"""

from __future__ import annotations

import io
import re
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.core.errors import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents import services
from cndb.plugins.documents.models import Document, DocumentVersion, Tag
from cndb.plugins.documents.schemas import (
    ContentUpdate,
    DailyNoteRequest,
    DocumentBatchRequest,
    DocumentCreate,
    DocumentUpdate,
    LinkRepairRequest,
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
    # 个人置顶优先：置顶项排在当前排序之前（两组内部保持所选排序）
    pinned_ids = services.content.pinned_document_ids(db, workspace_id, current_user.id)

    order_col = {
        "sort": (Document.sort_order, Document.id),
        "updated": (Document.updated_at.desc(),),
        "created": (Document.created_at.desc(),),
        "title": (Document.title,),
    }[order]
    stmt = select(Document).where(*filters).order_by(*order_col).limit(limit).offset(offset)
    docs = services.content.sort_pinned_first(list(db.execute(stmt).scalars().all()), pinned_ids)
    return {
        "items": services.content.serialize_documents(db, docs, pinned_ids=pinned_ids),
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
    pinned_ids = services.content.pinned_document_ids(db, workspace_id, current_user.id)
    ordered = services.content.sort_pinned_first(list(docs), pinned_ids)
    return {"items": services.content.serialize_documents(db, ordered, pinned_ids=pinned_ids)}


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


@router.post("/daily-note")
def create_daily_note(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: DailyNoteRequest | None = None,
) -> dict[str, Any]:
    """每日笔记（幂等）：当日笔记已存在直接返回，否则按模板创建（editor+）。

    注意：必须定义在 /{doc_id} 之前，否则 "daily-note" 会被解析为 doc_id。
    """
    _require_member(db, workspace_id, current_user)
    doc, created = services.content.get_or_create_daily_note(
        db, workspace_id, current_user, day=payload.date if payload else None
    )
    return {**services.content.serialize_document(db, doc), "created": created}


@router.get("/trash")
def list_trash(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """回收站列表（成员可见，按删除时间倒序）。

    注意：必须定义在 /{doc_id} 之前，否则 "trash" 会被解析为 doc_id。
    """
    _require_member(db, workspace_id, current_user)
    docs, total = services.content.list_deleted_documents(db, workspace_id, limit=limit, offset=offset)
    items = services.content.serialize_documents(db, list(docs))
    for item, doc in zip(items, docs, strict=True):
        item["deleted_at"] = doc.deleted_at
        item["deleted_by_id"] = doc.deleted_by_id
    return {"items": items, "total": total}


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
    pinned_ids = services.content.pinned_document_ids(db, workspace_id, current_user.id)
    return services.content.serialize_document(db, doc, pinned=doc.id in pinned_ids)


@router.post("/{doc_id}/pin")
def pin_document(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """置顶文档（个人）：仅影响当前用户的树/列表顺序."""
    _require_member(db, workspace_id, current_user)
    doc = services.content.get_document_or_404(db, workspace_id, doc_id)
    pinned = services.content.set_document_pin(db, doc, current_user.id, True)
    return {"document_id": doc.id, "pinned": pinned}


@router.delete("/{doc_id}/pin", status_code=204)
def unpin_document(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """取消置顶（幂等）."""
    _require_member(db, workspace_id, current_user)
    doc = services.content.get_document_or_404(db, workspace_id, doc_id)
    services.content.set_document_pin(db, doc, current_user.id, False)


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
    pinned_ids = services.content.pinned_document_ids(db, workspace_id, current_user.id)
    data = services.content.serialize_document(db, doc, pinned=doc.id in pinned_ids)
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
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """保存文档内容（双轨制）.

    - owner / 开启直编的 editor：直接落库为新版本（乐观锁：base_updated_at 失配返回 409）；
    - viewer / 关闭直编的 editor：转为文档修改申请，返回 202 + 申请载荷（正文不落库）；
    - 非工作区成员：403。
    """
    mode = services.change_requests.resolve_write_mode(db, workspace_id, current_user)
    if mode == services.change_requests.WRITE_MODE_DENIED:
        raise PermissionDeniedError("非工作区成员")

    if mode == services.change_requests.WRITE_MODE_CHANGE_REQUEST:
        cr = services.change_requests.create_request(
            db,
            workspace_id,
            doc_id,
            current_user,
            content=payload.content,
            change_summary=payload.change_summary,
            base_version_number=payload.base_version_number,
        )
        response.status_code = 202
        return {
            "change_request": services.change_requests.serialize_request(db, cr, with_diff=True),
            "message": f"已提交修改申请 #{cr.id}，审核通过后生效",
        }

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


@router.get("/{doc_id}/export")
def export_document(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    fmt: Annotated[str, Query(alias="format")] = "md",
) -> StreamingResponse:
    """导出文档正文为 Markdown / Word(.docx) / PDF 文件.

    ``format`` 取 ``md`` / ``docx`` / ``pdf``（兼容 ``markdown`` / ``word`` 别名）；
    工作区成员即可导出（与文档读取权限一致），文件夹不可导出。
    """
    _require_member(db, workspace_id, current_user)
    normalized = services.export.normalize_format(fmt)
    if normalized is None:
        raise BadRequestError(f"不支持的导出格式: {fmt}，可选 {'/'.join(services.export.SUPPORTED_FORMATS)}")
    doc = services.content.get_document_or_404(db, workspace_id, doc_id)
    if doc.is_folder:
        raise BadRequestError("文件夹不支持导出")

    version = services.content.latest_version(db, doc.id)
    content = services.content.load_content(version, doc) if version else ""
    # 站内图片（``![alt](file:<key>)``）在 Word / PDF 导出中嵌入真实文件；
    # 解析器限定在该工作区上传目录内，非法 / 缺失的引用降级为占位文字
    images = services.export.make_image_resolver(settings.UPLOAD_DIR, workspace_id)
    file_bytes = services.export.render_export(content, normalized, doc.title, images=images)

    # Markdown 带站内图片时打包为 zip（<标题>.md + assets/<file_key>），否则维持单文件 .md
    media_type = services.export.FORMAT_CONTENT_TYPES[normalized]
    extension = services.export.FORMAT_EXTENSIONS[normalized]
    if normalized == services.export.FORMAT_MARKDOWN:
        archive = services.export.render_markdown_archive(
            content,
            doc.title,
            images,
            _export_filename(doc.title, "").rstrip("."),
        )
        if archive is not None:
            file_bytes = archive
            media_type = "application/zip"
            extension = "zip"

    filename = _export_filename(doc.title, extension)
    quoted = quote(filename)
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=media_type,
        headers={
            # ASCII fallback + RFC 5987 filename*（标题含中文时保证文件名正确）
            "Content-Disposition": f"attachment; filename=\"document.{normalized}\"; filename*=UTF-8''{quoted}"
        },
    )


def _export_filename(title: str, ext: str) -> str:
    """构造导出文件名：``{标题}.{ext}``，剔除文件系统非法字符."""
    safe = re.sub(r'[\\/:*?"<>|]', "_", title).strip() or "document"
    return f"{safe}.{ext}"


@router.post("/batch")
def batch_documents(
    workspace_id: int,
    payload: DocumentBatchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """批量移动 / 删除文档与文件夹.

    - ``action=move``：把 ``ids`` 移动到 ``parent_id``（``0`` / ``None`` = 根目录）；
    - ``action=delete``：软删除（文件夹连同子孙进入回收站）。

    逐项校验：不存在 / 已删除 / 目标非法 / 防环等失败项**不中断**整批，
    统一放进 ``skipped`` 返回，便于前端提示「成功 N 项，跳过 M 项」。
    """
    _require_member(db, workspace_id, current_user)
    services.content.require_editor(db, workspace_id, current_user)

    ids = list(dict.fromkeys(payload.ids))  # 去重并保持顺序
    skipped: list[dict[str, Any]] = []

    def _load_ok(doc_id: int) -> Document | None:
        doc = db.get(Document, doc_id)
        if doc is None or doc.workspace_id != workspace_id or doc.is_deleted:
            skipped.append({"id": doc_id, "reason": "文档不存在或已在回收站"})
            return None
        return doc

    if payload.action == "move":
        target = 0 if payload.parent_id is None else payload.parent_id
        moved: list[Document] = []
        for doc_id in ids:
            doc = _load_ok(doc_id)
            if doc is None:
                continue
            reason = services.content.move_target_reason(db, workspace_id, doc, target)
            if reason:
                skipped.append({"id": doc_id, "reason": reason})
                continue
            doc.parent_id = None if target == 0 else target
            doc.updated_by_id = current_user.id
            moved.append(doc)
        db.commit()
        return {"action": "move", "updated": len(moved), "skipped": skipped}

    docs: list[Document] = []
    for doc_id in ids:
        doc = _load_ok(doc_id)
        if doc is not None:
            docs.append(doc)
    updated = services.content.soft_delete_documents(db, workspace_id, docs, current_user)
    return {"action": "delete", "updated": updated, "skipped": skipped}


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
        # 校验复用批量移动的同一实现（services.content.move_target_reason）
        reason = services.content.move_target_reason(db, workspace_id, doc, payload.parent_id)
        if reason:
            raise ConflictError(reason)
        # 0 = 移动到根目录（None 语义为"不修改"，无法表达"改回根"）
        doc.parent_id = None if payload.parent_id == 0 else payload.parent_id
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


@router.post("/{doc_id}/restore")
def restore_document(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """从回收站恢复（editor+）：文件夹连同同一删除批次的子项一起恢复。"""
    doc, restored_count, reparented = services.content.restore_document(db, workspace_id, doc_id, current_user)
    data = services.content.serialize_document(db, doc)
    data["restored_count"] = restored_count
    data["reparented_to_root"] = reparented
    return data


@router.delete("/{doc_id}/purge")
def purge_document(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """彻底删除回收站文档（editor+，不可恢复；一并清理版本与外存内容）。"""
    stats = services.content.purge_document(db, workspace_id, doc_id, current_user)
    return {"id": doc_id, "purged": True, **stats}


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


# ── 反向链接 ──


@router.get("/{doc_id}/backlinks")
def get_backlinks(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """反向链接：工作区内正文含 ``[[本文档标题]]`` 的文档列表（含自引用）。"""
    _require_member(db, workspace_id, current_user)
    doc = services.content.get_document_or_404(db, workspace_id, doc_id)
    hits = services.content.find_backlinks(db, workspace_id, doc.title)
    return {
        "items": [
            {
                "id": d.id,
                "title": d.title,
                "summary": d.summary,
                "status": d.status,
                "updated_at": d.updated_at,
            }
            for d in hits
        ],
        "total": len(hits),
    }


@router.get("/{doc_id}/links")
def get_outgoing_links(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """出链解析：正文 ``[[标题]]`` 指向的文档与断链清单（工作区成员）。"""
    _require_member(db, workspace_id, current_user)
    doc = services.content.get_document_or_404(db, workspace_id, doc_id)
    items = services.content.resolve_outgoing_links(db, workspace_id, doc)
    return {
        "items": items,
        "total": len(items),
        "broken": sum(1 for item in items if item["broken"]),
    }


@router.post("/{doc_id}/links/repair")
def repair_links(
    workspace_id: int,
    doc_id: int,
    payload: LinkRepairRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """修复断链（editor+）：把正文中 ``[[旧标题]]`` 改指为现存文档，生成新版本。"""
    return services.content.repair_wikilinks(db, workspace_id, doc_id, current_user, payload.repairs)


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
