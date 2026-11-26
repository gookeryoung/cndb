"""工作区附件管理（需求 0174）.

附件物理位置 ``settings.UPLOAD_DIR/{workspace_id}``，归属记录在 ``files_fileowner``。
本模块只读扫描 + 孤儿回收：

- 列表：目录文件 + 归属文档标题，按 mtime 倒序；
- 体检：扫描工作区全部未删除文档的最新正文与 ``asset_file_key``，统计每个附件被引用次数；
  孤儿 = 文件存在、引用次数 0、且没有 ``FileOwner`` 记录（历史无归属但被引用的附件不误判）；
- 回收：只删体检判定为孤儿的文件，默认 dry-run。
"""

from __future__ import annotations

import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.plugins.documents.models import Document
from cndb.plugins.documents.services.content import latest_version, load_content
from cndb.plugins.files.models import FileOwner
from cndb.plugins.files.services import resolve_workspace_file

# 孤儿判定保护期：刚上传、尚未保存到正文的文件可能正在编辑中，24h 内不判孤儿
ORPHAN_MIN_AGE_SECONDS = 24 * 3600

# 站内文件引用：`file:<key>` 与 Obsidian/压缩包形态的 `assets/<key>`（key 为 uuid+后缀）
_FILE_REF_RE = re.compile(r"(?:file:|assets/)([A-Za-z0-9][A-Za-z0-9._-]{0,200})")


def _workspace_dir(workspace_id: int) -> Path:
    directory = settings.UPLOAD_DIR / str(workspace_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _title_map(db: Session, document_ids: set[int]) -> dict[int, str]:
    if not document_ids:
        return {}
    rows = db.execute(select(Document.id, Document.title).where(Document.id.in_(document_ids))).all()
    return {int(row[0]): str(row[1]) for row in rows}


def list_workspace_attachments(
    db: Session,
    workspace_id: int,
    *,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """附件列表（文件名 / 大小 / 归属文档 / 时间），按上传时间倒序分页."""
    files = [path for path in _workspace_dir(workspace_id).iterdir() if path.is_file()]
    keyword = q.strip().lower()
    if keyword:
        files = [path for path in files if keyword in path.name.lower()]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    total = len(files)
    page = files[offset : offset + limit]
    keys = [path.name for path in page]
    owners = {
        owner.file_key: owner
        for owner in db.execute(
            select(FileOwner).where(FileOwner.workspace_id == workspace_id, FileOwner.file_key.in_(keys))
        ).scalars()
    }
    titles = _title_map(db, {owner.document_id for owner in owners.values() if owner.document_id})
    items = []
    for path in page:
        stat = path.stat()
        owner = owners.get(path.name)
        items.append(
            {
                "file_key": path.name,
                "name": path.name,
                "size": int(stat.st_size),
                "uploaded_at": int(stat.st_mtime),
                "document_id": owner.document_id if owner else None,
                "document_title": titles.get(owner.document_id) if owner and owner.document_id else None,
                "has_owner": owner is not None,
            }
        )
    return {"items": items, "total": total}


def scan_workspace_attachments(db: Session, workspace_id: int) -> dict[str, Any]:
    """体检：统计附件引用次数并标记孤儿（只读，不删除）."""
    files = [path for path in _workspace_dir(workspace_id).iterdir() if path.is_file()]
    refs: Counter[str] = Counter()
    docs = (
        db.execute(
            select(Document).where(
                Document.workspace_id == workspace_id,
                Document.is_deleted == False,  # noqa: E712
            )
        )
        .scalars()
        .all()
    )
    for doc in docs:
        if doc.asset_file_key:
            refs[doc.asset_file_key] += 1
        if doc.is_folder:
            continue
        content = load_content(latest_version(db, doc.id), doc)
        for match in _FILE_REF_RE.finditer(content):
            refs[match.group(1)] += 1
    owner_keys = set(db.execute(select(FileOwner.file_key).where(FileOwner.workspace_id == workspace_id)).scalars())

    items = []
    orphan_bytes = 0
    for path in files:
        stat = path.stat()
        size = int(stat.st_size)
        ref_count = int(refs.get(path.name, 0))
        old_enough = time.time() - stat.st_mtime >= ORPHAN_MIN_AGE_SECONDS
        orphan = ref_count == 0 and path.name not in owner_keys and old_enough
        if orphan:
            orphan_bytes += size
        items.append(
            {
                "file_key": path.name,
                "name": path.name,
                "size": size,
                "ref_count": ref_count,
                "orphan": orphan,
            }
        )
    items.sort(key=lambda item: (not item["orphan"], item["name"]))
    return {
        "items": items,
        "total": len(items),
        "orphan_count": sum(1 for item in items if item["orphan"]),
        "orphan_bytes": orphan_bytes,
    }


def purge_orphan_attachments(db: Session, workspace_id: int, *, dry_run: bool = True) -> dict[str, Any]:
    """回收孤儿附件（默认 dry-run）；只删体检判定为孤儿的文件."""
    report = scan_workspace_attachments(db, workspace_id)
    orphans = [item for item in report["items"] if item["orphan"]]
    removed = 0
    removed_bytes = 0
    if not dry_run:
        for item in orphans:
            path = resolve_workspace_file(workspace_id, item["file_key"])
            if not path.is_file():
                continue
            try:
                path.unlink()
            except OSError:  # pragma: no cover - 文件被占用时保留，交由下次体检
                continue
            removed += 1
            removed_bytes += int(item["size"])
    return {
        "dry_run": dry_run,
        "orphan_count": len(orphans),
        "orphan_bytes": int(report["orphan_bytes"]),
        "removed_files": removed,
        "removed_bytes": removed_bytes,
    }
