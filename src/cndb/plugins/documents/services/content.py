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
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from cndb.core.config import settings
from cndb.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from cndb.plugins.documents.models import (
    CHANGE_TYPE_MANUAL,
    CHANGE_TYPE_ROLLBACK,
    CONTENT_TYPE_FOLDER,
    EXTERNAL_MIN_SIZE,
    INLINE_MAX_SIZE,
    Document,
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


def _external_dir(doc_id: int) -> Path:
    return _DOCS_DIR / str(doc_id)


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
    """从版本记录加载内容，自动识别压缩/外存策略."""
    if version is None:
        return ""
    raw = version.content
    if doc.content_path and raw == "":
        p = Path(doc.content_path)
        if p.is_file():
            return gzip.decompress(p.read_bytes()).decode("utf-8")
        logger.warning("外存内容文件缺失: %s", doc.content_path)
        return ""
    if raw.startswith(_COMPRESSED_PREFIX):
        return gzip.decompress(base64.b64decode(raw[len(_COMPRESSED_PREFIX) :])).decode("utf-8")
    return raw


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


def _encode_inline(content: str, raw_size: int) -> str:
    if raw_size <= INLINE_MAX_SIZE:
        return content
    compressed = gzip.compress(content.encode("utf-8"), compresslevel=6)
    return _COMPRESSED_PREFIX + base64.b64encode(compressed).decode("ascii")


def _store_content_bytes(doc: Document, next_num: int, content: str, raw_size: int) -> str:
    """按分级存储策略落盘，返回 DB content 字段应存的值.

    - ≤50KB：原文内联
    - ≤2MB：gz base64 内联
    - >2MB：gzip 写文件系统，返回 ""（doc.content_path 指向文件）
    """
    if raw_size <= INLINE_MAX_SIZE:
        return content
    compressed = gzip.compress(content.encode("utf-8"), compresslevel=6)
    if raw_size > EXTERNAL_MIN_SIZE:
        d = _external_dir(doc.id)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"v{next_num}.md.gz"
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
    db.commit()
    db.refresh(doc)
    return doc


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


def soft_delete_document(db: Session, workspace_id: int, doc_id: int, user: User) -> Document:
    """软删除文档（文件夹删除递归标记子节点）."""
    doc = get_document_or_404(db, workspace_id, doc_id)
    require_editor(db, workspace_id, user)

    doc.is_deleted = True
    doc.updated_by_id = user.id
    if doc.is_folder:
        _delete_descendants(db, doc)
    _sync_fts_delete(db, doc.id)
    db.commit()
    return doc


def _delete_descendants(db: Session, folder: Document) -> None:
    children = (
        db.execute(
            select(Document).where(
                Document.parent_id == folder.id,
                Document.is_deleted == False,  # noqa: E712
            )
        )
        .scalars()
        .all()
    )
    for child in children:
        child.is_deleted = True
        if child.is_folder:
            _delete_descendants(db, child)
        else:
            _sync_fts_delete(db, child.id)


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
    """
    docs = (
        db.execute(
            select(Document).where(
                Document.workspace_id == workspace_id,
                Document.is_deleted == False,  # noqa: E712
                Document.is_folder == False,  # noqa: E712
            )
        )
        .scalars()
        .all()
    )
    target = f"[[{title}]]"
    hits: list[Document] = []
    for d in docs:
        v = latest_version(db, d.id)
        if v is None:
            continue
        if target in load_content(v, d):
            hits.append(d)
    return hits


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


def serialize_document(db: Session, doc: Document) -> dict[str, Any]:
    """文档 → 响应字典（列表/详情共用）。"""
    tag_ids = [
        row.tag_id for row in db.execute(select(DocumentTag_.tag_id).where(DocumentTag_.document_id == doc.id)).all()
    ]
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
        "version_count": version_count(db, doc.id) if not doc.is_folder else 0,
    }


# 局部导入别名，避免顶部循环导入
from cndb.plugins.documents.models import DocumentTag as DocumentTag_  # noqa: E402
