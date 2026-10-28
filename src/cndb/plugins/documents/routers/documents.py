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
import re
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.core.errors import BadRequestError, CndbError, ConflictError, NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents import services
from cndb.plugins.documents.models import Document, DocumentVersion, Tag
from cndb.plugins.documents.schemas import (
    ContentUpdate,
    DocumentAiActionRequest,
    DocumentBatchRequest,
    DocumentCreate,
    DocumentDraftSave,
    DocumentSubmit,
    DocumentUpdate,
    LinkRepairRequest,
    RollbackRequest,
    TagIdsRequest,
)
from cndb.plugins.llm.services import gateway as llm_gateway
from cndb.plugins.llm.services.errors import LlmError
from cndb.plugins.llm.services.gateway import LlmContext
from cndb.plugins.workspaces.permissions import get_member_role, raise_permission_denied

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
    if get_member_role(user, ws, db) is None:
        # ADR 0047：403 文案带角色与拥有者指引（唯一出口，非成员走「申请加入」分支）
        raise_permission_denied(db, ws, user)


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
    """全量文档树（工作区成员，含文件夹层级）.

    进程内短 TTL 缓存（10s，按用户隔离：置顶是个人偏好）；文档写路径提交后主动失效，TTL 兜底。
    """
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
) -> StreamingResponse:
    """导出文档正文为 Markdown / Word(.docx) / PDF 文件.

    ``format`` 取 ``md`` / ``docx`` / ``pdf``（兼容 ``markdown`` / ``word`` 别名）；
    工作区成员即可导出（与文档读取权限一致），文件夹不可导出。
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
    chart_assets: dict[str, bytes] = {}
    if normalized == services.export.FORMAT_MARKDOWN:
        # 归档改写顺序固定：图表块追加静态 SVG → 表格改写 → render_markdown_archive
        # （与 ADR 0045 表格改写同一顺序约定，占位符无残留）
        content, chart_assets = services.charts.inline.rewrite_markdown_chart_blocks(content)
        content = services.export.rewrite_markdown_table_refs(content, tables)
        file_bytes = services.export.render_export(content, normalized, doc.title, images=images)
    else:
        file_bytes = services.export.render_export(content, normalized, doc.title, images=images, tables=tables)

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
