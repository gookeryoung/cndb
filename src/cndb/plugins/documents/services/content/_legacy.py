"""文档内容服务：CRUD / 版本快照 / 乐观锁更新 / 分级存储.

存储策略（按内容大小自动分级）：
- ≤4KB：直接存 document_versions.content
- 4KB–2MB：gzip 压缩后存 DB（content 字段存 base64 压缩串，前缀 ``gz:`` 标记）
- >2MB：gzip 落文件系统 data/docs/{doc_id}/v{n}.md.gz，DB 存路径

历史版本按原策略写入的不带前缀原文仍可读（``load_content`` 自动识别）。

并发控制：乐观锁 — 更新时 WHERE updated_at 匹配客户端持有版本，失配抛 ConflictError。
"""

from __future__ import annotations

import logging
import shutil
import time
import uuid
import zlib
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from cndb.core.errors import ConflictError
from cndb.plugins.documents.models import (
    Document,
    DocumentTag,
    DocumentVersion,
)
from cndb.plugins.documents.services import parse

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User

from sqlalchemy.orm import Session

from cndb.plugins.documents.services import content as _pkg

from . import access

# 固定全名而非 __name__：拆包后日志分类必须仍是 …services.content（ADR 0180 D7）
logger = logging.getLogger("cndb.plugins.documents.services.content")
GRAPH_MAX_NODES = 500
_GRAPH_CACHE_TTL_SECONDS = 30.0
# 缓存条目上限（用户 × 工作区维度会累积）：超出时丢弃最旧条目，避免长驻进程无界增长。
_GRAPH_CACHE_MAX_ENTRIES = 256
_graph_cache: dict[tuple[int, str | int, int], tuple[float, dict[str, Any]]] = {}


def reset_link_graph_cache() -> None:
    """清空图谱聚合缓存（测试 / 全局重置使用）."""
    _graph_cache.clear()


def invalidate_link_graph_cache(workspace_id: int) -> None:
    """清掉单个工作区的图谱缓存（需求 0182 C1）.

    30s TTL 期间写路径不失效会让用户看到旧图（改完正文以为双链没生效）。
    按工作区粒度删键：一处写入不清空全站缓存。
    """
    for key in [k for k in _graph_cache if k[0] == workspace_id]:
        _graph_cache.pop(key, None)


def _prune_graph_cache(now: float) -> None:
    """清理过期条目；仍超上限时丢弃最旧一条（O(n)，n ≤ 256+1）."""
    for key in [k for k, (ts, _) in _graph_cache.items() if now - ts >= _GRAPH_CACHE_TTL_SECONDS]:
        _graph_cache.pop(key, None)
    while len(_graph_cache) >= _GRAPH_CACHE_MAX_ENTRIES:
        oldest = min(_graph_cache.items(), key=lambda item: item[1][0])[0]
        _graph_cache.pop(oldest, None)


def _broken_node_id(title: str) -> int:
    """断链目标用稳定负 id，避免与真实文档 id 冲突."""
    return -(zlib.crc32(title.encode("utf-8")) % 1_000_000_000) - 1


