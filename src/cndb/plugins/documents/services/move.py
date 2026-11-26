"""文档跨工作区移动（ADR 0155）.

一句话语义：把若干根节点（可含文件夹与整棵子树）从源工作区**真移动**到目标工作区，
保留文档 id、版本链、站内文件、问题讨论与待审修改申请；访客分享链接不中断；
写盘前按目标工作区配额预判，超限直接 413。

顺序（M1 原子性，不可交换）：

1. 校验：可见性 / 源 WRITE / 目标 WRITE / 目标文档模块 / 父节点 / 根节点未删
2. 配额：``已用 + 本次字节 > 配额`` → 413（**写盘之前**）
3. 复制站内文件到目标工作区目录（缺文件跳过计数；复制失败整体失败，无 DB 写入）
4. 单事务改 DB：子树 workspace_id、根节点 parent_id/sort_order、issue/申请/文件归属
5. 提交成功后删除源工作区文件（失败只记日志）
6. 两侧存储快照标脏并各记一条 ``core_event``
"""

from __future__ import annotations

import logging
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError, NotFoundError, PermissionDeniedError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import Document, DocumentChangeRequest, DocumentDraft, DocumentIssue

logger = logging.getLogger(__name__)

#: 单次移动允许的根节点上限（批量选择 / 文件夹混选）
MAX_MOVE_ROOTS = 200
#: 正文中站内文件的引用形式：``file:<file_key>``
_FILE_REF = re.compile(r"file:([A-Za-z0-9][A-Za-z0-9._-]{0,254})")
#: GitHub 风格「文件缺失」提示（与导出侧同口径，不做 500）
MISSING_FILE_NOTE = "移动时发现 {count} 个站内文件缺失（已跳过，正文引用保留）"


@dataclass
class MoveResult:
    """一次移动的可解释结果（C9）."""

    document_ids: list[int]
    target_workspace_id: int
    moved_nodes: int
    moved_files: int
    moved_change_requests: int
    moved_bytes: int
    missing_files: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "document_ids": list(self.document_ids),
            "target_workspace_id": self.target_workspace_id,
            "moved_nodes": self.moved_nodes,
            "moved_files": self.moved_files,
            "moved_change_requests": self.moved_change_requests,
            "moved_bytes": self.moved_bytes,
            "missing_files": list(self.missing_files),
        }


# ── 查询 / 收集 ──


def _workspace_or_404(db: Session, workspace_id: int) -> Any:
    from cndb.plugins.workspaces.models import Workspace

    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise NotFoundError("工作区不存在")
    return workspace


def _require_write(db: Session, workspace: Any, user: User) -> None:
    """目标 / 源工作区写权限（与删除文档同口径）."""
    from cndb.plugins.workspaces.permissions import WorkspaceCapability, resolve_capabilities

    if WorkspaceCapability.WRITE not in resolve_capabilities(user, workspace, db).capabilities:
        raise PermissionDeniedError("仅工作区所有者或编辑者可以移动文档")


def resolve_move_roots(db: Session, *, source_workspace_id: int, root_ids: list[int], actor: User) -> list[Document]:
    """校验并返回根节点（可见 / 未删 / 去重 / 去嵌套）.

    Raises:
        BadRequestError: 空选择 / 超过上限 / 根节点在回收站 / 编号非法
        NotFoundError: 工作区或文档不可见（统一 404，不泄露存在性）
    """
    from cndb.plugins.documents.services import visibility

    if not root_ids:
        raise BadRequestError("请先选择要移动的文档")
    if len(root_ids) > MAX_MOVE_ROOTS:
        raise BadRequestError(f"单次最多移动 {MAX_MOVE_ROOTS} 个文档（含文件夹）")

    workspace = _workspace_or_404(db, source_workspace_id)
    _require_write(db, workspace, actor)

    roots: list[Document] = []
    seen: set[int] = set()
    for raw in root_ids:
        try:
            doc_id = int(raw)
        except (TypeError, ValueError) as exc:
            raise BadRequestError("文档编号非法") from exc
        if doc_id in seen:
            continue
        seen.add(doc_id)
        row = db.get(Document, doc_id)
        if row is None or row.workspace_id != source_workspace_id:
            raise NotFoundError("文档不存在")
        if row.is_deleted:
            raise BadRequestError(f"「{row.title}」在回收站中，请先恢复再移动")
        # 可见性按普通读口径（未发布草稿 / 归档仅创建者与 owner），不可见统一 404
        roots.append(visibility.get_visible_document_or_404(db, source_workspace_id, doc_id, actor))

    # 去嵌套：父节点已选中时，子节点随父一起走，不再单独作为根
    root_ids_set = {doc.id for doc in roots}
    filtered: list[Document] = []
    for doc in roots:
        ancestor = doc.parent_id
        nested = False
        while ancestor is not None:
            if ancestor in root_ids_set:
                nested = True
                break
            parent = db.get(Document, ancestor)
            ancestor = parent.parent_id if parent is not None else None
        if not nested:
            filtered.append(doc)
    return filtered


