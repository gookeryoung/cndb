"""工作区存储用量统计与配额口径.

工作区在磁盘上的占用由两部分构成：

- **文件系统内容**：``settings.UPLOAD_DIR/{workspace_id}/`` 下的附件，以及
  ``data/docs/{doc_id}/`` 下的文档外存版本文件；缩略图缓存位于独立的
  ``.thumbs/`` 目录，不计入业务占用；
- **数据库内容**：随工作区落库、不落盘的数据，包括内联在
  ``document_versions.content`` 中的文档正文、``documents_draft`` 个人草稿，
  以及数据表记录（按物理表逐行汇总单元格字节数）。

只有「版本正文内联存储」的文档才在此计入；外存版本（``content == ""`` 且
``content_size > 0``）已由文件系统路径统计过，避免重复计数。

用量按文件系统实际大小 + 数据库内实际存储字节汇总，与「空间分配」（配额）
保持同一口径。
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.plugins.workspaces.models import DEFAULT_STORAGE_QUOTA_BYTES


def _dir_size(path: Path) -> int:
    """递归汇总目录内普通文件字节数（跳过符号链接；不可读文件忽略）."""
    if not path.is_dir():
        return 0
    total = 0
    for entry in path.rglob("*"):
        if entry.is_symlink() or not entry.is_file():
            continue
        with suppress(OSError):
            total += entry.stat().st_size
    return total


def _value_bytes(value: Any) -> int:
    """单个单元格/字符串值的字节数（None 计 0，二进制按实际长度）."""
    if value is None:
        return 0
    if isinstance(value, (bytes, bytearray, memoryview)):
        return len(bytes(value))
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    return len(str(value).encode("utf-8"))


def workspace_attachment_bytes(workspace_id: int) -> int:
    """工作区附件目录占用（字节）."""
    return _dir_size(settings.UPLOAD_DIR / str(workspace_id))


def _docs_root() -> Path:
    """文档外存根目录（运行时读取，兼容测试对 content._DOCS_DIR 的重定向）."""
    from cndb.plugins.documents.services import content as content_service

    return Path(content_service._DOCS_DIR)


def workspace_document_bytes(db: Session, workspace_id: int) -> int:
    """工作区文档内容占用（字节）：数据库内联正文 + 个人草稿."""
    from cndb.plugins.documents.models import Document, DocumentDraft, DocumentVersion

    # 版本正文内联存储：content 非空即为内联（外存版本 content 恒为空串）
    version_rows = (
        db.query(DocumentVersion.content)
        .join(Document, Document.id == DocumentVersion.document_id)
        .filter(
            Document.workspace_id == workspace_id,
            DocumentVersion.content != "",
        )
        .all()
    )
    total = sum(_value_bytes(row[0]) for row in version_rows)

    # 个人草稿：保存不落版本，仅存本表，同样占用数据库空间
    draft_rows = (
        db.query(DocumentDraft.content)
        .join(Document, Document.id == DocumentDraft.document_id)
        .filter(Document.workspace_id == workspace_id)
        .all()
    )
    return total + sum(_value_bytes(row[0]) for row in draft_rows)


def _physical_table_bytes(db: Session, table_name: str) -> int:
    """单张物理表的记录占用（字节）：逐行汇总各单元格字节数（表不存在返回 0）."""
    from sqlalchemy import MetaData, Table

    with suppress(Exception):
        sa_table = Table(table_name, MetaData(), autoload_with=db.get_bind())
        rows = db.execute(sa_table.select()).all()
        return sum(sum(_value_bytes(value) for value in row) for row in rows)
    return 0


def workspace_table_bytes(db: Session, workspace_id: int) -> int:
    """工作区数据表记录占用（字节）：活动物理表 + 行回收站影子表."""
    from cndb.plugins.tables.models import DataTable

    tables = (
        db.query(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed_at.is_(None),
        )
        .all()
    )
    total = 0
    for tbl in tables:
        total += _physical_table_bytes(db, tbl.db_table_name)
        total += _physical_table_bytes(db, tbl.trash_table_name)
    return total


def workspace_storage_bytes(db: Session, workspace_id: int) -> int:
    """工作区总占用（字节）：附件 + 文档（外存文件 + 内联正文）+ 数据表记录."""
    total = workspace_attachment_bytes(workspace_id)

    from cndb.plugins.documents.models import Document

    docs_root = _docs_root()
    doc_ids = db.query(Document.id).filter(Document.workspace_id == workspace_id).all()
    for (doc_id,) in doc_ids:
        total += _dir_size(docs_root / str(doc_id))

    total += workspace_document_bytes(db, workspace_id)
    total += workspace_table_bytes(db, workspace_id)
    return total


def workspace_quota_bytes(workspace: Any) -> int:
    """读取工作区配额（缺失或非法时回退默认值 100MB）."""
    value = getattr(workspace, "storage_quota_bytes", None)
    if isinstance(value, int) and value >= 0:
        return value
    return DEFAULT_STORAGE_QUOTA_BYTES


__all__ = [
    "workspace_attachment_bytes",
    "workspace_document_bytes",
    "workspace_quota_bytes",
    "workspace_storage_bytes",
    "workspace_table_bytes",
]
