"""通用文件导入编排：预览（只读）与落库（文件夹 / 冲突 / 附件 / 权限）.

复用 Obsidian 通道的既有权衡：两段式 ``analyze`` → ``import``、冲突三策略、文件夹层级
递增去重、附件落盘 + 归属登记（ADR 0010 I2/I4/I5）。
"""

from __future__ import annotations

import posixpath
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.core.errors import BadRequestError
from cndb.plugins.documents.models import CHANGE_TYPE_IMPORT, DOC_STATUSES, Document
from cndb.plugins.documents.services import content as content_service
from cndb.plugins.documents.services.obsidian import (
    CONFLICT_POLICIES,
    CONFLICT_RENAME,
    CONFLICT_SKIP,
    DETAIL_LIMIT,
    PREVIEW_LIMIT,
    RESULT_DOCS_LIMIT,
    _existing_child,
    _folder_chain,
    _next_title,
    _sibling_map,
    _validate_parent,
)
from cndb.plugins.files.models import FileOwner

from . import mhtml as mhtml_converter
from . import reader
from .errors import UnsupportedImport
from .formats import ASSET_CONTENT_TYPES
from .reader import ImportedDoc, UploadedItem


class _UploadStore:
    """本次导入的附件落盘器：写工作区上传目录 + 记录归属（图片按文档粒度绑定）."""

    def __init__(self, db: Session, workspace_id: int, user: Any, *, enabled: bool) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.user = user
        self.enabled = enabled
        self.written = 0
        self.bytes_written = 0
        self.asset_written = 0
        self.asset_bytes = 0
        self._pending: list[str] = []

    def store(self, data: bytes, name: str) -> str | None:
        """落盘一个内嵌图片，返回站点文件 key（未启用返回 None）."""
        if not self.enabled or not data:
            return None
        return self._write(data, name)

    def store_asset(self, data: bytes, name: str) -> str:
        """落盘原件（PDF / Office / 图片），返回站点文件 key.

        与 `import_attachments` 开关无关：原件是文档本体，必须落盘（ADR 0025 D4）。
        """
        key = self._write(data, name)
        self.asset_written += 1
        self.asset_bytes += len(data)
        return key

    def _write(self, data: bytes, name: str) -> str:
        suffix = Path(name).suffix.lower()
        key = f"{uuid.uuid4().hex}{suffix}"
        directory = Path(settings.UPLOAD_DIR) / str(self.workspace_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / key).write_bytes(data)
        self.written += 1
        self.bytes_written += len(data)
        self._pending.append(key)
        return key

    def bind_pending(self, document_id: int) -> None:
        """把自上次绑定以来落盘的附件登记到该文档（下载按文档权限校验）."""
        if not self._pending:
            return
        for key in self._pending:
            self.db.add(
                FileOwner(
                    file_key=key,
                    workspace_id=self.workspace_id,
                    document_id=document_id,
                    uploaded_by_id=getattr(self.user, "id", None),
                )
            )
        self._pending.clear()
        self.db.commit()


def _folder_groups(docs: Iterable[ImportedDoc]) -> set[tuple[str, ...]]:
    """所有文档所在目录（去重）。"""
    return {tuple(doc.path.split("/")[:-1]) for doc in docs}


def _preview_folders(
    siblings: dict[int, dict[str, Document]], root_key: int, folders: set[tuple[str, ...]]
) -> tuple[list[dict[str, Any]], dict[tuple[str, ...], int]]:
    """计算待建文件夹与「目录 → 节点 id」映射（新建的用负 id 占位）."""
    preview: list[dict[str, Any]] = []
    folder_ids: dict[tuple[str, ...], int] = {}
    for folder in sorted(folders, key=lambda f: (len(f), f)):
        parent = root_key
        for chain in _folder_chain(folder):
            if chain in folder_ids:
                parent = folder_ids[chain]
                continue
            existing = _existing_child(siblings, parent, chain[-1])
            if existing is not None and existing.is_folder:
                folder_ids[chain] = existing.id
                parent = existing.id
                continue
            fake = -(len(folder_ids) + 1)
            folder_ids[chain] = fake
            preview.append({"path": "/".join(chain), "title": chain[-1], "status": "new"})
            parent = fake
    return preview, folder_ids


def _expand_mhtml_resources(items: list[UploadedItem]) -> list[UploadedItem]:
    """OFF 态预扫描：把每个 MHTML 的图片素材追加为批次图片条目（ADR 0049 D4）.

    素材路径为 ``<md目录>/_assets/<素材名>``，走原件族路径落为 `_assets` 文件夹下的
    图片文档；坏例不在此处理（留给 ``convert_file`` 统一计 skipped）。
    """
    expanded = list(items)
    for item in items:
        if Path(item.path).suffix.lower() not in reader.MHTML_SUFFIXES:
            continue
        try:
            _, resources = mhtml_converter.parse_mhtml(item.data)
        except UnsupportedImport:
            continue
        folder = posixpath.dirname(item.path)
        for name, _, _, payload in resources:
            expanded.append(UploadedItem(path=posixpath.join(folder, mhtml_converter.ASSET_DIR, name), data=payload))
    return expanded