def build_link_graph(
    db: Session,
    workspace_id: int,
    user: User,
    *,
    max_nodes: int = GRAPH_MAX_NODES,
) -> dict[str, Any]:
    """工作区链接图：可见文档为节点，``[[标题]]`` 为边（需求 0168 C1/C2/C3）.

    - 解析唯一复用 ``parse.iter_wikilinks``，与 /links、/backlinks 同源；
    - 断链目标是虚拟节点（负 id，``broken=true``）；同名多命中取首个并标
      ``ambiguous``；自环过滤、边按 (源, 目标) 去重；
    - H33：draft/archived 仅创建者与 OWNER/超管可见，不可见文档不进节点与边；
    - C6：节点数上限按 updated_at 取最近 N，超出时 ``truncated=true``；
      聚合结果按 (工作区, 可见性身份) 缓存 30s。
    """
    from cndb.plugins.documents.services import visibility

    admin = visibility.is_document_admin(db, workspace_id, user)
    # max_nodes 必须进缓存键：同一身份用小窗口试探过之后，再用大窗口
    # 会命中「截断版」结果（测试与未来调参都会踩）。
    cache_key: tuple[int, str | int, int] = (workspace_id, "admin" if admin else user.id, max_nodes)
    cached = _graph_cache.get(cache_key)
    now = time.monotonic()
    if cached is not None and now - cached[0] < _GRAPH_CACHE_TTL_SECONDS:
        return cached[1]

    filters: list[Any] = [Document.workspace_id == workspace_id, Document.is_deleted == False]  # noqa: E712
    if not admin:
        filters.append(visibility.visible_condition(db, workspace_id, user, is_admin=False))
    total = int(db.execute(select(func.count()).select_from(Document).where(*filters)).scalar_one())
    docs = list(
        db.execute(
            select(Document).where(*filters).order_by(Document.updated_at.desc(), Document.id.desc()).limit(max_nodes)
        )
        .scalars()
        .all()
    )
    truncated = total > len(docs)

    title_counts: dict[str, int] = defaultdict(int)
    title_index: dict[str, int] = {}
    for doc in docs:
        title_counts[doc.title] += 1
        title_index.setdefault(doc.title, doc.id)
    # H33：区分「真断链」与「存在但当前用户不可见」——后者不得建节点/边，
    # 否则断链节点标题会把他人草稿的存在性泄漏给 viewer。只取标题列，不返回前端。
    all_titles = set(
        db.execute(
            select(Document.title).where(
                Document.workspace_id == workspace_id,
                Document.is_deleted == False,  # noqa: E712
            )
        )
        .scalars()
        .all()
    )
    # 只取可见文档标题（与上面的 all_titles 区分）：判断「窗口外」时不能用
    # all_titles，否则会把「不可见」也算成「被截断」，泄漏他人草稿的存在性。
    visible_titles = all_titles if admin else set(db.execute(select(Document.title).where(*filters)).scalars().all())

    nodes: list[dict[str, Any]] = [
        {
            "id": doc.id,
            "title": doc.title,
            "content_type": doc.content_type,
            "status": doc.status,
            "is_folder": bool(doc.is_folder),
            "broken": False,
        }
        for doc in docs
    ]
    broken_ids: set[int] = set()
    # 需求 0182 C2：节点被截断时，指向「存在但落在窗口外」文档的边会被丢掉，
    # 不统计的话中心文档看起来像孤立点。按 (源, 目标标题) 去重计数。
    out_of_view: set[tuple[int, str]] = set()
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[int, int]] = set()
    # 批量取每个文档的最新版本（id 单调递增，取 max(id) 等价最新版），
    # 避免 500 节点逐文档 latest_version 的 N+1 查询。
    versions: dict[int, DocumentVersion] = {}
    if docs:
        latest_ids = (
            select(func.max(DocumentVersion.id))
            .where(DocumentVersion.document_id.in_([doc.id for doc in docs]))
            .group_by(DocumentVersion.document_id)
        )
        versions = {
            row.document_id: row
            for row in db.execute(select(DocumentVersion).where(DocumentVersion.id.in_(latest_ids))).scalars()
        }
    for doc in docs:
        version = versions.get(doc.id)
        for link in parse.iter_wikilinks(_pkg.load_content(version, doc)):
            target_title = link["target"]
            if not target_title:
                continue  # [[#锚点]] 无目标标题，不构成跨文档边
            target_id = title_index.get(target_title)
            if target_id is None and target_title in all_titles:
                # 两种情况都落在这里：文档存在于窗口外（被 max_nodes 截断），
                # 或存在但当前用户不可见（H33）。前者计入 edges_out_of_view，
                # 后者必须静默丢弃（否则标题存在性泄漏）。
                if truncated and target_title in visible_titles:
                    out_of_view.add((doc.id, target_title))
                continue
            if target_id is None:
                target_id = _broken_node_id(target_title)
                if target_id not in broken_ids:
                    broken_ids.add(target_id)
                    nodes.append(
                        {
                            "id": target_id,
                            "title": target_title,
                            "content_type": "markdown",
                            "status": "broken",
                            "is_folder": False,
                            "broken": True,
                        }
                    )
            elif target_id == doc.id:
                continue  # 自环不画
            ambiguous = title_counts[target_title] > 1
            edge_key = (doc.id, target_id)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            edges.append(
                {
                    "source": doc.id,
                    "target": target_id,
                    "broken": target_id in broken_ids,
                    "ambiguous": ambiguous,
                    "raw": parse.format_wikilink(target_title, anchor=link["anchor"], alias=link["alias"]),
                }
            )

    payload = {
        "nodes": nodes,
        "edges": edges,
        "truncated": truncated,
        "total": total,
        "edges_out_of_view": len(out_of_view),
    }
    _prune_graph_cache(now)
    _graph_cache[cache_key] = (now, payload)
    return payload


DUPLICATE_SUFFIX = " 副本"


def _document_tag_ids(db: Session, document_id: int) -> list[int]:
    rows = db.execute(select(DocumentTag.tag_id).where(DocumentTag.document_id == document_id)).all()
    return [int(row[0]) for row in rows]


