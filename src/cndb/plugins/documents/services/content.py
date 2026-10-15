"""文档内容服务：CRUD / 版本快照 / 乐观锁更新 / 分级存储.

存储策略（按内容大小自动分级）：
- ≤50KB：直接存 document_versions.content
- >2MB：gzip 落文件系统 data/docs/{doc_id}/v{n}.md.gz，DB 存路径
- 之间：zlib 压缩后存 DB（content 字段存 base64 压缩串，前缀 ``gz:`` 标记）

并发控制：乐观锁 — 更新时 WHERE updated_at 匹配客户端持有版本，失配抛 ConflictError。
"""

from __future__ import annotations

import base64
import datetime as dt
import gzip
import logging
import shutil
import zlib
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from cndb.core.config import settings
from cndb.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from cndb.plugins.documents.models import (
    CHANGE_TYPE_MANUAL,
    CHANGE_TYPE_ROLLBACK,
    CONTENT_TYPE_FOLDER,
    EXTERNAL_MIN_SIZE,
    INLINE_MAX_SIZE,
    Document,
    DocumentChangeRequest,
    DocumentIssue,
    DocumentIssueComment,
    DocumentIssueEvent,
    DocumentPermission,
    DocumentPin,
    DocumentShare,
    DocumentTag,
    DocumentVersion,
    Tag,
)
from cndb.plugins.documents.services import parse
from cndb.plugins.workspaces.models import WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_COMPRESSED_PREFIX = "gz:"

# 外存根目录：跟随数据库目录（data/docs）
_DOCS_DIR = (
    Path(settings.DATABASE_URL.replace("sqlite:///", "")).parent / "docs"
    if (settings.DATABASE_URL.startswith("sqlite:///"))
    else Path("data/docs")
)


def _external_dir(doc_id: int, root: Path | None = None) -> Path:
    return (root if root is not None else _DOCS_DIR) / str(doc_id)


def _external_version_path(doc_id: int, version_number: int, root: Path | None = None) -> Path:
    """外存内容文件路径：``data/docs/{doc_id}/v{n}.md.gz``.

    文件名自描述版本号，是外存内容的唯一权威定位方式；``Document.content_path``
    只是"最新外存版本"的兼容冗余字段，多版本时会被后来者覆盖，**不可**用于读取
    历史版本（否则所有历史版本都会串到最新内容）。

    Args:
        root: 自定义外存根目录（体检/回收集成测试用；默认跟随数据库目录）。
    """
    return _external_dir(doc_id, root) / f"v{version_number}.md.gz"


# ── 读取辅助 ──


def get_document_or_404(db: Session, workspace_id: int, doc_id: int) -> Document:
    """取工作区下未删除文档，不存在抛 NotFoundError."""
    doc = db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.workspace_id == workspace_id,
            Document.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if doc is None:
        raise NotFoundError("文档不存在")
    return doc


def get_deleted_document_or_404(db: Session, workspace_id: int, doc_id: int) -> Document:
    """取工作区下**已删除**文档（回收站操作专用），不存在抛 NotFoundError."""
    doc = db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.workspace_id == workspace_id,
            Document.is_deleted == True,  # noqa: E712
        )
    ).scalar_one_or_none()
    if doc is None:
        raise NotFoundError("回收站中不存在该文档")
    return doc


def get_document_any_state_or_404(db: Session, workspace_id: int, doc_id: int) -> Document:
    """取工作区下文档（不过滤删除态），不存在抛 NotFoundError.

    供"先判断删除态再决定语义"的流程使用（如彻底删除对未删除文档返回 409）。
    """
    doc = db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.workspace_id == workspace_id,
        )
    ).scalar_one_or_none()
    if doc is None:
        raise NotFoundError("文档不存在")
    return doc


