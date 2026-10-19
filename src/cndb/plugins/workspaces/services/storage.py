"""工作区存储用量统计与配额口径.

工作区在磁盘上的占用由两部分构成：

- **附件**：``settings.UPLOAD_DIR/{workspace_id}/`` 下的文件；缩略图缓存位于
  独立的 ``.thumbs/`` 目录，不计入业务占用；
- **文档外存内容**：``data/docs/{doc_id}/`` 下的版本文件，按文档的工作区归属
  汇总（内联在数据库中的文档内容不占用此配额）。

用量按文件系统实际大小汇总，与「空间分配」（配额）保持同一口径。
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


def workspace_attachment_bytes(workspace_id: int) -> int:
    """工作区附件目录占用（字节）."""
    return _dir_size(settings.UPLOAD_DIR / str(workspace_id))


def _docs_root() -> Path:
    """文档外存根目录（运行时读取，兼容测试对 content._DOCS_DIR 的重定向）."""
    from cndb.plugins.documents.services import content as content_service

    return Path(content_service._DOCS_DIR)


def workspace_storage_bytes(db: Session, workspace_id: int) -> int:
    """工作区总占用（字节）：附件 + 文档外存内容."""
    total = workspace_attachment_bytes(workspace_id)

    from cndb.plugins.documents.models import Document

    docs_root = _docs_root()
    doc_ids = db.query(Document.id).filter(Document.workspace_id == workspace_id).all()
    for (doc_id,) in doc_ids:
        total += _dir_size(docs_root / str(doc_id))
    return total


def workspace_quota_bytes(workspace: Any) -> int:
    """读取工作区配额（缺失或非法时回退默认值 100MB）."""
    value = getattr(workspace, "storage_quota_bytes", None)
    if isinstance(value, int) and value >= 0:
        return value
    return DEFAULT_STORAGE_QUOTA_BYTES


__all__ = [
    "workspace_attachment_bytes",
    "workspace_quota_bytes",
    "workspace_storage_bytes",
]
