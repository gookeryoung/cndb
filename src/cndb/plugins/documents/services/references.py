"""跨工作区移动后的引用修复（ADR 0156）.

移动保留文档 id 与版本链，但**引用仍是工作区局部语义**：

- ``[[标题]]`` 双链按当前工作区标题解析 → 指向留在源工作区的文档则断链；
- ``{{table:<表ID>|...}}`` 数据表引用指向源工作区的表 → 解析失败。

本模块做三件事，且只做这三件事：

1. **诊断**（`diagnose_move_references`）：两方向扫描（被移动文档内 → 源工作区目标；
   源工作区文档 → 被移动文档标题），返回可读的 :class:`ReferenceIssue`；
2. **预览**（`preview_repair`）：按策略给出「原文 → 新文」，不落库；
3. **执行**（`apply_repair`）：按策略改写正文并**生成新版本**（`change_type=move_repair`），
   幂等、可回滚、事件留痕（不含正文）。

安全口径（不变量 R1..R6）：

- 默认策略 ``none``，绝不静默改正文；
- 只替换诊断命中的片段（复用 ``iter_wikilinks`` / ``parse_table_ref_line``），
  代码围栏内文本与其余字节一律不动；
- 无残留引用时不生成版本；
- ``snapshot`` 失败（表已删 / 无权限）降级为 ``annotate`` 文案，不中断整批。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import (
    CHANGE_TYPE_MOVE_REPAIR,
    Document,
    DocumentVersion,
)
from cndb.plugins.documents.services import content as content_service
from cndb.plugins.documents.services import parse

logger = logging.getLogger(__name__)

RepairStrategy = Literal["none", "annotate", "snapshot"]
STRATEGIES: tuple[str, ...] = ("none", "annotate", "snapshot")
#: 单次修复的文档上限（与移动同口径）
MAX_REPAIR_DOCS = 200
#: 诊断结果上限（防止极端正文撑爆响应）
MAX_ISSUES = 2000

#: 表格引用所在行（用于按行精确替换，保留缩进）
_TABLE_REF_LINE = re.compile(r"^(?P<indent>\s*)(?P<raw>\{\{table:[^{}]*\}\})\s*$")

REASON_TARGET_LEFT_BEHIND = "target_left_behind"
REASON_TARGET_MOVED = "target_moved"
REASON_TARGET_NOT_FOUND = "target_not_found"
REASON_TABLE_IN_OTHER_WORKSPACE = "table_in_other_workspace"
REASON_TABLE_DELETED = "table_deleted"


@dataclass
class ReferenceIssue:
    """一条失效引用（C9：可解释）."""

    document_id: int
    workspace_id: int
    kind: str  # wikilink | table_ref
    raw: str
    reason: str
    target_workspace_id: int | None = None
    target_workspace_name: str | None = None
    target_title: str | None = None
    target_table_id: int | None = None
    anchor: str | None = None
    alias: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "workspace_id": self.workspace_id,
            "kind": self.kind,
            "raw": self.raw,
            "reason": self.reason,
            "target_workspace_id": self.target_workspace_id,
            "target_workspace_name": self.target_workspace_name,
            "target_title": self.target_title,
            "target_table_id": self.target_table_id,
        }


@dataclass
class RepairPreview:
    """一条引用的修复预览（原文 → 新文）."""

    document_id: int
    raw: str
    next: str
    kind: str
    reason: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "raw": self.raw,
            "next": self.next,
            "kind": self.kind,
            "reason": self.reason,
        }


@dataclass
class RepairResult:
    changed_documents: int = 0
    changed_references: int = 0
    skipped_documents: int = 0
    truncated: bool = False
    recomputed: bool = False
    issues: list[dict[str, Any]] = field(default_factory=list)
    previews: list[dict[str, Any]] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "changed_documents": self.changed_documents,
            "changed_references": self.changed_references,
            "skipped_documents": self.skipped_documents,
            "truncated": self.truncated,
            "recomputed": self.recomputed,
            "issues": self.issues,
            "previews": self.previews,
        }


# ── 内部工具 ──


def _latest_contents(db: Session, doc_ids: Iterable[int]) -> dict[int, str]:
    """批量取各文档最新版本正文（避免逐篇 N+1）."""
    ids = list(dict.fromkeys(doc_ids))
    if not ids:
        return {}
    latest = (
        select(
            DocumentVersion.document_id.label("document_id"),
            func.max(DocumentVersion.version_number).label("version_number"),
        )
        .where(DocumentVersion.document_id.in_(ids))
        .group_by(DocumentVersion.document_id)
        .subquery()
    )
    rows = db.execute(
        select(DocumentVersion.document_id, DocumentVersion.content).join(
            latest,
            (DocumentVersion.document_id == latest.c.document_id)
            & (DocumentVersion.version_number == latest.c.version_number),
        )
    ).all()
    # 外存版本 content 为空串，需要按 doc 读盘
    docs = {doc.id: doc for doc in db.query(Document).filter(Document.id.in_(ids)).all()}
    out: dict[int, str] = {}
    for doc_id, stored in rows:
        doc = docs.get(doc_id)
        if doc is None:
            continue
        if stored == "" and doc.content_size > 0:
            version = content_service.latest_version(db, doc_id)
            out[doc_id] = content_service.load_content(version, doc) if version else ""
        else:
            out[doc_id] = stored
    return out


def _format_wikilink_text(issue: ReferenceIssue, workspace_name: str) -> str:
    label = issue.alias or issue.target_title or issue.raw
    if issue.reason == REASON_TARGET_NOT_FOUND:
        return f"{label}（引用的文档不存在）"
    return f"{label}（已移至「{workspace_name}」）"


def _format_table_text(issue: ReferenceIssue, workspace_name: str) -> str:
    if issue.reason == REASON_TABLE_DELETED:
        return "（数据表引用已失效：原数据表已删除）"
    return f"（数据表引用已失效：原数据表在「{workspace_name}」）"


def _workspace_name(db: Session, workspace_id: int | None) -> str:
    if workspace_id is None:
        return "其它工作区"
    from cndb.plugins.workspaces.models import Workspace

    workspace = db.get(Workspace, workspace_id)
    return workspace.name if workspace is not None else f"工作区 #{workspace_id}"


def _table_workspace(db: Session, table_id: int) -> tuple[int | None, str | None]:
    """数据表归属工作区（不存在返回 (None, None)）."""
    from cndb.plugins.tables.models import DataTable

    table = db.get(DataTable, table_id)
    if table is None:
        return None, None
    return table.workspace_id, table.name


# ── 1) 诊断 ──


def diagnose_move_references(
    db: Session,
    *,
    source_workspace_id: int,
    target_workspace_id: int,
    moved_doc_ids: list[int],
) -> list[ReferenceIssue]:
    """诊断一次移动影响到的全部引用（两个方向）."""
    ids = list(dict.fromkeys(moved_doc_ids))
    if len(ids) > MAX_REPAIR_DOCS:
        raise BadRequestError(f"单次最多诊断 {MAX_REPAIR_DOCS} 篇文档")
    moved_docs = db.query(Document).filter(Document.id.in_(ids)).all() if ids else []
    moved_by_title: dict[str, Document] = {}
    for doc in moved_docs:
        moved_by_title.setdefault(doc.title, doc)
    contents = _latest_contents(db, [doc.id for doc in moved_docs])

    target_name = _workspace_name(db, target_workspace_id)
    source_name = _workspace_name(db, source_workspace_id)
    issues: list[ReferenceIssue] = []
    seen: set[tuple[int, str]] = set()

    # 方向 1：被移动文档内 → 指向源工作区（或已删除）的目标
    source_titles = {
        row[0]
        for row in db.execute(
            select(Document.title).where(
                Document.workspace_id == source_workspace_id,
                Document.is_deleted == False,  # noqa: E712
            )
        ).all()
    }
    for doc in moved_docs:
        if doc.is_folder:
            continue
        text = contents.get(doc.id, "")
        for link in parse.iter_wikilinks(text):
            title = link["target"]
            if not title:
                continue
            # 同一子树内的一起搬走了 → 在目标工作区仍可解析，不算失效
            if title in moved_by_title:
                continue
            key = (doc.id, link["raw"])
            if key in seen:
                continue
            seen.add(key)
            found = title in source_titles
            issues.append(
                ReferenceIssue(
                    document_id=doc.id,
                    workspace_id=target_workspace_id,
                    kind="wikilink",
                    raw=link["raw"],
                    reason=REASON_TARGET_LEFT_BEHIND if found else REASON_TARGET_NOT_FOUND,
                    target_workspace_id=source_workspace_id if found else None,
                    target_workspace_name=source_name if found else None,
                    target_title=title,
                    anchor=link["anchor"] or None,
                    alias=link["alias"] or None,
                )
            )
        for line in text.splitlines():
            match = _TABLE_REF_LINE.match(line)
            if match is None:
                continue
            raw = match.group("raw")
            spec = content_service_parse_table_ref(raw)
            if spec is None or spec.table_id is None:
                continue
            key = (doc.id, raw)
            if key in seen:
                continue
            table_ws, _table_name = _table_workspace(db, spec.table_id)
            if table_ws == target_workspace_id:
                continue  # 目标工作区自己的表，引用仍然有效
            seen.add(key)
            if table_ws is None:
                issues.append(
                    ReferenceIssue(
                        document_id=doc.id,
                        workspace_id=target_workspace_id,
                        kind="table_ref",
                        raw=raw,
                        reason=REASON_TABLE_DELETED,
                        target_table_id=spec.table_id,
                    )
                )
            else:
                issues.append(
                    ReferenceIssue(
                        document_id=doc.id,
                        workspace_id=target_workspace_id,
                        kind="table_ref",
                        raw=raw,
                        reason=REASON_TABLE_IN_OTHER_WORKSPACE,
                        target_workspace_id=table_ws,
                        target_workspace_name=source_name
                        if table_ws == source_workspace_id
                        else _workspace_name(db, table_ws),
                        target_table_id=spec.table_id,
                    )
                )

    # 方向 2：源工作区残留文档 → 指向被移动文档标题（移动后必断，只能 annotate）
    moved_titles = [title for title in moved_by_title if title]
    if moved_titles:
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
                Document.workspace_id == source_workspace_id,
                Document.is_deleted == False,  # noqa: E712
                Document.is_folder == False,  # noqa: E712
            )
        ).all()
        moved_id_set = {doc.id for doc in moved_docs}
        for doc, version in rows:
            if doc.id in moved_id_set:
                continue
            text = content_service.load_content(version, doc)
            if not text or "[[" not in text:
                continue
            for link in parse.iter_wikilinks(text):
                if link["target"] not in moved_by_title:
                    continue
                key = (doc.id, link["raw"])
                if key in seen:
                    continue
                seen.add(key)
                issues.append(
                    ReferenceIssue(
                        document_id=doc.id,
                        workspace_id=source_workspace_id,
                        kind="wikilink",
                        raw=link["raw"],
                        reason=REASON_TARGET_MOVED,
                        target_workspace_id=target_workspace_id,
                        target_workspace_name=target_name,
                        target_title=link["target"],
                        anchor=link["anchor"] or None,
                        alias=link["alias"] or None,
                    )
                )

    issues.sort(key=lambda item: (item.workspace_id, item.document_id, item.raw))
    return issues[:MAX_ISSUES]


def content_service_parse_table_ref(raw: str) -> Any:
    """薄封装：复用导出侧的表格引用解析（避免在本模块重复实现）."""
    from cndb.plugins.documents.services.export.table_refs import parse_table_ref_line

    return parse_table_ref_line(raw)


# ── 2) 预览 ──


def _snapshot_table(db: Session, raw: str, workspace_id: int, actor: User) -> str | None:
    """把一条表格引用渲染为静态 GFM 表格（失败返回 None → 调用方降级 annotate）."""
    from cndb.plugins.documents.services.export.table_refs import (
        make_table_resolver,
        rewrite_markdown_table_refs,
    )

    try:
        resolver = make_table_resolver(db, workspace_id, actor)
        rewritten = rewrite_markdown_table_refs(raw, resolver)
    except Exception:  # pragma: no cover - 权限 / 数据异常一律降级
        logger.warning("表格快照失败，降级为注释: %s", raw, exc_info=True)
        return None
    if "{{table:" in rewritten:
        # 解析失败时 rewrite 会返回错误文案，同样视为失败，走 annotate
        return None
    return rewritten


def preview_repair(
    db: Session,
    *,
    issues: list[ReferenceIssue],
    strategy: str,
    actor: User,
) -> list[RepairPreview]:
    """按策略生成「原文 → 新文」（不落库）."""
    if strategy not in STRATEGIES:
        raise BadRequestError(f"不支持的修复策略: {strategy}")
    if strategy == "none" or not issues:
        return []
    previews: list[RepairPreview] = []
    for issue in issues:
        if issue.kind == "wikilink":
            workspace_name = issue.target_workspace_name or "其它工作区"
            nxt = _format_wikilink_text(issue, workspace_name)
        else:
            workspace_name = issue.target_workspace_name or "其它工作区"
            nxt = None
            if strategy == "snapshot" and issue.reason == REASON_TABLE_IN_OTHER_WORKSPACE:
                # 表还在源工作区 → 用源工作区权限渲染快照（移动操作的执行者本来是源成员）
                snapshot_ws = issue.target_workspace_id or issue.workspace_id
                nxt = _snapshot_table(db, issue.raw, snapshot_ws, actor)
            if nxt is None:
                nxt = _format_table_text(issue, workspace_name)
        previews.append(
            RepairPreview(document_id=issue.document_id, raw=issue.raw, next=nxt, kind=issue.kind, reason=issue.reason)
        )
    return previews


# ── 3) 执行 ──


def _rewrite_outside_fences(text: str, replacements: dict[str, str]) -> tuple[str, int]:
    """按行替换，**跳过代码围栏内文本**（R4），返回 (新文, 命中条数)."""
    if not replacements:
        return text, 0
    out: list[str] = []
    in_fence = False
    hits = 0
    for line in text.split("\n"):
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        replaced = line
        for raw, new in replacements.items():
            if raw and raw in replaced:
                hits += replaced.count(raw)
                replaced = replaced.replace(raw, new)
        out.append(replaced)
    return "\n".join(out), hits


def apply_repair(
    db: Session,
    *,
    source_workspace_id: int,
    target_workspace_id: int,
    moved_doc_ids: list[int],
    strategy: str,
    actor: User,
    confirm: bool = False,
) -> RepairResult:
    """执行修复（默认预览；``confirm=True`` 才落库）.

    并发口径（D6）：``confirm`` 时**重新诊断 + 按最新版本重算**，响应带 ``recomputed`` 标记。
    """
    from cndb.core.events import record_event
    from cndb.plugins.documents.services.content import update_content
    from cndb.plugins.workspaces.models import Workspace
    from cndb.plugins.workspaces.permissions import WorkspaceCapability, resolve_capabilities

    if strategy not in STRATEGIES:
        raise BadRequestError(f"不支持的修复策略: {strategy}")
    if strategy == "none":
        return RepairResult()

    issues = diagnose_move_references(
        db,
        source_workspace_id=source_workspace_id,
        target_workspace_id=target_workspace_id,
        moved_doc_ids=moved_doc_ids,
    )
    truncated = len(issues) >= MAX_ISSUES
    previews = preview_repair(db, issues=issues, strategy=strategy, actor=actor)
    result = RepairResult(
        truncated=truncated,
        issues=[issue.as_payload() for issue in issues],
        previews=[preview.as_payload() for preview in previews],
    )
    if not confirm or not previews:
        return result

    # 按文档分组；每个文档用**最新版本**重算替换（D6）
    by_doc: dict[int, list[RepairPreview]] = {}
    for preview in previews:
        by_doc.setdefault(preview.document_id, []).append(preview)

    for doc_id, doc_previews in by_doc.items():
        doc = db.get(Document, doc_id)
        if doc is None or doc.is_folder:
            result.skipped_documents += 1
            continue
        workspace = db.get(Workspace, doc.workspace_id)
        if (
            workspace is None
            or WorkspaceCapability.WRITE not in resolve_capabilities(actor, workspace, db).capabilities
        ):
            result.skipped_documents += 1
            continue
        version = content_service.latest_version(db, doc.id)
        text = content_service.load_content(version, doc) if version else ""
        if not text:
            result.skipped_documents += 1
            continue
        replacements = {preview.raw: preview.next for preview in doc_previews if preview.raw}
        rewritten, hits = _rewrite_outside_fences(text, replacements)
        if hits == 0 or rewritten == text:
            continue
        try:
            update_content(
                db,
                doc.workspace_id,
                doc.id,
                actor,
                content=rewritten,
                change_summary="跨工作区移动引用修复",
                change_type=CHANGE_TYPE_MOVE_REPAIR,
            )
        except Exception:
            db.rollback()
            logger.warning("引用修复写入失败: doc=%s", doc.id, exc_info=True)
            result.skipped_documents += 1
            continue
        result.changed_documents += 1
        result.changed_references += hits

    if result.changed_documents:
        record_event(
            db,
            "documents.references_repaired",
            summary=f"跨工作区移动引用修复：{result.changed_documents} 篇 / {result.changed_references} 条",
            target_type="workspace",
            target_id=target_workspace_id,
            workspace_id=target_workspace_id,
            actor_id=actor.id,
            actor_name=actor.username,
            detail={
                "source_workspace_id": source_workspace_id,
                "strategy": strategy,
                "documents": result.changed_documents,
                "references": result.changed_references,
            },
        )
    return result


def references_payload(issues: list[ReferenceIssue]) -> list[dict[str, Any]]:
    """诊断结果 → 响应载荷（工作区名已在诊断期解析，前端可直接展示原因）."""
    return [issue.as_payload() for issue in issues]


__all__ = [
    "MAX_ISSUES",
    "MAX_REPAIR_DOCS",
    "REASON_TABLE_DELETED",
    "REASON_TABLE_IN_OTHER_WORKSPACE",
    "REASON_TARGET_LEFT_BEHIND",
    "REASON_TARGET_MOVED",
    "REASON_TARGET_NOT_FOUND",
    "STRATEGIES",
    "ReferenceIssue",
    "RepairPreview",
    "RepairResult",
    "apply_repair",
    "diagnose_move_references",
    "preview_repair",
    "references_payload",
]
