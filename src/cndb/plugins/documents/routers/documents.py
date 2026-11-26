"""documents 插件路由：文档管理 API.

端点一览（均挂 /{workspace_id}/documents 前缀）：
- POST   ""                          创建文档/文件夹（editor+）
- GET    ""                          列表（成员，支持 parent/status/tag 筛选）
- GET    /tree                       树形列表（含子节点计数）
- GET    /search                     FTS5 全文检索（工作区成员）
- GET    /trash                      回收站列表（按删除时间倒序）
- GET    /{doc_id}                   详情（不含内容）
- GET    /{doc_id}/backlinks         反向链接列表（谁引用了本文档）
- GET    /{doc_id}/links             出链解析（[[标题]] 命中与断链）
- POST   /{doc_id}/links/repair      断链修复（改指现存文档，editor+）
- GET    /{doc_id}/content           详情 + 最新内容（含个人草稿与写模式）
- GET    /{doc_id}/export            导出 Markdown / Word / PDF 文件（成员）
- PUT    /{doc_id}/content           保存内容（双轨制：直编落库 / 转修改申请 202，兼容旧行为）
- GET    /{doc_id}/draft             读取个人工作草稿
- GET    /{doc_id}/draft/diff        「基准版本 → 草稿」unified diff（ADR 0057）
- PUT    /{doc_id}/draft             保存个人工作草稿（不生成版本）
- DELETE /{doc_id}/draft             丢弃个人工作草稿
- POST   /{doc_id}/submit            显式提交修改（直编 200 / 修改申请 202）
- PATCH  /{doc_id}                   更新元数据（标题/状态/移动/标签，editor+）
- DELETE /{doc_id}                   软删除（editor+，进回收站）
- POST   /{doc_id}/restore           从回收站恢复（editor+）
- DELETE /{doc_id}/purge             彻底删除（editor+，不可恢复）
- GET    /{doc_id}/versions          版本列表
- GET    /{doc_id}/versions/{num}    版本详情（含内容）
- GET    /{doc_id}/diff              版本差异
- POST   /{doc_id}/rollback          回滚（editor+）
"""

from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.core.errors import BadRequestError, CndbError, ConflictError, NotFoundError
from cndb.core.events import record_event
from cndb.core.textdiff import unified_diff
from cndb.plugins.accounts.models import User
from cndb.plugins.documents import services
from cndb.plugins.documents.models import Document, DocumentVersion, Tag
from cndb.plugins.documents.schemas import (
    ContentUpdate,
    DocumentAiActionRequest,
    DocumentBatchRequest,
    DocumentCreate,
    DocumentDraftSave,
    DocumentDuplicateRequest,
    DocumentMoveRequest,
    DocumentSubmit,
    DocumentUpdate,
    LinkRepairRequest,
    ReferenceRepairRequest,
    RollbackRequest,
    TagIdsRequest,
)
from cndb.plugins.llm.services import gateway as llm_gateway
from cndb.plugins.llm.services.errors import LlmError
from cndb.plugins.llm.services.gateway import LlmContext
from cndb.plugins.workspaces.permissions import raise_permission_denied, workspace_data_role

# 文档树缓存 TTL（秒）
DOC_TREE_TTL_SECONDS = 10.0


def invalidate_document_tree_cache(workspace_id: int) -> int:
    """失效某工作区的文档树缓存."""
    from cndb.core.cache import cache_key, list_cache

    return list_cache.clear(cache_key("doc-tree", workspace_id))