def _unique_duplicate_title(db: Session, workspace_id: int, base_title: str) -> str:
    """同工作区唯一副本标题：原名 副本 / 原名 副本 2 / 原名 副本 3 …"""
    existing = set(
        db.execute(
            select(Document.title).where(
                Document.workspace_id == workspace_id,
                Document.is_deleted == False,  # noqa: E712
            )
        )
        .scalars()
        .all()
    )
    candidate = f"{base_title}{DUPLICATE_SUFFIX}"
    seq = 2
    while candidate in existing:
        candidate = f"{base_title}{DUPLICATE_SUFFIX} {seq}"
        seq += 1
    return candidate[:500]


def _copy_asset_file(workspace_id: int, source: Document) -> tuple[str, str, int]:
    """复制原件字节到新 file_key（uuid + 原后缀），返回 (key, mime, size)."""
    from cndb.plugins.files.services import resolve_workspace_file

    source_path = resolve_workspace_file(workspace_id, source.asset_file_key or "")
    if not source_path.is_file():
        raise ConflictError("原件文件缺失，无法创建副本")
    new_key = f"{uuid.uuid4().hex}{source_path.suffix}"
    target_path = resolve_workspace_file(workspace_id, new_key)
    shutil.copy2(source_path, target_path)
    return new_key, source.asset_mime, int(source_path.stat().st_size)


def duplicate_document(
    db: Session,
    workspace_id: int,
    doc_id: int,
    user: User,
    *,
    parent_id: int | None = None,
) -> Document:
    """创建文档 / 文件夹子树的副本，返回新的根节点（需求 0172）.

    - 仅 owner/editor；源文档必须可见（由路由层 `get_visible_document_or_404` 保证）；
    - 根节点标题自动加「副本」并递增，子节点保留原标题；
    - 文件夹递归复制整棵子树；原件族复制文件字节并登记新 `FileOwner`；
    - 每个节点经 ``create_document`` 落库，因此只有 v1 版本。
    """
    access.require_editor(db, workspace_id, user)
    source = access.get_document_or_404(db, workspace_id, doc_id)
    target_parent = source.parent_id if parent_id is None else parent_id
    if target_parent is not None:
        parent = access.get_document_or_404(db, workspace_id, target_parent)
        if not parent.is_folder:
            raise ConflictError("父节点必须是文件夹")
    created = _duplicate_node(db, workspace_id, source, user, target_parent, is_root=True)
    # 副本标题以「副本」结尾，本身就是新的链接目标（需求 0182 C1）
    invalidate_link_graph_cache(workspace_id)
    return created


def _duplicate_node(
    db: Session,
    workspace_id: int,
    source: Document,
    user: User,
    parent_id: int | None,
    *,
    is_root: bool,
) -> Document:
    title = _unique_duplicate_title(db, workspace_id, source.title) if is_root else source.title
    if source.is_folder:
        new_doc = _pkg.create_document(
            db,
            workspace_id,
            user,
            title=title,
            is_folder=True,
            parent_id=parent_id,
            status=source.status,
            sort_order=source.sort_order,
        )
        children = (
            db.execute(
                select(Document)
                .where(
                    Document.parent_id == source.id,
                    Document.is_deleted == False,  # noqa: E712
                )
                .order_by(Document.sort_order, Document.id)
            )
            .scalars()
            .all()
        )
        for child in children:
            _duplicate_node(db, workspace_id, child, user, new_doc.id, is_root=False)
        return new_doc

    tag_ids = _document_tag_ids(db, source.id)
    if source.asset_file_key:
        new_key, mime, size = _copy_asset_file(workspace_id, source)
        new_doc = _pkg.create_document(
            db,
            workspace_id,
            user,
            title=title,
            parent_id=parent_id,
            status=source.status,
            tag_ids=tag_ids,
            sort_order=source.sort_order,
            export_template_ref=source.export_template_ref,
            content_type=source.content_type,
            asset_file_key=new_key,
            asset_mime=mime,
            content_size=size,
        )
        from cndb.plugins.files.services import record_owner

        record_owner(
            db,
            file_key=new_key,
            workspace_id=workspace_id,
            document_id=new_doc.id,
            uploaded_by_id=user.id,
        )
        return new_doc

    content = _pkg.load_content(_pkg.latest_version(db, source.id), source)
    return _pkg.create_document(
        db,
        workspace_id,
        user,
        title=title,
        content=content,
        parent_id=parent_id,
        status=source.status,
        tag_ids=tag_ids,
        sort_order=source.sort_order,
        export_template_ref=source.export_template_ref,
        content_type=source.content_type,
    )