def require_editor(db: Session, workspace_id: int, user: User) -> WorkspaceRole:
    """校验用户是工作区 editor/owner（viewer 或非成员拒绝写操作）."""
    role = get_member_role(user, _get_workspace(db, workspace_id), db)
    if role is None or role == WorkspaceRole.VIEWER:
        raise PermissionDeniedError("仅编辑者及以上角色可执行此操作")
    return role


def _get_workspace(db: Session, workspace_id: int):
    from cndb.plugins.workspaces.models import Workspace

    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("工作区不存在")
    return ws


def load_content(version: DocumentVersion | None, doc: Document) -> str:
    """从版本记录加载内容，自动识别压缩/外存策略.

    外存版本按 ``data/docs/{doc_id}/v{version_number}.md.gz`` 定位（文件名自描述
    版本号）；内容缺失/损坏时降级为空串并记 warning —— 读取路径（详情 / 版本 /
    diff / 检索 / 分享）不应因单个坏文件整体 500。
    """
    if version is None:
        return ""
    raw = version.content or ""
    if raw == "" and version.content_size > 0:
        return _read_external_content(doc, version)
    if raw.startswith(_COMPRESSED_PREFIX):
        return _decode_inline_compressed(raw)
    return raw


def _read_external_content(doc: Document, version: DocumentVersion) -> str:
    """读取外存版本内容，失败降级为空串."""
    path = _external_version_path(doc.id, version.version_number)
    if not path.is_file() and doc.content_path:
        # 兼容历史非标准落盘位置：仅当冗余路径确为当前版本的文件名时才采用，
        # 避免"多版本共用 doc.content_path"把历史版本读成最新内容。
        legacy = Path(doc.content_path)
        if legacy.name == path.name and legacy.is_file():
            path = legacy
    if not path.is_file():
        logger.warning("外存内容文件缺失: %s（doc=%s v%s）", path, doc.id, version.version_number)
        return ""
    try:
        return gzip.decompress(path.read_bytes()).decode("utf-8")
    except (OSError, EOFError, ValueError, zlib.error) as exc:
        logger.warning("外存内容文件损坏，已降级为空内容: %s（%s）", path, exc)
        return ""


def _decode_inline_compressed(raw: str) -> str:
    """解码内联 gzip+base64 内容，失败降级为空串."""
    try:
        return gzip.decompress(base64.b64decode(raw[len(_COMPRESSED_PREFIX) :])).decode("utf-8")
    except (OSError, EOFError, ValueError, zlib.error) as exc:
        logger.warning("内联压缩内容损坏，已降级为空内容: %s", exc)
        return ""


def latest_version(db: Session, doc_id: int) -> DocumentVersion | None:
    """最新版本记录（version_number 最大）。"""
    return db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == doc_id)
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def version_count(db: Session, doc_id: int) -> int:
    return int(db.execute(select(func.count()).where(DocumentVersion.document_id == doc_id)).scalar_one())


# ── 写入 ──


