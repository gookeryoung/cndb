"""文档写入：创建 / 内容更新 / 版本回滚 / 移动校验（ADR 0180 D1）."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cndb.core.errors import ConflictError, NotFoundError
from cndb.plugins.documents.models import (
    CHANGE_TYPE_MANUAL,
    CHANGE_TYPE_ROLLBACK,
    CONTENT_TYPE_FOLDER,
    CONTENT_TYPE_MARKDOWN,
    Document,
    DocumentVersion,
)
from cndb.plugins.documents.services import parse

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User

from cndb.plugins.documents.services import content as _pkg

from . import access, storage

# 固定全名而非 __name__：拆包后日志分类必须仍是 …services.content（ADR 0180 D7）
logger = logging.getLogger("cndb.plugins.documents.services.content")


def create_document(
    db: Session,
    workspace_id: int,
    user: User,
    *,
    title: str,
    content: str = "",
    is_folder: bool = False,
    parent_id: int | None = None,
    status: str = "draft",
    tag_ids: list[int] | None = None,
    sort_order: int = 0,
    export_template_ref: str | None = None,
    change_type: str = CHANGE_TYPE_MANUAL,
    content_type: str = CONTENT_TYPE_MARKDOWN,
    asset_file_key: str | None = None,
    asset_mime: str = "",
    content_size: int | None = None,
) -> Document:
    """创建文档（或文件夹），自动解析元数据并创建 v1 版本.

    ``asset_file_key`` 非空表示原件族文档（PDF / Office / 图片，ADR 0025）：
    跳过 Markdown 元数据解析，正文为空版本，不建 TOC / 摘要，只按标题进检索。
    """
    if parent_id is not None:
        parent = access.get_document_or_404(db, workspace_id, parent_id)
        if not parent.is_folder:
            raise ConflictError("父节点必须是文件夹")

    asset = bool(asset_file_key)
    doc = Document(
        workspace_id=workspace_id,
        parent_id=parent_id,
        title=title,
        content_type=CONTENT_TYPE_FOLDER if is_folder else (content_type if asset else CONTENT_TYPE_MARKDOWN),
        is_folder=is_folder,
        status=status,
        sort_order=sort_order,
        # 文件夹没有导出物：忽略绑定（ADR 0177 边界 1）
        export_template_ref=None if is_folder else export_template_ref,
        asset_file_key=asset_file_key,
        asset_mime=asset_mime if asset else "",
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    if not is_folder and not asset:
        meta, _ = parse.parse_front_matter(content)
        doc.author = meta.get("author", "")[:200] or parse.extract_author(content)
        doc.summary = parse.extract_summary(content)
        doc.toc_json = parse.extract_toc(content)
    db.add(doc)
    db.flush()  # 拿 id

    doc.slug = parse.generate_slug(title, doc.id)

    if tag_ids:
        _pkg._apply_tags(db, doc, tag_ids, user)

    if not is_folder:
        raw_size = content_size if asset and content_size is not None else len(content.encode("utf-8"))
        stored = "" if asset else storage.store_content_bytes(doc, 1, content, raw_size)
        version = DocumentVersion(
            document_id=doc.id,
            version_number=1,
            content=stored,
            content_size=raw_size,
            content_hash=parse.content_hash(content),
            change_summary="上传文件" if asset else "创建文档",
            change_type=change_type,
            created_by_id=user.id,
        )
        db.add(version)
        doc.content_size = raw_size
        _pkg.sync_fts(db, doc, content)

    db.commit()
    db.refresh(doc)
    # 新节点/新标题可能立刻被 [[标题]] 引用：图谱缓存必须失效（需求 0182 C1）
    _pkg.invalidate_link_graph_cache(workspace_id)
    return doc


def replace_document_asset(
    db: Session,
    workspace_id: int,
    doc_id: int,
    user: User,
    *,
    asset_file_key: str,
    asset_mime: str,
    content_size: int,
) -> Document:
    """替换原件族文档的原件（导入覆盖策略用）：不产生新版本，正文保持为空.

    旧原件由调用方在事务提交后删除（DB 先落新值，避免「文件删了事务回滚」）。
    """
    doc = access.get_document_or_404(db, workspace_id, doc_id)
    access.require_editor(db, workspace_id, user)
    if doc.is_folder:
        raise ConflictError("文件夹没有原件")
    if not doc.asset_file_key:
        raise ConflictError("目标文档不是原件类型，无法覆盖", code="doc_not_asset")

    doc.asset_file_key = asset_file_key
    doc.asset_mime = asset_mime
    doc.content_size = content_size
    doc.updated_by_id = user.id
    db.commit()
    db.refresh(doc)
    return doc


def ensure_text_document(doc: Document) -> None:
    """原件族文档不接受 Markdown 写操作（ADR 0025 I2：原件即事实）.

    保存正文 / 草稿 / 提交 / 回滚都经由此守卫；前端对这类文档隐藏编辑入口。
    """
    if doc.asset_file_key:
        raise ConflictError("该文档是上传的原件（只读），不支持编辑正文；可下载后另行处理", code="doc_read_only")


def update_content(
    db: Session,
    workspace_id: int,
    doc_id: int,
    user: User,
    *,
    content: str,
    change_summary: str = "",
    base_updated_at: str | None = None,
    change_type: str = CHANGE_TYPE_MANUAL,
) -> Document:
    """乐观锁更新内容：创建新版本 + 刷新元数据 + 同步 FTS.

    Args:
        base_updated_at: 客户端持有的 updated_at ISO 字符串；None 表示跳过冲突检测。
    """
    doc = access.get_document_or_404(db, workspace_id, doc_id)
    access.require_editor(db, workspace_id, user)

    if doc.is_folder:
        raise ConflictError("文件夹没有内容")
    ensure_text_document(doc)

    if base_updated_at is not None and _pkg._normalize_ts(base_updated_at) != _pkg._normalize_ts(
        doc.updated_at.isoformat() if doc.updated_at else ""
    ):
        raise ConflictError("文档已被他人修改，请刷新获取最新版本后重试（您的本地修改未丢失）")

    v = _pkg.latest_version(db, doc.id)
    next_num = (v.version_number + 1) if v else 1
    raw_size = len(content.encode("utf-8"))
    content_hash = parse.content_hash(content)

    # 内容未变化：不创建新版本
    if v and v.content_hash == content_hash:
        return doc

    stored = storage.store_content_bytes(doc, next_num, content, raw_size)

    version = DocumentVersion(
        document_id=doc.id,
        version_number=next_num,
        content=stored,
        content_size=raw_size,
        content_hash=content_hash,
        change_summary=change_summary[:500],
        change_type=change_type,
        created_by_id=user.id,
    )
    db.add(version)

    doc.content_size = raw_size
    doc.updated_by_id = user.id
    meta, _ = parse.parse_front_matter(content)
    doc.author = meta.get("author", "")[:200] or parse.extract_author(content)
    doc.summary = parse.extract_summary(content)
    doc.toc_json = parse.extract_toc(content)

    _pkg.sync_fts(db, doc, content)
    try:
        db.commit()
    except IntegrityError as exc:
        # 并发保存：两个请求同时取到同一 next_num，唯一约束 (document_id, version_number)
        # 只放行一个。回滚并把竞争失败方转成 409，而非裸穿 500。
        db.rollback()
        raise ConflictError(
            "文档版本写入冲突（可能有并发保存），请刷新获取最新版本后重试",
            code="doc_version_conflict",
        ) from exc
    db.refresh(doc)
    # 新版本落地：同文档其它待审修改申请的内容基准即过期
    _mark_open_change_requests_stale(db, doc.id)
    # 正文写入后统一分发 document.saved：直编保存 / 草稿提交 / 修改申请合并 / 回滚 / 链接修复
    # 都走本函数，避免只在某个路由里分发导致事件漏触发（ADR 0076 P1）。
    _dispatch_document_saved(db, doc)
    # 正文变了，边就变了（需求 0182 C1）
    _pkg.invalidate_link_graph_cache(workspace_id)
    return doc


def _dispatch_document_saved(db: Session, doc: Document) -> None:
    """正文落库后触发 ``document.saved`` 流水线（尽力而为，失败不影响保存）."""
    try:
        from cndb.plugins.pipeline.services.triggers import (
            EVENT_DOCUMENT_SAVED,
            dispatch_event,
        )

        dispatch_event(
            db,
            EVENT_DOCUMENT_SAVED,
            workspace_id=doc.workspace_id,
            payload={"document_id": doc.id, "title": doc.title},
        )
    except Exception:
        logger.warning("文档保存事件分发失败，跳过", exc_info=True)


def _mark_open_change_requests_stale(db: Session, document_id: int) -> None:
    """把同文档待审修改申请标记为基准过期（延迟导入避免与 change_requests 循环依赖）."""
    from cndb.plugins.documents.services.change_requests import mark_open_requests_stale

    mark_open_requests_stale(db, document_id)


def rollback_version(db: Session, workspace_id: int, doc_id: int, user: User, target_version: int) -> Document:
    """回滚到指定版本：内容恢复并以 rollback 类型创建新版本（历史不可变）."""
    doc = access.get_document_or_404(db, workspace_id, doc_id)
    access.require_editor(db, workspace_id, user)

    target = db.execute(
        select(DocumentVersion).where(
            DocumentVersion.document_id == doc_id,
            DocumentVersion.version_number == target_version,
        )
    ).scalar_one_or_none()
    if target is None:
        raise NotFoundError(f"版本 v{target_version} 不存在")

    return update_content(
        db,
        workspace_id,
        doc_id,
        user,
        content=_pkg.load_content(target, doc),
        change_summary=f"回滚到 v{target_version}",
        base_updated_at=None,
        change_type=CHANGE_TYPE_ROLLBACK,
    )


def move_target_reason(db: Session, workspace_id: int, doc: Document, parent_id: int | None) -> str | None:
    """判断能否把 doc 移动到 parent_id 下；不可移动时返回原因（None = 可以）.

    约定 ``0`` 与 ``None`` 均表示根目录。批量移动需要**逐项**报告失败原因而不是整体中断，
    故与 PATCH 端点共用同一个校验函数。
    """
    if parent_id in (None, 0):
        return None
    if parent_id == doc.id:
        return "不能将文档移动到自身"
    parent = db.execute(
        select(Document).where(
            Document.id == parent_id,
            Document.workspace_id == workspace_id,
            Document.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if parent is None:
        return "目标文件夹不存在"
    if not parent.is_folder:
        return "父节点必须是文件夹"
    # 环检测：目标节点的祖先链中若出现自身，则移动后会形成孤岛
    ancestor: Document | None = parent
    visited: set[int] = set()
    while ancestor is not None and ancestor.id not in visited:
        if ancestor.id == doc.id:
            return "不能将文档移动到自身子孙节点下"
        visited.add(ancestor.id)
        ancestor = db.get(Document, ancestor.parent_id) if ancestor.parent_id is not None else None
    return None