def analyze_files(
    db: Session,
    workspace_id: int,
    user: Any,
    items: list[UploadedItem],
    *,
    parent_id: int | None = None,
    image_sink: reader.ImageSink | None = None,
) -> dict[str, Any]:
    """解析批次并返回导入预览（不写任何数据）."""
    content_service.require_editor(db, workspace_id, user)
    _validate_parent(db, workspace_id, parent_id)
    reader.validate_batch(items)

    docs, skipped = reader.convert_batch(items, image_sink=image_sink)
    siblings = _sibling_map(db, workspace_id)
    root_key = parent_id or 0
    folders, folder_ids = _preview_folders(siblings, root_key, _folder_groups(docs))

    preview_items: list[dict[str, Any]] = []
    conflicts = 0
    for doc in sorted(docs, key=lambda d: d.path):
        folder = tuple(doc.path.split("/")[:-1])
        parent = folder_ids.get(folder, root_key)
        existing = None if parent < 0 else _existing_child(siblings, parent, doc.title)
        if existing is not None:
            conflicts += 1
        if len(preview_items) < PREVIEW_LIMIT:
            preview_items.append(
                {
                    "path": doc.path,
                    "title": doc.title,
                    "folder": "/".join(folder),
                    "suffix": doc.suffix,
                    "format": doc.content_type,
                    "is_asset": doc.asset,
                    "status": "conflict" if existing is not None else "new",
                    "existing_document_id": existing.id if existing is not None else None,
                    "warnings": doc.warnings[:5],
                }
            )

    warnings = [{"path": doc.path, "message": message} for doc in docs for message in doc.warnings]
    return {
        "total_files": len(items),
        "total_documents": len(docs),
        "total_folders": len(folders),
        "assets": sum(1 for doc in docs if doc.asset),
        "conflicts": conflicts,
        "skipped": skipped[:DETAIL_LIMIT],
        "warnings": warnings[:DETAIL_LIMIT],
        "folders": folders[:PREVIEW_LIMIT],
        "items": preview_items,
        "preview_truncated": len(preview_items) < len(docs),
    }


