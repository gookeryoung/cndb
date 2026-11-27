"""双链解析与链接修复：反链 / 出链 / 断链修复（ADR 0180 D1）."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.core.errors import ConflictError
from cndb.plugins.documents.models import (
    Document,
    DocumentVersion,
)
from cndb.plugins.documents.services import parse

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User


from cndb.plugins.documents.services import content as _pkg

from . import access

logger = logging.getLogger("cndb.plugins.documents.services.content")


def find_backlinks(
    db: Session,
    workspace_id: int,
    title: str,
    *,
    viewer: Any = None,
    is_admin: bool = False,
) -> list[Document]:
    """反向链接扫描：返回工作区内正文含 ``[[title]]`` 的未删除文档列表.

    扫描源为非文件夹文档（文件夹无正文）；目标标题可为文件夹（被提及即计入）；
    含自引用（文档引用自身标题时也出现在结果中）。

    单次查询取各文档最新版本（``MAX(version_number)`` 分组子查询），
    避免历史上"逐文档查最新版本"的 N+1。
    """
    visibility_filters: list[Any] = []
    if viewer is not None and not is_admin:
        from cndb.plugins.documents.services.visibility import visible_condition

        visibility_filters.append(visible_condition(db, workspace_id, viewer, is_admin=False))

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
            *visibility_filters,
        )
        .order_by(Document.sort_order, Document.id)
    ).all()
    # 反链按「目标标题」匹配：[[标题]] / [[标题#锚点]] / [[标题|别名]] 都算引用
    return [
        doc
        for doc, version in rows
        if any(link["target"] == title for link in parse.iter_wikilinks(_pkg.load_content(version, doc)))
    ]


def resolve_outgoing_links(db: Session, workspace_id: int, doc: Document) -> list[dict[str, Any]]:
    """解析文档正文出链 ``[[标题#锚点|别名]]``：返回标题、命中文档 ID 与是否存在（断链）.

    代码围栏内的 ``[[...]]`` 不计入（见 ``parse.iter_wikilinks``）；
    同名文档取最早创建的一个；引用的目标可为文件夹。

    同一目标标题的多种写法（带锚点/别名）合并为一行，``raw`` 取首次出现的原文，
    便于前端原样展示；``anchor`` / ``alias`` 供修复与提示使用。
    """
    version = _pkg.latest_version(db, doc.id)
    links = parse.iter_wikilinks(_pkg.load_content(version, doc))
    if not links:
        return []

    merged: list[dict[str, str]] = []
    seen: dict[str, dict[str, str]] = {}
    for link in links:
        target = link["target"]
        if not target:
            continue
        if target in seen:
            # 同一目标补全锚点/别名信息（首个出现的写法优先展示）
            known = seen[target]
            known["anchor"] = known["anchor"] or link["anchor"]
            known["alias"] = known["alias"] or link["alias"]
            continue
        seen[target] = link
        merged.append(link)

    titles = [link["target"] for link in merged]
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
    return [
        {
            "title": link["target"],
            "document_id": index.get(link["target"]),
            "exists": link["target"] in index,
            "broken": link["target"] not in index,
            "anchor": link["anchor"],
            "alias": link["alias"],
            "raw": parse.format_wikilink(link["target"], anchor=link["anchor"], alias=link["alias"]),
        }
        for link in merged
    ]


def repair_wikilinks(
    db: Session,
    workspace_id: int,
    doc_id: int,
    user: User,
    repairs: list[Any],
) -> dict[str, Any]:
    """把正文中的断链 ``[[旧标题]]`` 改指为现存文档（创建新版本，可回溯）.

    Args:
        repairs: 元素含 ``title``（正文中原样出现的旧标题，锚点/别名写法同样命中）
            与 ``target_document_id``（同一工作区内未删除的目标文档；可为文件夹）。

    语义：
    - 目标必须属于同一工作区且未删除，否则 404；
    - 旧标题在正文中不存在、或目标标题与旧标题相同 → 该条跳过；
    - 改写保留原有锚点与别名（``[[旧#锚点|别名]]`` → ``[[新#锚点|别名]]``）；
    - 全部条目都未产生替换时抛 409，避免写入无意义的新版本；
    - 链接修复走 ``update_content``，因此同样保留完整版本历史。
    """
    doc = access.get_document_or_404(db, workspace_id, doc_id)
    access.require_editor(db, workspace_id, user)
    if doc.is_folder:
        raise ConflictError("文件夹没有正文，无法修复链接")

    content = _pkg.load_content(_pkg.latest_version(db, doc.id), doc)
    applied: list[dict[str, Any]] = []
    replaced = 0
    for item in repairs:
        title = str(item.title)
        target = access.get_document_or_404(db, workspace_id, item.target_document_id)
        if title == target.title:
            continue
        content, count = parse.rewrite_wikilink_target(content, title, target.title)
        if count == 0:
            continue
        replaced += count
        applied.append({"title": title, "new_title": target.title, "document_id": target.id, "count": count})

    if not applied:
        raise ConflictError(
            "未找到可修复的链接（正文中没有该标题，或目标标题与原标题相同）",
            code="no_link_repaired",
        )

    updated = _pkg.update_content(
        db,
        workspace_id,
        doc_id,
        user,
        content=content,
        change_summary=f"修复文档链接（{replaced} 处）",
        base_updated_at=None,
    )
    latest = _pkg.latest_version(db, doc_id)
    return {
        "document_id": doc_id,
        "version_number": latest.version_number if latest else 0,
        "repaired": applied,
        "replaced": replaced,
        "document": _pkg.serialize_document(db, updated),
    }