def collect_subtree(db: Session, roots: Iterable[Document]) -> list[Document]:
    """根节点 + 全部后代（**含回收站中的子节点**，保证树完整，D11）."""
    root_ids = [doc.id for doc in roots]
    if not root_ids:
        return []
    collected: dict[int, Document] = {doc.id: doc for doc in roots}
    frontier = list(root_ids)
    while frontier:
        children = db.query(Document).filter(Document.parent_id.in_(frontier)).all()
        frontier = []
        for child in children:
            if child.id not in collected:
                collected[child.id] = child
                frontier.append(child.id)
    return list(collected.values())


def collect_file_keys(db: Session, nodes: list[Document]) -> set[str]:
    """子树引用的站内文件 key：原件 + 全部版本正文 + 个人草稿正文."""
    from cndb.plugins.documents.models import DocumentVersion

    if not nodes:
        return set()
    doc_ids = [doc.id for doc in nodes]
    keys: set[str] = {doc.asset_file_key for doc in nodes if doc.asset_file_key}
    contents = (
        db.query(DocumentVersion.content)
        .filter(DocumentVersion.document_id.in_(doc_ids), DocumentVersion.content != "")
        .all()
    )
    drafts = db.query(DocumentDraft.content).filter(DocumentDraft.document_id.in_(doc_ids)).all()
    for (text,) in [*contents, *drafts]:
        if not text or "file:" not in text:
            continue
        keys.update(match.group(1) for match in _FILE_REF.finditer(text))
    return {key for key in keys if key and ".." not in key and "/" not in key and "\\" not in key}


def _file_path(workspace_id: int, file_key: str) -> Any:
    from cndb.plugins.files.services import resolve_workspace_file

    return resolve_workspace_file(workspace_id, file_key)


def move_size_bytes(db: Session, nodes: list[Document], file_keys: set[str]) -> int:
    """本次迁移计入目标工作区的字节数（与 ``workspace_storage_bytes`` 同口径）.

    口径 = 站内文件字节 + 文档外存目录（``data/docs/{doc_id}``）+ 内联正文 / 草稿字节。
    """
    from sqlalchemy import func

    from cndb.plugins.documents.models import DocumentVersion
    from cndb.plugins.workspaces.services.storage import _dir_size, _docs_root, _stored_bytes

    total = 0
    for key in file_keys:
        try:
            path = _file_path(nodes[0].workspace_id, key)
        except BadRequestError:  # pragma: no cover - collect_file_keys 已过滤非法 key
            continue
        if path.is_file():
            total += path.stat().st_size
    docs_root = _docs_root()
    doc_ids = [doc.id for doc in nodes]
    if doc_ids:
        for doc_id in doc_ids:
            total += _dir_size(docs_root / str(doc_id))
        version_total = (
            db.query(func.coalesce(func.sum(_stored_bytes(DocumentVersion.content)), 0))
            .filter(DocumentVersion.document_id.in_(doc_ids), DocumentVersion.content != "")
            .scalar()
        )
        draft_total = (
            db.query(func.coalesce(func.sum(_stored_bytes(DocumentDraft.content)), 0))
            .filter(DocumentDraft.document_id.in_(doc_ids))
            .scalar()
        )
        total += int(version_total or 0) + int(draft_total or 0)
    return int(total)


# ── 校验辅助 ──


def _validate_target(
    db: Session,
    *,
    source_workspace_id: int,
    target_workspace_id: int,
    actor: User,
    parent_id: int | None,
) -> Any:
    from cndb.plugins.workspaces.modules import resolve_features

    if int(target_workspace_id) == int(source_workspace_id):
        raise BadRequestError("源工作区与目标工作区相同")
    target = _workspace_or_404(db, target_workspace_id)
    _require_write(db, target, actor)
    if not resolve_features(target.modules or []).get("documents", False):
        raise BadRequestError("目标工作区未启用文档模块")
    if parent_id is not None:
        parent = db.get(Document, int(parent_id))
        if parent is None or parent.workspace_id != target_workspace_id or not parent.is_folder or parent.is_deleted:
            raise BadRequestError("目标文件夹不存在或不可用")
    return target