def import_files(
    db: Session,
    workspace_id: int,
    user: Any,
    items: list[UploadedItem],
    *,
    parent_id: int | None = None,
    conflict: str = CONFLICT_RENAME,
    status: str = "draft",
    import_attachments: bool = True,
) -> dict[str, Any]:
    """把上传的文件批次导入为文档树（文件夹 + 文档 + 附件）."""
    if conflict not in CONFLICT_POLICIES:
        raise BadRequestError(f"不支持的冲突策略：{conflict}，可选 {'/'.join(CONFLICT_POLICIES)}")
    if status not in DOC_STATUSES:
        raise BadRequestError(f"不支持的文档状态：{status}")

    content_service.require_editor(db, workspace_id, user)
    _validate_parent(db, workspace_id, parent_id)
    reader.validate_batch(items)

    store = _UploadStore(db, workspace_id, user, enabled=import_attachments)
    siblings = _sibling_map(db, workspace_id)
    root_key = parent_id or 0
    folder_ids: dict[tuple[str, ...], int] = {}
    created_folders = 0

    def ensure_folder(folder: tuple[str, ...]) -> int:
        nonlocal created_folders
        parent = root_key
        for chain in _folder_chain(folder):
            known = folder_ids.get(chain)
            if known is not None:
                parent = known
                continue
            existing = _existing_child(siblings, parent, chain[-1])
            if existing is not None and existing.is_folder:
                folder_ids[chain] = existing.id
                parent = existing.id
                continue
            order = len(siblings.get(parent, {}))
            title = _next_title(siblings, parent, chain[-1])
            created = content_service.create_document(
                db,
                workspace_id,
                user,
                title=title,
                is_folder=True,
                parent_id=(parent or None),
                status=status,
                sort_order=order,
            )
            folder_ids[chain] = created.id
            siblings.setdefault(parent, {})[title.strip().lower()] = created
            created_folders += 1
            parent = created.id
        return parent

    stats: dict[str, Any] = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "folders_created": 0,
        "attachments": 0,
        "attachment_bytes": 0,
        "assets": 0,
        "documents": [],
        "skipped_files": [],
        "warnings": [],
    }

    if not import_attachments:
        # 关态：素材展开为批次图片条目，落为 _assets 文件夹图片文档（ADR 0049 D4）
        items = _expand_mhtml_resources(items)

    local_images = reader.build_local_image_index(items)
    for item in sorted(items, key=lambda entry: entry.path):
        try:
            doc = reader.convert_file(item, image_sink=store.store, local_images=local_images)
        except UnsupportedImport as exc:
            stats["skipped"] += 1
            if len(stats["skipped_files"]) < DETAIL_LIMIT:
                stats["skipped_files"].append({"path": item.path, "reason": str(exc)})
            continue

        for message in doc.warnings:
            if len(stats["warnings"]) < DETAIL_LIMIT:
                stats["warnings"].append({"path": item.path, "message": message})

        folder = tuple(doc.path.split("/")[:-1])
        parent = ensure_folder(folder)
        title = doc.title
        existing = _existing_child(siblings, parent, title)

        if existing is not None and existing.is_folder:
            title = _next_title(siblings, parent, title)
            existing = None
        elif existing is not None and conflict == CONFLICT_SKIP:
            stats["skipped"] += 1
            if len(stats["skipped_files"]) < DETAIL_LIMIT:
                stats["skipped_files"].append({"path": item.path, "reason": "同名文档已存在"})
            continue
        elif existing is not None and conflict == CONFLICT_RENAME:
            title = _next_title(siblings, parent, title)
            existing = None

        if doc.asset:
            # 原件族：同名 Markdown 文档不被覆盖（避免把可编辑正文换成只读原件），按改名处理
            if existing is not None and existing.content_type not in ASSET_CONTENT_TYPES:
                title = _next_title(siblings, parent, title)
                existing = None
            saved = _save_asset(db, workspace_id, user, store, item, doc, existing, parent, title, status, siblings)
            stats["assets"] += 1
            if existing is not None:
                stats["updated"] += 1
            else:
                stats["created"] += 1
        elif existing is not None:
            saved = content_service.update_content(
                db,
                workspace_id,
                existing.id,
                user,
                content=doc.body,
                change_summary="从文件导入覆盖",
                change_type=CHANGE_TYPE_IMPORT,
            )
            stats["updated"] += 1
        else:
            order = len(siblings.get(parent, {}))
            saved = content_service.create_document(
                db,
                workspace_id,
                user,
                title=title,
                content=doc.body,
                parent_id=(parent or None),
                status=status,
                sort_order=order,
                change_type=CHANGE_TYPE_IMPORT,
            )
            siblings.setdefault(parent, {})[title.strip().lower()] = saved
            stats["created"] += 1

        store.bind_pending(saved.id)
        if len(stats["documents"]) < RESULT_DOCS_LIMIT:
            stats["documents"].append(
                {"id": saved.id, "title": saved.title, "path": item.path, "format": saved.content_type}
            )

    stats["folders_created"] = created_folders
    stats["attachments"] = store.written - store.asset_written
    stats["attachment_bytes"] = store.bytes_written - store.asset_bytes
    stats["total"] = stats["created"] + stats["updated"] + stats["skipped"]
    return stats


def _save_asset(
    db: Session,
    workspace_id: int,
    user: Any,
    store: _UploadStore,
    item: UploadedItem,
    doc: reader.ImportedDoc,
    existing: Document | None,
    parent: int,
    title: str,
    status: str,
    siblings: dict[int, dict[str, Document]],
) -> Document:
    """原件族落库：写原件 + 建/替换文档节点（复用既有身份证与归属登记）."""
    key = store.store_asset(item.data, item.path)
    size = len(item.data)
    if existing is not None:
        previous = existing.asset_file_key
        saved = content_service.replace_document_asset(
            db,
            workspace_id,
            existing.id,
            user,
            asset_file_key=key,
            asset_mime=doc.mime,
            content_size=size,
        )
        if previous and previous != key:
            _drop_previous_asset(db, workspace_id, previous)
        return saved

    order = len(siblings.get(parent, {}))
    saved = content_service.create_document(
        db,
        workspace_id,
        user,
        title=title,
        content="",
        parent_id=(parent or None),
        status=status,
        sort_order=order,
        change_type=CHANGE_TYPE_IMPORT,
        content_type=doc.content_type,
        asset_file_key=key,
        asset_mime=doc.mime,
        content_size=size,
    )
    siblings.setdefault(parent, {})[title.strip().lower()] = saved
    return saved


def _drop_previous_asset(db: Session, workspace_id: int, file_key: str) -> None:
    """覆盖导入后清理旧原件（文件 + 归属登记），避免孤儿占用存储配额."""
    from cndb.plugins.files.services import forget_owner, remove_workspace_file

    forget_owner(db, file_key)
    remove_workspace_file(workspace_id, file_key)


__all__ = ["analyze_files", "import_files"]