def invalidate_tree_on_write(request: Request) -> None:
    """文档路由的**写请求**先失效该工作区的文档树缓存.

    文档写路径分散在 routers 与 services（多处 commit），逐个埋点容易漏；
    这里按"方法即意图"统一处理：非 GET/HEAD/OPTIONS 请求进入文档路由时先清缓存，
    随后的写与后续读取都能拿到最新树形数据（TTL 10s 仅作兜底）。
    取舍：清缓存发生在写入提交之前，理论上存在"并发读把旧数据写回缓存"的窄窗口
    （毫秒级 + 10s TTL 上限），对文档树这类展示型数据可接受。
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    wid = request.path_params.get("workspace_id")
    if wid is None:
        return
    try:
        invalidate_document_tree_cache(int(wid))
    except (TypeError, ValueError):  # pragma: no cover - 路径参数异常时忽略
        return


router = APIRouter(
    prefix="/{workspace_id}/documents",
    tags=["documents"],
    dependencies=[Depends(invalidate_tree_on_write)],
)


def _require_member(db: Session, workspace_id: int, user: User) -> None:
    """校验当前用户是工作区成员（读权限最低要求）。"""
    from cndb.plugins.workspaces.models import Workspace

    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("工作区不存在")
    if workspace_data_role(user, ws, db) is None:
        # ADR 0047：403 文案带角色与拥有者指引（唯一出口，非成员走「申请加入」分支）
        raise_permission_denied(db, ws, user)


def _audit_document(
    db: Session,
    workspace_id: int,
    user: User,
    action: str,
    doc: Document,
    *,
    summary: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """文档域审计（需求 0173）：只记定位信息，不落正文；任何异常都不阻断主流程."""
    try:
        record_event(
            db,
            action,
            summary=summary or doc.title,
            target_type="document",
            target_id=doc.id,
            workspace_id=workspace_id,
            actor_id=user.id,
            actor_name=user.username,
            detail=detail or {},
        )
    except Exception:  # pragma: no cover - 审计失败不得影响文档写操作
        logging.getLogger(__name__).warning("文档审计事件写入失败 action=%s", action, exc_info=True)


# ── 跨工作区移动（ADR 0155）──
# 静态段路由必须注册在 /{doc_id} 一族之前，否则 "move-to-workspace" / "move-targets"
# 会被当成 doc_id 解析（422）。


@router.get("/move-targets")
def list_move_targets(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """可移动目标工作区（有写权限 + 已启用文档模块 + 配额余量）.

    前端弹窗只展示本接口返回的候选，避免前端自行猜权限（ADR 0155 D10）。
    """
    _require_member(db, workspace_id, current_user)
    return {"items": services.move.move_targets(db, source_workspace_id=workspace_id, actor=current_user)}


@router.post("/references/preview")
def preview_reference_repair(
    workspace_id: int,
    payload: ReferenceRepairRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """预览跨工作区移动后的引用修复（ADR 0156）：只返回「原文 → 新文」，不落库."""
    _require_member(db, workspace_id, current_user)
    services.content.require_editor(db, workspace_id, current_user)
    try:
        issues = services.references.diagnose_move_references(
            db,
            source_workspace_id=workspace_id,
            target_workspace_id=payload.target_workspace_id,
            moved_doc_ids=[int(doc_id) for doc_id in payload.document_ids],
        )
        previews = services.references.preview_repair(db, issues=issues, strategy=payload.strategy, actor=current_user)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    return {
        "strategy": payload.strategy,
        "issues": [issue.as_payload() for issue in issues],
        "previews": [preview.as_payload() for preview in previews],
        "affected_documents": sorted({preview.document_id for preview in previews}),
    }


@router.post("/references/repair")
def repair_references(
    workspace_id: int,
    payload: ReferenceRepairRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """执行引用修复（ADR 0156）：按最新版本重算并生成新版本（可回滚）。"""
    _require_member(db, workspace_id, current_user)
    services.content.require_editor(db, workspace_id, current_user)
    result = services.references.apply_repair(
        db,
        source_workspace_id=workspace_id,
        target_workspace_id=payload.target_workspace_id,
        moved_doc_ids=[int(doc_id) for doc_id in payload.document_ids],
        strategy=payload.strategy,
        actor=current_user,
        confirm=True,
    )
    return result.as_payload()


@router.post("/move-to-workspace")
def move_documents_to_workspace(
    workspace_id: int,
    payload: DocumentMoveRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """把文档 / 多篇 / 文件夹（子树整体）移动到目标工作区（ADR 0155）.

    - 源 `WRITE` + 目标 `WRITE` + 目标开启文档模块（与删除 / 新建文档同口径）；
    - 保留文档 id 与版本链、站内文件、问题讨论、待审修改申请；访客分享链接继续有效；
    - 目标配额不足在写盘前拦下（413，文案含差额）；
    - 失败整体回滚，不留半移动状态。
    """
    result = services.move.move_nodes_to_workspace(
        db,
        source_workspace_id=workspace_id,
        root_ids=[int(doc_id) for doc_id in payload.document_ids],
        target_workspace_id=payload.target_workspace_id,
        actor=current_user,
        parent_id=payload.parent_id,
    )
    invalidate_document_tree_cache(workspace_id)
    invalidate_document_tree_cache(payload.target_workspace_id)
    record_event(
        db,
        "document.move",
        summary=f"跨工作区移动 {len(result.document_ids)} 个文档",
        target_type="document",
        target_id=result.document_ids[0] if result.document_ids else None,
        workspace_id=workspace_id,
        actor_id=current_user.id,
        actor_name=current_user.username,
        detail={
            "document_ids": list(result.document_ids),
            "target_workspace_id": payload.target_workspace_id,
        },
    )
    payload_out = result.as_payload()
    # 引用修复（ADR 0156）：发生在移动提交之后；失败不回滚移动（用户可再点一次「修复引用」，幂等）
    if payload.repair_strategy != "none":
        try:
            repair = services.references.apply_repair(
                db,
                source_workspace_id=workspace_id,
                target_workspace_id=payload.target_workspace_id,
                moved_doc_ids=result.document_ids,
                strategy=payload.repair_strategy,
                actor=current_user,
                confirm=True,
            )
        except Exception:  # pragma: no cover - 修复异常不阻断移动结果
            logging.getLogger(__name__).warning("移动后的引用修复失败", exc_info=True)
            payload_out["reference_repair"] = None
        else:
            payload_out["reference_repair"] = repair.as_payload()
            invalidate_document_tree_cache(workspace_id)
            invalidate_document_tree_cache(payload.target_workspace_id)
    return payload_out


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
    # 写入口校验绑定引用（ADR 0177 C7）：非法 / 跨区 → 400；文件夹没有导出物
    if payload.is_folder and payload.export_template_ref is not None:
        raise BadRequestError("文件夹不支持绑定排版模板")
    try:
        export_template_ref = services.export.validate_export_template_ref(
            db, workspace_id, payload.export_template_ref
        )
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
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
        export_template_ref=export_template_ref,
    )
    _audit_document(
        db,
        workspace_id,
        current_user,
        "document.create",
        doc,
        summary=f"创建文档：{doc.title}",
        detail={"is_folder": doc.is_folder, "status": doc.status},
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
    """文档列表（工作区成员）."""
    _require_member(db, workspace_id, current_user)

    # 共享筛选条件（数据查询与 total 计数一致）
    filters: list[ColumnElement[bool]] = [
        Document.workspace_id == workspace_id,
        Document.is_deleted == False,  # noqa: E712
        # 可见性：草稿/归档仅创建者与工作区所有者可见（不暴露他人未发布内容）
        services.visibility.visible_condition(db, workspace_id, current_user),
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
    """全量文档树（工作区成员，含文件夹层级）."""
    _require_member(db, workspace_id, current_user)

    from cndb.core.cache import cache_key, list_cache

    ck = cache_key("doc-tree", workspace_id, current_user.id, id(db.bind))
    cached = list_cache.get(ck)
    if cached is not None:
        return cached
    data = _document_tree_uncached(db, workspace_id, current_user)
    list_cache.set(ck, data, DOC_TREE_TTL_SECONDS)
    return data


def _document_tree_uncached(
    db: Session,
    workspace_id: int,
    current_user: User,
) -> dict[str, Any]:
    all_docs = list(
        db.execute(
            select(Document)
            .where(Document.workspace_id == workspace_id, Document.is_deleted == False)  # noqa: E712
            .order_by(Document.sort_order, Document.id)
        )
        .scalars()
        .all()
    )
    # 可见性：隐藏他人草稿；同时保留可见节点的祖先文件夹，避免目录树出现孤儿节点
    visible = services.visibility.filter_visible_documents(db, workspace_id, all_docs, current_user)
    visible_ids = {d.id for d in visible}
    visible_ids |= services.visibility.visible_ancestor_ids(all_docs, visible)
    ordered_docs = [d for d in all_docs if d.id in visible_ids]
    pinned_ids = services.content.pinned_document_ids(db, workspace_id, current_user.id)
    ordered = services.content.sort_pinned_first(ordered_docs, pinned_ids)
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
    # 标签计数按"当前用户可见文档"重算：Tag.doc_count 是全量计数，
    # 直接返回会泄露"只被他人草稿引用的标签"及其数量。
    from cndb.plugins.documents.models import DocumentTag

    counts_rows = db.execute(
        select(DocumentTag.tag_id, func.count())
        .join(Document, Document.id == DocumentTag.document_id)
        .where(
            Document.workspace_id == workspace_id,
            Document.is_deleted == False,  # noqa: E712
            services.visibility.visible_condition(db, workspace_id, current_user),
        )
        .group_by(DocumentTag.tag_id)
    ).all()
    visible_counts = {int(tid): int(cnt) for tid, cnt in counts_rows}
    return {
        "items": [
            {
                "id": t.id,
                "workspace_id": t.workspace_id,
                "name": t.name,
                "color": t.color,
                "description": t.description,
                "doc_count": visible_counts.get(t.id, 0),
            }
            for t in tags
            if visible_counts.get(t.id, 0) > 0
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
        # 可见性：全文检索不得命中他人草稿/未发布内容
        viewer_id=current_user.id,
        is_admin=services.visibility.is_document_admin(db, workspace_id, current_user),
    )
    return {"items": items, "total": total, "query": q}


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
    docs, total = services.content.list_deleted_documents(
        db,
        workspace_id,
        limit=limit,
        offset=offset,
        viewer=current_user,
        is_admin=services.visibility.is_document_admin(db, workspace_id, current_user),
    )
    items = services.content.serialize_documents(db, list(docs))
    for item, doc in zip(items, docs, strict=True):
        item["deleted_at"] = doc.deleted_at
        item["deleted_by_id"] = doc.deleted_by_id
    return {"items": items, "total": total}


@router.post("/{doc_id}/duplicate", status_code=201)
def duplicate_document(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: DocumentDuplicateRequest | None = None,
) -> dict[str, Any]:
    """创建文档 / 文件夹子树副本（需求 0172，owner/editor）."""
    services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    doc = services.content.duplicate_document(
        db,
        workspace_id,
        doc_id,
        current_user,
        parent_id=payload.parent_id if payload else None,
    )
    record_event(
        db,
        "document.duplicate",
        summary=f"创建副本：{doc.title}",
        target_type="document",
        target_id=doc.id,
        workspace_id=workspace_id,
        actor_id=current_user.id,
        actor_name=current_user.username,
        detail={"source_document_id": doc_id},
    )
    return services.content.serialize_document(db, doc)


@router.get("/{doc_id}")
def get_document(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """文档详情（不含正文）。"""
    _require_member(db, workspace_id, current_user)
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
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
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
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
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
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
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    pinned_ids = services.content.pinned_document_ids(db, workspace_id, current_user.id)
    data = services.content.serialize_document(db, doc, pinned=doc.id in pinned_ids)
    if doc.is_folder:
        data["content"] = ""
        data["draft"] = None
    else:
        v = services.content.latest_version(db, doc.id)
        data["content"] = services.content.load_content(v, doc)
        data["version_number"] = v.version_number if v else 0
        # 个人工作草稿：前端据此决定默认进入编辑模式（有草稿 → 编辑）
        data["draft"] = services.drafts.draft_payload(db, doc, current_user)
    # 当前用户的写模式：direct 直编 / change_request 走修改申请
    data["write_mode"] = services.change_requests.resolve_write_mode(db, workspace_id, current_user)
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
        from cndb.plugins.workspaces.models import Workspace

        ws = db.get(Workspace, workspace_id)
        if ws is None:
            raise NotFoundError("工作区不存在")
        # ADR 0047：403 文案带角色与拥有者指引（唯一出口）
        raise_permission_denied(db, ws, current_user)

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
        # 旧「保存即提交」路径：提交成功后清理个人草稿，避免同一改动出现两份
        services.drafts.delete_draft(db, workspace_id, doc_id, current_user)
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

    # 旧「保存即提交」路径：正文已落库，清理对应个人草稿
    services.drafts.delete_draft(db, workspace_id, doc_id, current_user)

    data = services.content.serialize_document(db, doc)
    v = services.content.latest_version(db, doc.id)
    data["content"] = payload.content
    data["version_number"] = v.version_number if v else 0
    _audit_document(
        db,
        workspace_id,
        current_user,
        "document.update_content",
        doc,
        summary=f"更新正文：{doc.title}",
        detail={"version_number": data["version_number"], "content_size": doc.content_size},
    )
    return data


@router.get("/{doc_id}/draft")
def get_document_draft(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """读取当前用户的个人工作草稿（没有或已与正文一致时 draft 为 null）."""
    _require_member(db, workspace_id, current_user)
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    return {"draft": services.drafts.draft_payload(db, doc, current_user)}


@router.put("/{doc_id}/draft")
def save_document_draft(
    workspace_id: int,
    doc_id: int,
    payload: DocumentDraftSave,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """保存个人工作草稿：只写草稿表，不生成版本、不触发审核.

    草稿与最新版本内容一致时等价于「无修改」，服务端删除草稿并返回 draft=null。
    """
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    draft = services.drafts.save_draft(
        db,
        workspace_id,
        doc_id,
        current_user,
        content=payload.content,
        base_version_number=payload.base_version_number,
    )
    if draft is None:
        return {"draft": None, "message": "内容与当前版本一致，无需保存草稿"}
    return {"draft": services.drafts.draft_payload(db, doc, current_user)}


@router.delete("/{doc_id}/draft", status_code=204)
def discard_document_draft(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """丢弃个人工作草稿（幂等）."""
    services.drafts.delete_draft(db, workspace_id, doc_id, current_user)
    return Response(status_code=204)


@router.get("/{doc_id}/draft/diff")
def draft_diff(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """「基准版本 → 草稿」unified diff（ADR 0057，只读）.

    无草稿返回 404（code=no_draft）；基准为草稿的 base_version_number，
    基准版本缺失时回退最新版本；stale=true 表示文档已前进版本。
    """
    return services.drafts.draft_diff(db, workspace_id, doc_id, current_user)


@router.post("/{doc_id}/submit")
def submit_document_content(
    workspace_id: int,
    doc_id: int,
    payload: DocumentSubmit,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """显式提交修改（手动动作，替代「保存即提交」）.

    - 有直编资格：落库为新版本，返回 200；
    - 否则：生成修改申请，返回 202；
    - 正文与服务端最新版本一致：409（code=no_changes），不产生版本/申请。
    """
    result = services.drafts.submit_draft(
        db,
        workspace_id,
        doc_id,
        current_user,
        content=payload.content,
        change_summary=payload.change_summary,
        base_version_number=payload.base_version_number,
    )
    if result.get("mode") == "change_request":
        response.status_code = 202
    return result


@router.post("/{doc_id}/ai/actions/{action}")
def run_document_ai_action(
    workspace_id: int,
    doc_id: int,
    action: str,
    payload: DocumentAiActionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """文档 AI 动作（ADR 0020 P1）：选区改写 / 摘要 / 标签建议.

    - 只读动作：工作区成员即可（viewer 用自己的个人 Key）；
    - 不写文档：改写结果由前端写回编辑器内存态，摘要 / 标签仅返回建议；
    - 模型输出不合 schema → 422（零副作用），未配置 Key → 400，上游失败 → 502。
    """
    _require_member(db, workspace_id, current_user)
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    spec = services.ai.DOCUMENT_ACTIONS.get(action)
    if spec is None:
        raise NotFoundError(f"未知 AI 动作: {action}")
    if doc.is_folder:
        raise BadRequestError("文件夹不支持 AI 操作")

    truncated = False
    if action == "polish":
        selection = (payload.selection or "").strip()
        if not selection:
            raise BadRequestError("请先选中要改写的文本")
        if len(selection) > services.ai.MAX_SELECTION_CHARS:
            raise BadRequestError(
                f"选中文本过长（{len(selection)} > {services.ai.MAX_SELECTION_CHARS} 字），请分段改写"
            )
        if payload.instruction not in services.ai.POLISH_INSTRUCTIONS:
            raise BadRequestError(f"不支持的改写指令: {payload.instruction}")
        user_content = services.ai.build_polish_content(
            selection,
            payload.instruction,
            language=payload.language,
            context=payload.context,
        )
    else:
        version = services.content.latest_version(db, doc.id)
        body = services.content.load_content(version, doc) if version is not None else ""
        user_content, truncated = services.ai.prepare_document_content(body)
        if not user_content:
            raise BadRequestError("文档正文为空，无法生成")

    try:
        result = llm_gateway.invoke(
            db,
            current_user,
            spec,
            user_content=user_content,
            context=LlmContext(workspace_id=workspace_id, target_type="document", target_id=doc.id),
        )
    except LlmError as exc:
        # 平台错误分类 → 统一业务异常（保留 400/422/429/502 语义与中文文案）
        raise CndbError(str(exc), status_code=exc.status_code, code=exc.code) from exc

    parsed = result.parsed
    result_payload = parsed.model_dump() if hasattr(parsed, "model_dump") else {"text": str(parsed)}
    return {
        "action": spec.name,
        "run_id": result.run_id,
        "model": result.model,
        "usage": result.usage,
        "result": result_payload,
        "truncated": truncated,
    }


@router.get("/{doc_id}/export")
def export_document(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    fmt: Annotated[str, Query(alias="format")] = "md",
    template: Annotated[str | None, Query(description="导出模板引用：builtin:<key> 或模板 id")] = None,
) -> StreamingResponse:
    """导出文档正文为 Markdown / Word(.docx) / PDF 文件.

    ``format`` 取 ``md`` / ``docx`` / ``pdf``（兼容 ``markdown`` / ``word`` 别名）；
    ``template``（ADR 0152）作用于 docx / pdf，缺省按「工作区默认模板 → 内置 research（研究报告）」
    解析，``md`` 忽略该参数；工作区成员即可导出，文件夹不可导出。
    """
    _require_member(db, workspace_id, current_user)
    normalized = services.export.normalize_format(fmt)
    if normalized is None:
        raise BadRequestError(f"不支持的导出格式: {fmt}，可选 {'/'.join(services.export.SUPPORTED_FORMATS)}")
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    if doc.is_folder:
        raise BadRequestError("文件夹不支持导出")

    version = services.content.latest_version(db, doc.id)
    content = services.content.load_content(version, doc) if version else ""
    # 站内图片（``![alt](file:<key>)``）在 Word / PDF 导出中嵌入真实文件；
    # 解析器限定在该工作区上传目录内，非法 / 缺失的引用降级为占位文字
    images = services.export.make_image_resolver(settings.UPLOAD_DIR, workspace_id)
    # 数据表引用（``{{table:<id>|view=<vid>}}``）按当前导出用户权限解析为真实表格；
    # 图表定义已在正文内嵌块中（ADR 0052），导出无需再按实例 ID 查库
    tables = services.export.make_table_resolver(db, workspace_id, current_user)
    resolved_template = None
    if normalized != services.export.FORMAT_MARKDOWN:
        try:
            resolved_template = services.export.resolve_export_template(
                db, workspace_id, template, document_ref=doc.export_template_ref
            )
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
    chart_assets: dict[str, bytes] = {}
    if normalized == services.export.FORMAT_MARKDOWN:
        # 归档改写顺序固定：图表块追加静态 SVG → 表格改写 → render_markdown_archive
        # （与 ADR 0045 表格改写同一顺序约定，占位符无残留）
        content, chart_assets = services.charts.inline.rewrite_markdown_chart_blocks(content)
        content = services.export.rewrite_markdown_table_refs(content, tables)
        file_bytes = services.export.render_export(content, normalized, doc.title, images=images)
    else:
        file_bytes = services.export.render_export(
            content, normalized, doc.title, images=images, tables=tables, template=resolved_template
        )

    # Markdown 带站内图片 / 图表资产时打包为 zip（<标题>.md + assets/*），否则维持单文件 .md
    media_type = services.export.FORMAT_CONTENT_TYPES[normalized]
    extension = services.export.FORMAT_EXTENSIONS[normalized]
    if normalized == services.export.FORMAT_MARKDOWN:
        archive = services.export.render_markdown_archive(
            content,
            doc.title,
            images,
            _export_filename(doc.title, "").rstrip("."),
            extra_assets=chart_assets,
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


@router.get("/{doc_id}/asset")
def download_document_asset(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    download: Annotated[bool, Query(description="true = 附件下载；默认内联（预览）")] = False,
) -> Response:
    """读取原件族文档的原件（PDF / Office / 图片，ADR 0025）.

    - 权限与正文同源：工作区成员 + 文档可见性（未发布草稿对非创建者 404）；
    - 默认内联返回（PDF / 图片可被浏览器直接渲染），``?download=true`` 走附件下载；
    - ``asset_file_key`` 不外露，避免绕过本端点直取文件。
    """
    _require_member(db, workspace_id, current_user)
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    if not doc.asset_file_key:
        raise NotFoundError("该文档没有原件")

    from cndb.plugins.files.services import resolve_workspace_file

    path = resolve_workspace_file(workspace_id, doc.asset_file_key)
    if not path.is_file():
        raise NotFoundError("原件不存在或已被清理")

    media_type = doc.asset_mime or "application/octet-stream"
    extension = Path(doc.asset_file_key).suffix
    filename = _export_filename(doc.title, extension.lstrip(".") or "bin")
    disposition = "attachment" if download or media_type == "application/octet-stream" else "inline"
    headers = {
        "Content-Disposition": f"{disposition}; filename=\"document{extension}\"; filename*=UTF-8''{quote(filename)}",
        # 原件同样参与文档权限：禁止被当作可执行页面渲染
        "X-Content-Type-Options": "nosniff",
    }
    if media_type == "image/svg+xml":
        # SVG 可内嵌脚本：加 sandbox 头，直接打开该 URL 时也不执行脚本
        headers["Content-Security-Policy"] = "sandbox"
    return FileResponse(path, media_type=media_type, headers=headers)


def _load_pdf_asset(doc: Document) -> bytes:
    """读取 PDF 原件字节（ADR 0164 派生副本输入，只读）."""
    from cndb.plugins.files.services import resolve_workspace_file

    if not doc.asset_file_key:
        raise NotFoundError("该文档没有原件")
    path = resolve_workspace_file(doc.workspace_id, doc.asset_file_key)
    if not path.is_file():
        raise NotFoundError("原件不存在或已被清理")
    return path.read_bytes()


@router.get("/{doc_id}/asset/orientation")
def document_asset_orientation(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """PDF 原件页面方向信息（ADR 0164）：每页 ``/Rotate`` 与 MediaBox 尺寸.

    - 仅 ``content_type=pdf``；其余 404（与「没有可旋转原件」同文案口径）；
    - 权限与 ``/asset`` 同源：工作区成员 + 文档可见性；
    - 解析失败 422 ``pdf_unreadable``，由前端降级为「只保留手动旋转」。
    """
    from cndb.plugins.documents.services.preview import pdf_rotation

    _require_member(db, workspace_id, current_user)
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    if doc.content_type != "pdf":
        raise NotFoundError("该文档没有可旋转的 PDF 原件")

    try:
        pages = pdf_rotation.read_page_orientations(_load_pdf_asset(doc))
    except pdf_rotation.PdfRotationError as exc:
        raise BadRequestError(str(exc), code="pdf_unreadable", status_code=422) from exc

    rotates = {page.rotate for page in pages}
    aspects = set()
    for page in pages:
        if page.height <= 0:
            aspects.add("mixed")
            continue
        ratio = page.width / page.height
        if ratio >= 1.1:
            aspects.add("landscape")
        elif ratio <= 0.9:
            aspects.add("portrait")
        else:
            aspects.add("square")

    return {
        "page_count": len(pages),
        "uniform_rotate": next(iter(rotates)) if len(rotates) == 1 else None,
        "uniform_aspect": next(iter(aspects)) if len(aspects) == 1 else "mixed",
        "pages": [
            {"rotate": page.rotate, "width": round(page.width, 2), "height": round(page.height, 2)}
            for page in pages[:64]
        ],
    }


@router.get("/{doc_id}/asset/rotated")
def document_asset_rotated(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    rotate: Annotated[int, Query(description="顺时针旋转角度：0 / 90 / 180 / 270")] = 0,
    flip: Annotated[bool, Query(description="是否水平镜像")] = False,
) -> Response:
    """PDF 派生副本（ADR 0164 P0）：旋转 / 水平镜像后返回，不改原件.

    - 仅 ``content_type=pdf``；参数越界 / 解析失败 422；非 PDF / 缺原件 404；
    - 权限与 ``/asset`` 同源；原件字节永不改写（ADR 0164 I1）；
    - 页面既有 ``/Rotate`` 先烘焙进内容，再应用用户方向（ADR 0164 I2）。
    """
    from cndb.plugins.documents.services.preview import pdf_rotation

    if rotate not in pdf_rotation.VALID_ROTATIONS:
        raise BadRequestError("rotate 仅支持 0 / 90 / 180 / 270", code="pdf_rotation_invalid", status_code=422)

    _require_member(db, workspace_id, current_user)
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    if doc.content_type != "pdf":
        raise NotFoundError("该文档没有可旋转的 PDF 原件")

    try:
        result = pdf_rotation.get_derived(
            _load_pdf_asset(doc),
            doc_id=doc.id,
            file_key=doc.asset_file_key or "",
            rotate=rotate,
            flip=flip,
        )
    except pdf_rotation.PdfRotationError as exc:
        raise BadRequestError(str(exc), code="pdf_unreadable", status_code=422) from exc

    return Response(
        content=result,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="document-rotated.pdf"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/{doc_id}/asset/preview")
def preview_document_asset(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """原件在线预览：MHTML（需求 0064）/ Excel / Word（ADR 0087）返回自包含 HTML.

    - 仅 ``content_type ∈ {mhtml, xlsx, word}`` 的原件族文档可用，其余 400；
    - 权限与 ``/asset`` 同源：工作区成员 + 文档可见性；
    - MHTML 复用 ADR 0049 解析链路：根 HTML 原样保留（内联样式保留），命中素材索引的
      ``<img src>`` 内联为 ``data:`` URI，未命中引用保留原样；
    - Excel / Word 复用 ``services/preview/office``（openpyxl / python-docx）渲染为自包含 HTML，
      旧版二进制 ``.xls`` / ``.doc`` 一律 400（保持下载查看）；
    - 响应加 ``Content-Security-Policy: sandbox``：原件来自外部，视为不可信内容，
      即使直接打开该 URL 脚本也不执行。
    """
    _require_member(db, workspace_id, current_user)
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    if doc.content_type not in ("mhtml", "xlsx", "word"):
        raise BadRequestError("该文档类型不支持在线预览")
    if not doc.asset_file_key:
        raise NotFoundError("该文档没有原件")

    from cndb.plugins.files.services import resolve_workspace_file

    path = resolve_workspace_file(workspace_id, doc.asset_file_key)
    if not path.is_file():
        raise NotFoundError("原件不存在或已被清理")

    if doc.content_type == "mhtml":
        from cndb.plugins.documents.services.importers.errors import UnsupportedImport
        from cndb.plugins.documents.services.importers.mhtml import build_preview_html

        try:
            html = build_preview_html(path.read_bytes())
        except UnsupportedImport as exc:
            raise BadRequestError(f"MHTML 原件无法解析：{exc}") from exc
    else:
        from cndb.plugins.documents.services.preview import UnsupportedPreview, build_office_preview

        try:
            html = build_office_preview(doc.content_type, doc.asset_mime, path.read_bytes())
        except UnsupportedPreview as exc:
            raise BadRequestError(f"原件无法在线预览：{exc}") from exc
    return Response(
        content=html,
        media_type="text/html",
        headers={
            "Content-Disposition": 'inline; filename="preview.html"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


class _PdfPreviewBusyError(CndbError):
    """转换队列已满（HTTP 503，带 Retry-After）."""

    status_code = 503
    code = "pdf_preview_busy"
    retry_after = 5


def _pdf_preview_state_error(state: Any) -> None:
    """把服务层判定结果映射为统一业务异常（ADR 0129 §2）."""
    from cndb.plugins.documents.services.preview import pptx_pdf

    if state.status == pptx_pdf.STATUS_DISABLED:
        raise ConflictError("当前部署未启用服务端 PDF 预览", code="pdf_preview_disabled")
    if state.status == pptx_pdf.STATUS_UNSUPPORTED:
        raise ConflictError("该文档类型不支持服务端 PDF 预览", code="pdf_preview_unsupported")
    if state.status == pptx_pdf.STATUS_TOO_LARGE:
        raise CndbError(
            "PPTX 原件超出服务端预览上限，请下载查看",
            code="pdf_preview_too_large",
            status_code=413,
        )
    if state.status == pptx_pdf.STATUS_BUSY:
        raise _PdfPreviewBusyError("预览转换排队已满，请稍后重试")
    raise CndbError(
        "PDF 预览生成失败，请下载查看",
        code="pdf_conversion_failed",
        status_code=422,
    )


def _pdf_preview_pending(state: Any) -> JSONResponse:
    """202：转换排队 / 进行中，不代表失败，客户端按 Retry-After 轮询."""
    from cndb.plugins.documents.services.preview import pptx_pdf

    return JSONResponse(
        status_code=202,
        content={"status": state.status, "retry_after": pptx_pdf.RETRY_AFTER_SECONDS},
        headers={
            "Retry-After": str(pptx_pdf.RETRY_AFTER_SECONDS),
            "Cache-Control": "no-store",
        },
    )


def _pdf_preview_file(
    request: Request,
    doc: Document,
) -> Response:
    """就绪：返回衍生 PDF（支持 ETag / 304，不参与原件权限之外的任何旁路）."""
    from cndb.plugins.documents.services.preview import pptx_pdf

    path = pptx_pdf.derived_pdf_path(doc.workspace_id, doc.asset_file_key or "")
    if not path.is_file():
        raise CndbError("PDF 预览已失效，请重试", code="pdf_conversion_failed", status_code=422)
    etag = f'"pptxpdf-{doc.asset_file_key}-{pptx_pdf.CONVERTER_CACHE_VERSION}"'
    headers = {
        "Content-Disposition": 'inline; filename="preview.pdf"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=3600",
        "ETag": etag,
    }
    if (request.headers.get("if-none-match") or "").strip() == etag:
        return Response(status_code=304, headers=headers)
    return FileResponse(path, media_type="application/pdf", headers=headers)


@router.get("/{doc_id}/asset/pdf")
def get_document_asset_pdf(
    workspace_id: int,
    doc_id: int,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """PPTX 服务端 PDF 预览（ADR 0129）.

    权限与 ``/asset`` 同源；转换默认关闭（未配置 pdf-worker 时 409），
    就绪返回 200 + PDF，排队 / 进行中返回 202，失败返回 422 并保留客户端降级。
    """
    from cndb.plugins.documents.services.preview import pptx_pdf

    _require_member(db, workspace_id, current_user)
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    if doc.content_type != "pptx":
        raise ConflictError("该文档类型不支持服务端 PDF 预览", code="pdf_preview_unsupported")
    if not doc.asset_file_key:
        raise NotFoundError("该文档没有原件")

    state = pptx_pdf.ensure_pptx_pdf(workspace_id, doc_id, db=db)
    if state.status == pptx_pdf.STATUS_READY:
        return _pdf_preview_file(request, doc)
    if state.status in (pptx_pdf.STATUS_QUEUED, pptx_pdf.STATUS_RUNNING):
        return _pdf_preview_pending(state)
    _pdf_preview_state_error(state)
    raise AssertionError("unreachable")  # pragma: no cover - 判定穷尽


@router.post("/{doc_id}/asset/pdf")
def retry_document_asset_pdf(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """手动重试一次 PPTX PDF 转换（幂等）.

    已就绪返回 200 JSON；排队 / 进行中 202；其余错误口径与 GET 一致。
    """
    from cndb.plugins.documents.services.preview import pptx_pdf

    _require_member(db, workspace_id, current_user)
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    if doc.content_type != "pptx":
        raise ConflictError("该文档类型不支持服务端 PDF 预览", code="pdf_preview_unsupported")
    if not doc.asset_file_key:
        raise NotFoundError("该文档没有原件")

    state = pptx_pdf.ensure_pptx_pdf(workspace_id, doc_id, retry=True, db=db)
    if state.status == pptx_pdf.STATUS_READY:
        return JSONResponse(content={"status": state.status}, headers={"Cache-Control": "no-store"})
    if state.status in (pptx_pdf.STATUS_QUEUED, pptx_pdf.STATUS_RUNNING):
        return _pdf_preview_pending(state)
    _pdf_preview_state_error(state)
    raise AssertionError("unreachable")  # pragma: no cover - 判定穷尽


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
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    services.content.require_editor(db, workspace_id, current_user)

    if payload.title is not None:
        doc.title = payload.title
        doc.slug = services.parse.generate_slug(payload.title, doc.id)
    if payload.status is not None:
        # 发布只切换状态、不写入正文：本人仍有未提交草稿时必须先提交 / 丢弃，
        # 否则成员看到的发布版会与编辑中的草稿不一致。
        if (
            payload.status == "published"
            and doc.status != "published"
            and services.drafts.draft_payload(db, doc, current_user) is not None
        ):
            raise ConflictError(
                "存在未提交的个人草稿，请先提交或丢弃草稿后再发布",
                code="uncommitted_draft",
            )
        doc.status = payload.status
    if payload.sort_order is not None:
        doc.sort_order = payload.sort_order
    if "export_template_ref" in payload.model_fields_set:
        # null = 清除绑定、回到工作区默认；文件夹没有导出物（ADR 0177 C6 / 边界 1）
        if doc.is_folder:
            raise BadRequestError("文件夹不支持绑定排版模板")
        try:
            doc.export_template_ref = services.export.validate_export_template_ref(
                db, workspace_id, payload.export_template_ref
            )
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
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
    _audit_document(db, workspace_id, current_user, "document.delete", doc, summary=f"删除文档：{doc.title}")
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
    _audit_document(
        db,
        workspace_id,
        current_user,
        "document.restore",
        doc,
        summary=f"恢复文档：{doc.title}",
        detail={"restored_count": restored_count, "reparented_to_root": reparented},
    )
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
    services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
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
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
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
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)

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

    diff_text, added, removed = unified_diff(_load(base), _load(head))
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
    _audit_document(
        db,
        workspace_id,
        current_user,
        "document.rollback",
        doc,
        summary=f"回滚文档：{doc.title}",
        detail={"target_version": payload.target_version},
    )
    return services.content.serialize_document(db, doc)


# ── 反向链接 ──


@router.get("/links/graph")
def get_link_graph(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """知识图谱聚合（需求 0168）：可见文档为节点、双链为边，30s 缓存（工作区成员）."""
    _require_member(db, workspace_id, current_user)
    return services.content.build_link_graph(db, workspace_id, current_user)


@router.get("/{doc_id}/backlinks")
def get_backlinks(
    workspace_id: int,
    doc_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """反向链接：工作区内正文含 ``[[本文档标题]]`` 的文档列表（含自引用）。"""
    _require_member(db, workspace_id, current_user)
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    hits = services.content.find_backlinks(
        db,
        workspace_id,
        doc.title,
        viewer=current_user,
        is_admin=services.visibility.is_document_admin(db, workspace_id, current_user),
    )
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
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
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
    doc = services.visibility.get_visible_document_or_404(db, workspace_id, doc_id, current_user)
    services.content.require_editor(db, workspace_id, current_user)
    services.content._apply_tags(db, doc, payload.tag_ids, current_user)
    db.commit()
    return services.content.serialize_document(db, doc)


__all__ = ["router"]