def _store_content_bytes(doc: Document, next_num: int, content: str, raw_size: int) -> str:
    """按分级存储策略落盘，返回 DB content 字段应存的值.

    - ≤50KB：原文内联
    - ≤2MB：gz base64 内联（``gz:`` 前缀）
    - >2MB：gzip 写 ``data/docs/{doc_id}/v{n}.md.gz``，返回 ""；同时刷新
      ``doc.content_path``（仅作"最新外存版本"冗余标记，读取以版本号定位为准）
    """
    if raw_size <= INLINE_MAX_SIZE:
        return content
    compressed = gzip.compress(content.encode("utf-8"), compresslevel=6)
    if raw_size > EXTERNAL_MIN_SIZE:
        path = _external_version_path(doc.id, next_num)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(compressed)
        doc.content_path = str(path)
        return ""
    return _COMPRESSED_PREFIX + base64.b64encode(compressed).decode("ascii")


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
    change_type: str = CHANGE_TYPE_MANUAL,
) -> Document:
    """创建文档（或文件夹），自动解析元数据并创建 v1 版本."""
    if parent_id is not None:
        parent = get_document_or_404(db, workspace_id, parent_id)
        if not parent.is_folder:
            raise ConflictError("父节点必须是文件夹")

    doc = Document(
        workspace_id=workspace_id,
        parent_id=parent_id,
        title=title,
        content_type=CONTENT_TYPE_FOLDER if is_folder else "markdown",
        is_folder=is_folder,
        status=status,
        sort_order=sort_order,
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    if not is_folder:
        meta, _ = parse.parse_front_matter(content)
        doc.author = meta.get("author", "")[:200] or parse.extract_author(content)
        doc.summary = parse.extract_summary(content)
        doc.toc_json = parse.extract_toc(content)
    db.add(doc)
    db.flush()  # 拿 id

    doc.slug = parse.generate_slug(title, doc.id)

    if tag_ids:
        _apply_tags(db, doc, tag_ids, user)

    if not is_folder:
        raw_size = len(content.encode("utf-8"))
        stored = _store_content_bytes(doc, 1, content, raw_size)
        version = DocumentVersion(
            document_id=doc.id,
            version_number=1,
            content=stored,
            content_size=raw_size,
            content_hash=parse.content_hash(content),
            change_summary="创建文档",
            change_type=change_type,
            created_by_id=user.id,
        )
        db.add(version)
        doc.content_size = raw_size
        _sync_fts(db, doc, content)

    db.commit()
    db.refresh(doc)
    return doc


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
    doc = get_document_or_404(db, workspace_id, doc_id)
    require_editor(db, workspace_id, user)

    if doc.is_folder:
        raise ConflictError("文件夹没有内容")

    if base_updated_at is not None and _normalize_ts(base_updated_at) != _normalize_ts(
        doc.updated_at.isoformat() if doc.updated_at else ""
    ):
        raise ConflictError("文档已被他人修改，请刷新获取最新版本后重试（您的本地修改未丢失）")

    v = latest_version(db, doc.id)
    next_num = (v.version_number + 1) if v else 1
    raw_size = len(content.encode("utf-8"))
    content_hash = parse.content_hash(content)

    # 内容未变化：不创建新版本
    if v and v.content_hash == content_hash:
        return doc

    stored = _store_content_bytes(doc, next_num, content, raw_size)

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

    _sync_fts(db, doc, content)
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
    return doc


def _mark_open_change_requests_stale(db: Session, document_id: int) -> None:
    """把同文档待审修改申请标记为基准过期（延迟导入避免与 change_requests 循环依赖）."""
    from cndb.plugins.documents.services.change_requests import mark_open_requests_stale

    mark_open_requests_stale(db, document_id)


def rollback_version(db: Session, workspace_id: int, doc_id: int, user: User, target_version: int) -> Document:
    """回滚到指定版本：内容恢复并以 rollback 类型创建新版本（历史不可变）."""
    doc = get_document_or_404(db, workspace_id, doc_id)
    require_editor(db, workspace_id, user)

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
        content=load_content(target, doc),
        change_summary=f"回滚到 v{target_version}",
        base_updated_at=None,
        change_type=CHANGE_TYPE_ROLLBACK,
    )  # type: ignore[return-value]


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


def soft_delete_documents(db: Session, workspace_id: int, docs: list[Document], user: User) -> int:
    """批量软删除（同一删除时间戳，最后统一刷新标签计数）；返回处理的根节点数."""
    require_editor(db, workspace_id, user)
    deleted_at = dt.datetime.now(dt.UTC)
    count = 0
    for doc in docs:
        if doc.is_deleted:
            continue
        _mark_deleted_subtree(db, doc, user, deleted_at)
        count += 1
    if count:
        _refresh_tag_counts(db, workspace_id)
    db.commit()
    return count