def _ensure_quota(db: Session, target: Any, needed: int) -> None:
    """配额先判（M6）：写盘之前拦下，与上传同一口径与状态码."""
    from cndb.plugins.workspaces.services.storage import workspace_quota_bytes
    from cndb.plugins.workspaces.services.storage_snapshot import snapshot_used_bytes

    quota = workspace_quota_bytes(target)
    used = snapshot_used_bytes(db, target.id, lazy=True)
    if used is None:  # pragma: no cover - 懒计算失败时的保守兜底
        raise BadRequestError("无法读取目标工作区存储用量，请稍后重试")
    if used + needed > quota:
        mb = 1024 * 1024
        raise BadRequestError(
            f"目标工作区存储空间不足：已用 {used / mb:.1f} MB / 配额 {quota / mb:.1f} MB，本次需 {needed / mb:.1f} MB"
        )


# ── 执行 ──


def move_nodes_to_workspace(
    db: Session,
    *,
    source_workspace_id: int,
    root_ids: list[int],
    target_workspace_id: int,
    actor: User,
    parent_id: int | None = None,
) -> MoveResult:
    """把根节点（含子树）移动到目标工作区（ADR 0155，唯一执行入口）."""
    import datetime as dt

    from cndb.core.events import record_event
    from cndb.plugins.documents.services import content as content_service
    from cndb.plugins.files.models import FileOwner
    from cndb.plugins.workspaces.services.storage_snapshot import mark_dirty

    roots = resolve_move_roots(db, source_workspace_id=source_workspace_id, root_ids=root_ids, actor=actor)
    target = _validate_target(
        db,
        source_workspace_id=source_workspace_id,
        target_workspace_id=target_workspace_id,
        actor=actor,
        parent_id=parent_id,
    )
    nodes = collect_subtree(db, roots)
    node_ids = [doc.id for doc in nodes]
    file_keys = collect_file_keys(db, nodes)
    needed = move_size_bytes(db, nodes, file_keys)
    _ensure_quota(db, target, needed)

    # ── 1) 复制文件（失败即整体失败，此阶段无 DB 写入） ──
    copied: list[str] = []
    missing: list[str] = []
    try:
        for key in sorted(file_keys):
            source_path = _file_path(source_workspace_id, key)
            if not source_path.is_file():
                missing.append(key)
                continue
            target_path = _file_path(target_workspace_id, key)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            copied.append(key)
    except OSError as exc:
        for key in copied:
            try:
                _file_path(target_workspace_id, key).unlink(missing_ok=True)
            except OSError:  # pragma: no cover - 清理失败只记日志
                logger.warning("清理已复制文件失败: %s", key, exc_info=True)
        logger.warning("跨工作区移动复制文件失败", exc_info=True)
        raise BadRequestError("文件搬迁失败（磁盘空间或权限不足），文档未移动") from exc

    try:
        now = dt.datetime.now(dt.UTC)
        # ── 2) 子树本体 ──
        for doc in nodes:
            doc.workspace_id = target_workspace_id
            # 模板绑定：id 型引用属于源工作区，移动后必然悬空 → 清空；
            # builtin:<key> 是代码常量，跨工作区仍然有效，保留（ADR 0177 C8）
            ref = doc.export_template_ref or ""
            if ref and not ref.startswith("builtin:"):
                doc.export_template_ref = None
            doc.updated_at = now
            doc.updated_by_id = actor.id
        sort_order = (
            db.query(Document)
            .filter(
                Document.workspace_id == target_workspace_id,
                Document.parent_id.is_(None) if parent_id is None else Document.parent_id == parent_id,
            )
            .count()
        )
        for doc in roots:
            doc.parent_id = parent_id
            sort_order += 1
            doc.sort_order = sort_order

        # ── 3) 申请 / 问题 / 文件归属 ──
        db.query(DocumentChangeRequest).filter(DocumentChangeRequest.document_id.in_(node_ids)).update(
            {DocumentChangeRequest.workspace_id: target_workspace_id}, synchronize_session=False
        )
        moved_requests = db.query(DocumentChangeRequest).filter(DocumentChangeRequest.document_id.in_(node_ids)).count()
        db.query(DocumentIssue).filter(DocumentIssue.document_id.in_(node_ids)).update(
            {DocumentIssue.workspace_id: target_workspace_id}, synchronize_session=False
        )
        if copied:
            db.query(FileOwner).filter(FileOwner.file_key.in_(copied)).update(
                {FileOwner.workspace_id: target_workspace_id}, synchronize_session=False
            )
        db.commit()
    except Exception:
        db.rollback()
        for key in copied:
            try:
                _file_path(target_workspace_id, key).unlink(missing_ok=True)
            except OSError:  # pragma: no cover - 清理失败只记日志
                logger.warning("回滚清理已复制文件失败: %s", key, exc_info=True)
        raise

    # 跨工作区移动改变了两个工作区的节点集合（需求 0182 C1）
    from cndb.plugins.documents.services.content import invalidate_link_graph_cache

    invalidate_link_graph_cache(source_workspace_id)
    invalidate_link_graph_cache(target_workspace_id)

    # ── 4) 提交成功：删源文件 + 重建检索 + 两侧统计与事件（失败只告警） ──
    for key in copied:
        try:
            _file_path(source_workspace_id, key).unlink(missing_ok=True)
        except OSError:  # pragma: no cover - 源文件删除失败不影响结果
            logger.warning("删除源工作区文件失败: %s", key, exc_info=True)
    for doc in nodes:
        try:
            version = content_service.latest_version(db, doc.id)
            content_service.sync_fts(db, doc, content_service.load_content(version, doc) if version else "")
        except Exception:  # pragma: no cover - 检索重建失败不阻断
            logger.warning("移动后重建检索失败: doc=%s", doc.id, exc_info=True)
    mark_dirty(source_workspace_id)
    mark_dirty(target_workspace_id)
    record_event(
        db,
        "documents.move_out",
        summary=f"移出 {len(nodes)} 个文档到工作区 #{target_workspace_id}",
        target_type="workspace",
        target_id=source_workspace_id,
        workspace_id=source_workspace_id,
        actor_id=actor.id,
        actor_name=actor.username,
        detail={"target_workspace_id": target_workspace_id, "document_ids": node_ids[:50], "nodes": len(nodes)},
    )
    record_event(
        db,
        "documents.move_in",
        summary=f"从工作区 #{source_workspace_id} 迁入 {len(nodes)} 个文档",
        target_type="workspace",
        target_id=target_workspace_id,
        workspace_id=target_workspace_id,
        actor_id=actor.id,
        actor_name=actor.username,
        detail={"source_workspace_id": source_workspace_id, "document_ids": node_ids[:50], "nodes": len(nodes)},
    )
    return MoveResult(
        document_ids=[doc.id for doc in roots],
        target_workspace_id=target_workspace_id,
        moved_nodes=len(nodes),
        moved_files=len(copied),
        moved_change_requests=moved_requests,
        moved_bytes=needed,
        missing_files=missing,
    )