def soft_delete_document(db: Session, workspace_id: int, doc_id: int, user: User) -> Document:
    """软删除文档（文件夹级联整棵子树，同一删除批次；刷新标签计数）."""
    doc = get_document_or_404(db, workspace_id, doc_id)
    require_editor(db, workspace_id, user)

    deleted_at = dt.datetime.now(dt.UTC)
    _mark_deleted_subtree(db, doc, user, deleted_at)
    _refresh_tag_counts(db, workspace_id)
    db.commit()
    db.refresh(doc)
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
        _sync_fts_delete(db, node.id)

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


# ── 回收站：列表 / 恢复 / 彻底删除 ──


def list_deleted_documents(
    db: Session, workspace_id: int, *, limit: int = 50, offset: int = 0
) -> tuple[list[Document], int]:
    """回收站列表（按删除时间倒序；迁移前删除的 deleted_at 为空排最后）."""
    filters = [
        Document.workspace_id == workspace_id,
        Document.is_deleted == True,  # noqa: E712
    ]
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
    doc = get_deleted_document_or_404(db, workspace_id, doc_id)
    require_editor(db, workspace_id, user)

    restored = _restore_subtree(db, doc, batch=doc.deleted_at)
    reparented = False
    if doc.parent_id is not None:
        parent = db.get(Document, doc.parent_id)
        if parent is None or parent.is_deleted:
            doc.parent_id = None
            reparented = True
    doc.updated_by_id = user.id
    _refresh_tag_counts(db, workspace_id)
    db.commit()
    db.refresh(doc)
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
        _sync_fts(db, node, load_content(latest_version(db, node.id), node))

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
    - 一并清理版本 / 标签关联 / 分享 / 权限 / FTS 索引与外存内容目录。
    """
    doc = get_document_any_state_or_404(db, workspace_id, doc_id)
    require_editor(db, workspace_id, user)
    if not doc.is_deleted:
        raise ConflictError("文档尚未删除，请先移入回收站再彻底删除", code="doc_not_deleted")

    targets: list[Document] = []
    detached = _collect_purge_targets(db, doc, targets, visited=set())
    ids = [t.id for t in targets]

    db.execute(delete(DocumentVersion).where(DocumentVersion.document_id.in_(ids)))
    db.execute(delete(DocumentTag).where(DocumentTag.document_id.in_(ids)))
    db.execute(delete(DocumentPermission).where(DocumentPermission.document_id.in_(ids)))
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
        _sync_fts_delete(db, target.id)
    db.execute(delete(Document).where(Document.id.in_(ids)))
    _refresh_tag_counts(db, workspace_id)
    db.commit()

    # 外存文件在事务提交后删除：DB 侧已作废，避免"文件已删但事务回滚"
    files_removed = 0
    for doc_id_ in ids:
        external = _external_dir(doc_id_)
        if external.is_dir():
            shutil.rmtree(external, ignore_errors=True)
            files_removed += 1
    return {"purged_count": len(ids), "files_removed": files_removed, "detached": detached}


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


# ── 每日笔记 / 反向链接 ──

DAILY_NOTE_TITLE_FMT = "%Y-%m-%d"


def get_or_create_daily_note(
    db: Session, workspace_id: int, user: User, *, day: dt.date | None = None
) -> tuple[Document, bool]:
    """幂等获取/创建每日笔记：标题约定为日期字符串 ``YYYY-MM-DD``.

    当日笔记已存在（未删除的非文件夹文档）时直接返回（created=False），
    否则按模板创建新文档（created=True，需 editor+ 权限）。
    """
    date = day or dt.date.today()
    title = date.strftime(DAILY_NOTE_TITLE_FMT)
    existing = (
        db.execute(
            select(Document)
            .where(
                Document.workspace_id == workspace_id,
                Document.is_deleted == False,  # noqa: E712
                Document.is_folder == False,  # noqa: E712
                Document.title == title,
            )
            .order_by(Document.created_at.desc(), Document.id.desc())
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return existing, False
    require_editor(db, workspace_id, user)
    doc = create_document(db, workspace_id, user, title=title, content=f"# {title}\n\n")
    return doc, True


def find_backlinks(db: Session, workspace_id: int, title: str) -> list[Document]:
    """反向链接扫描：返回工作区内正文含 ``[[title]]`` 的未删除文档列表.

    扫描源为非文件夹文档（文件夹无正文）；目标标题可为文件夹（被提及即计入）；
    含自引用（文档引用自身标题时也出现在结果中）。

    单次查询取各文档最新版本（``MAX(version_number)`` 分组子查询），
    避免历史上"逐文档查最新版本"的 N+1。
    """
    latest = (
        select(
            DocumentVersion.document_id.label("document_id"),
            func.max(DocumentVersion.version_number).label("version_number"),
        )
        .group_by(DocumentVersion.document_id)
        .subquery()
    )
    rows = db.execute(
        select(Document, DocumentVersion)
        .join(latest, latest.c.document_id == Document.id)
        .join(
            DocumentVersion,
            (DocumentVersion.document_id == latest.c.document_id)
            & (DocumentVersion.version_number == latest.c.version_number),
        )
        .where(
            Document.workspace_id == workspace_id,
            Document.is_deleted == False,  # noqa: E712
            Document.is_folder == False,  # noqa: E712
        )
        .order_by(Document.sort_order, Document.id)
    ).all()
    target = f"[[{title}]]"
    return [doc for doc, version in rows if target in load_content(version, doc)]


def resolve_outgoing_links(db: Session, workspace_id: int, doc: Document) -> list[dict[str, Any]]:
    """解析文档正文出链 ``[[标题]]``：返回标题、命中文档 ID 与是否存在（断链）.

    代码围栏内的 ``[[...]]`` 不计入（见 ``parse.extract_wikilinks``）；
    同名文档取最早创建的一个；引用的目标可为文件夹。
    """
    version = latest_version(db, doc.id)
    titles = parse.extract_wikilinks(load_content(version, doc))
    if not titles:
        return []
    rows = db.execute(
        select(Document.id, Document.title)
        .where(
            Document.workspace_id == workspace_id,
            Document.is_deleted == False,  # noqa: E712
            Document.title.in_(titles),
        )
        .order_by(Document.id)
    ).all()
    index: dict[str, int] = {}
    for doc_id, title in rows:
        index.setdefault(title, doc_id)
    return [{"title": t, "document_id": index.get(t), "exists": t in index, "broken": t not in index} for t in titles]


def repair_wikilinks(
    db: Session,
    workspace_id: int,
    doc_id: int,
    user: User,
    repairs: list[Any],
) -> dict[str, Any]:
    """把正文中的断链 ``[[旧标题]]`` 改指为现存文档（创建新版本，可回溯）.

    Args:
        repairs: 元素含 ``title``（正文中原样出现的旧标题）与 ``target_document_id``
            （同一工作区内未删除的目标文档；可为文件夹）。

    语义：
    - 目标必须属于同一工作区且未删除，否则 404；
    - 旧标题在正文中不存在、或目标标题与旧标题相同 → 该条跳过；
    - 全部条目都未产生替换时抛 409，避免写入无意义的新版本；
    - 链接修复走 ``update_content``，因此同样保留完整版本历史。
    """
    doc = get_document_or_404(db, workspace_id, doc_id)
    require_editor(db, workspace_id, user)
    if doc.is_folder:
        raise ConflictError("文件夹没有正文，无法修复链接")

    content = load_content(latest_version(db, doc.id), doc)
    applied: list[dict[str, Any]] = []
    replaced = 0
    for item in repairs:
        title = str(item.title)
        target = get_document_or_404(db, workspace_id, item.target_document_id)
        old = f"[[{title}]]"
        new = f"[[{target.title}]]"
        count = content.count(old)
        if count == 0 or old == new:
            continue
        content = content.replace(old, new)
        replaced += count
        applied.append({"title": title, "new_title": target.title, "document_id": target.id, "count": count})

    if not applied:
        raise ConflictError(
            "未找到可修复的链接（正文中没有该标题，或目标标题与原标题相同）",
            code="no_link_repaired",
        )

    updated = update_content(
        db,
        workspace_id,
        doc_id,
        user,
        content=content,
        change_summary=f"修复文档链接（{replaced} 处）",
        base_updated_at=None,
    )
    latest = latest_version(db, doc_id)
    return {
        "document_id": doc_id,
        "version_number": latest.version_number if latest else 0,
        "repaired": applied,
        "replaced": replaced,
        "document": serialize_document(db, updated),
    }


# ── 标签辅助 ──


def _apply_tags(db: Session, doc: Document, tag_ids: list[int], user: User) -> None:
    from cndb.plugins.documents.models import DocumentTag

    valid_tags = (
        db.execute(select(Tag).where(Tag.workspace_id == doc.workspace_id, Tag.id.in_(tag_ids))).scalars().all()
    )
    valid_ids = {t.id for t in valid_tags}
    invalid = set(tag_ids) - valid_ids
    if invalid:
        raise NotFoundError(f"标签不存在: {sorted(invalid)}")

    existing = {
        row.tag_id for row in db.execute(select(DocumentTag.tag_id).where(DocumentTag.document_id == doc.id)).all()
    }
    for tid in valid_ids:
        if tid not in existing:
            db.add(DocumentTag(document_id=doc.id, tag_id=tid, tagged_by_id=user.id))
    for tid in existing - valid_ids:
        row = db.get(DocumentTag, {"document_id": doc.id, "tag_id": tid})
        if row:
            db.delete(row)
    _refresh_tag_counts(db, doc.workspace_id)


def _refresh_tag_counts(db: Session, workspace_id: int) -> None:
    from cndb.plugins.documents.models import DocumentTag

    db.flush()  # autoflush=False 场景下确保待插入的关联行对计数查询可见
    rows = db.execute(
        select(DocumentTag.tag_id, func.count())
        .join(Document, Document.id == DocumentTag.document_id)
        .where(Document.workspace_id == workspace_id, Document.is_deleted == False)  # noqa: E712
        .group_by(DocumentTag.tag_id)
    ).all()
    counts = {row[0]: row[1] for row in rows}
    tags = db.execute(select(Tag).where(Tag.workspace_id == workspace_id)).scalars().all()
    for t in tags:
        t.doc_count = counts.get(t.id, 0)


# ── FTS5 同步 ──


def _sync_fts(db: Session, doc: Document, content: str) -> None:
    """将文档同步到 FTS5 索引（content 列截断到 64KB 防索引膨胀）.

    FTS5 虚拟表不支持标准 UPSERT，使用 INSERT OR REPLACE（自动删旧插新）。
    """
    from cndb.plugins.documents.services.search import ensure_fts_schema

    ensure_fts_schema(db)
    db.execute(
        _fts_upsert_sql(),
        {
            "doc_id": doc.id,
            "title": doc.title,
            "content": content[:65536],
            "summary": doc.summary[:2000],
            "author": doc.author,
        },
    )


def _fts_upsert_sql():
    from sqlalchemy import text

    return text(
        """
        INSERT OR REPLACE INTO documents_fts(rowid, title, content, summary, author)
        VALUES (:doc_id, :title, :content, :summary, :author)
        """
    )


def _sync_fts_delete(db: Session, doc_id: int) -> None:
    """从 FTS5 索引移除文档：内容清空（FTS5 delete 命令需旧值，清空更简单可靠）."""
    db.execute(_fts_upsert_sql(), {"doc_id": doc_id, "title": "", "content": "", "summary": "", "author": ""})


def _normalize_ts(ts: str) -> str:
    """时间戳宽松归一化（去时区/毫秒差异，仅保留秒级）。"""
    ts = ts.strip().replace("T", " ").rstrip("Z")
    if "+" in ts:
        ts = ts.split("+")[0]
    return ts[:19]


def serialize_document(db: Session, doc: Document, *, pinned: bool = False) -> dict[str, Any]:
    """单文档 → 响应字典（详情/写操作回包用）。"""
    tag_ids = [
        row.tag_id for row in db.execute(select(DocumentTag.tag_id).where(DocumentTag.document_id == doc.id)).all()
    ]
    total = 0 if doc.is_folder else version_count(db, doc.id)
    return _serialize_document(doc, version_total=total, tag_ids=tag_ids, pinned=pinned)


def pinned_document_ids(db: Session, workspace_id: int, user_id: int) -> set[int]:
    """当前用户在该工作区的置顶文档 id 集合（个人偏好，一次查询）."""
    rows = db.execute(
        select(DocumentPin.document_id)
        .join(Document, Document.id == DocumentPin.document_id)
        .where(Document.workspace_id == workspace_id, DocumentPin.user_id == user_id)
    ).all()
    return {int(row[0]) for row in rows}


def sort_pinned_first(docs: list[Document], pinned_ids: set[int]) -> list[Document]:
    """置顶文档排在前面；两组内部保持原有顺序（`sorted` 稳定）."""
    if not pinned_ids:
        return docs
    return sorted(docs, key=lambda d: 0 if d.id in pinned_ids else 1)


def set_document_pin(db: Session, doc: Document, user_id: int, pinned: bool) -> bool:
    """设置 / 取消文档置顶（幂等），返回最终状态.

    个人语义：只影响该用户自己的置顶集合，不改变其他成员看到的顺序。
    """
    existing = db.execute(
        select(DocumentPin).where(DocumentPin.document_id == doc.id, DocumentPin.user_id == user_id)
    ).scalar_one_or_none()
    if pinned and existing is None:
        db.add(DocumentPin(document_id=doc.id, user_id=user_id))
        db.commit()
    elif not pinned and existing is not None:
        db.delete(existing)
        db.commit()
    return pinned


def serialize_documents(
    db: Session, docs: list[Document], *, pinned_ids: set[int] | None = None
) -> list[dict[str, Any]]:
    """批量文档 → 响应字典（列表/树用）.

    用 2 条聚合查询替代逐文档的 ``version_count`` + ``tag_ids`` 查询，
    消除大文档树（数百节点）上的 N+1。
    """
    if not docs:
        return []
    ids = [d.id for d in docs]
    counts = {
        row[0]: row[1]
        for row in db.execute(
            select(DocumentVersion.document_id, func.count())
            .where(DocumentVersion.document_id.in_(ids))
            .group_by(DocumentVersion.document_id)
        ).all()
    }
    tag_ids: dict[int, list[int]] = defaultdict(list)
    for doc_id, tag_id in db.execute(
        select(DocumentTag.document_id, DocumentTag.tag_id).where(DocumentTag.document_id.in_(ids))
    ).all():
        tag_ids[doc_id].append(tag_id)
    pinned = pinned_ids or set()
    return [
        _serialize_document(
            doc,
            version_total=0 if doc.is_folder else int(counts.get(doc.id, 0)),
            tag_ids=tag_ids.get(doc.id, []),
            pinned=doc.id in pinned,
        )
        for doc in docs
    ]


def _serialize_document(
    doc: Document, *, version_total: int, tag_ids: list[int], pinned: bool = False
) -> dict[str, Any]:
    """文档 → 响应字典主体（版本数/标签由调用方提供，避免逐条查询）."""
    return {
        "id": doc.id,
        "workspace_id": doc.workspace_id,
        "parent_id": doc.parent_id,
        "title": doc.title,
        "slug": doc.slug,
        "content_type": doc.content_type,
        "author": doc.author,
        "summary": doc.summary,
        "toc_json": doc.toc_json or [],
        "status": doc.status,
        "is_folder": doc.is_folder,
        "sort_order": doc.sort_order,
        "content_size": doc.content_size,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
        "created_by_id": doc.created_by_id,
        "updated_by_id": doc.updated_by_id,
        "tag_ids": tag_ids,
        "version_count": version_total,
        "pinned": pinned,
    }