def move_targets(db: Session, *, source_workspace_id: int, actor: User) -> list[dict[str, Any]]:
    """可移动目标工作区（前端弹窗数据源，避免前端猜权限 + 配额）.

    仅返回：用户有 `WRITE`、已启用文档模块、且不是源工作区的工作区；
    附带配额余量，前端在选中时即可提示「空间不足」。
    """
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember
    from cndb.plugins.workspaces.modules import resolve_features
    from cndb.plugins.workspaces.permissions import WorkspaceCapability, resolve_capabilities
    from cndb.plugins.workspaces.services.storage import workspace_quota_bytes
    from cndb.plugins.workspaces.services.storage_snapshot import snapshot_used_bytes

    _workspace_or_404(db, source_workspace_id)
    rows = (
        db.query(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .filter(WorkspaceMember.user_id == actor.id, Workspace.id != source_workspace_id)
        .order_by(Workspace.name)
        .all()
    )
    targets: list[dict[str, Any]] = []
    for workspace in rows:
        if WorkspaceCapability.WRITE not in resolve_capabilities(actor, workspace, db).capabilities:
            continue
        if not resolve_features(workspace.modules or []).get("documents", False):
            continue
        quota = workspace_quota_bytes(workspace)
        used = snapshot_used_bytes(db, workspace.id, lazy=True) or 0
        targets.append(
            {
                "id": workspace.id,
                "name": workspace.name,
                "role": None,
                "quota_bytes": quota,
                "used_bytes": used,
                "remaining_bytes": max(0, quota - used),
            }
        )
    return targets


__all__ = [
    "MAX_MOVE_ROOTS",
    "MoveResult",
    "collect_file_keys",
    "collect_subtree",
    "move_nodes_to_workspace",
    "move_size_bytes",
    "move_targets",
    "resolve_move_roots",
]
