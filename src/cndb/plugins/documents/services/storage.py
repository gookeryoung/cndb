"""文档外存内容体检与物理回收（孤儿文件 GC）.

外存内容按 ``data/docs/{doc_id}/v{n}.md.gz`` 命名（见 ``services.content``）。
有效引用**只来自** ``documents_documentversion``：``content == "" 且 content_size > 0``
的版本按 ``(document_id, version_number)`` 推导文件路径。

- 孤儿文件：落盘但未被任何版本引用（写入中途失败、历史逻辑遗留、手工拷贝等）；
- 丢失文件：版本引用了但文件不在（磁盘损坏/误删），体检时一并报告，**不**由 GC 删除。

安全边界：
- GC 只动文件系统，不改数据库；软删除（回收站）中的文档版本仍在库中，
  其外存文件属于有效引用，不会被回收；彻底删除（purge）已先行清理目录；
- 不跟随符号链接；只回收 ``v{n}.md.gz`` 规范命名的孤儿与位置不规范的文件。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.plugins.documents.models import DocumentVersion
from cndb.plugins.documents.services import content as content_service

logger = logging.getLogger(__name__)

_EXTERNAL_SUFFIX = ".md.gz"


@dataclass(frozen=True)
class OrphanFile:
    """未被任何版本引用的外存文件."""

    path: Path
    size: int
    reason: str


@dataclass
class StorageReport:
    """外存体检 / 回收报告."""

    root: Path
    referenced_files: int = 0
    missing_files: list[Path] = field(default_factory=list)
    orphan_files: list[OrphanFile] = field(default_factory=list)
    dry_run: bool = True
    removed_files: int = 0
    removed_dirs: int = 0

    @property
    def orphan_bytes(self) -> int:
        return sum(item.size for item in self.orphan_files)


def _docs_root() -> Path:
    """当前外存根目录（运行时读取，兼容测试对 content._DOCS_DIR 的重定向）."""
    return Path(content_service._DOCS_DIR)


def scan_external_storage(db: Session, *, root: Path | None = None) -> StorageReport:
    """体检外存目录：返回孤儿文件与丢失文件清单（只读，不删任何东西）.

    Args:
        root: 自定义外存根目录（默认取当前 ``data/docs``）。
    """
    base = Path(root) if root is not None else _docs_root()
    report = StorageReport(root=base)

    rows = db.execute(
        select(DocumentVersion.document_id, DocumentVersion.version_number).where(
            DocumentVersion.content == "",
            DocumentVersion.content_size > 0,
        )
    ).all()
    referenced: set[Path] = {
        content_service._external_version_path(int(doc_id), int(number), base) for doc_id, number in rows
    }

    for path in sorted(referenced):
        if path.is_file():
            report.referenced_files += 1
        else:
            report.missing_files.append(path)

    if not base.is_dir():
        return report

    for entry in sorted(base.iterdir()):
        if entry.is_symlink():
            continue
        if entry.is_file():
            report.orphan_files.append(
                OrphanFile(path=entry, size=entry.stat().st_size, reason="落盘位置不规范（应在文档子目录内）")
            )
            continue
        if not entry.is_dir():
            continue
        for candidate in sorted(entry.iterdir()):
            if candidate.is_symlink() or not candidate.is_file() or candidate in referenced:
                continue
            reason = "失去版本引用" if candidate.name.endswith(_EXTERNAL_SUFFIX) else "命名不规范（非 v{n}.md.gz）"
            report.orphan_files.append(OrphanFile(path=candidate, size=candidate.stat().st_size, reason=reason))
    return report


def purge_external_orphans(db: Session, *, root: Path | None = None, dry_run: bool = True) -> StorageReport:
    """回收孤儿外存文件并清理空文档目录；``dry_run=True`` 时仅体检.

    Returns:
        体检/回收报告：``dry_run`` 标记本次是否实际删除，``removed_files`` /
        ``removed_dirs`` 为实际删除计数。
    """
    report = scan_external_storage(db, root=root)
    report.dry_run = dry_run
    if dry_run:
        return report

    for orphan in report.orphan_files:
        try:
            orphan.path.unlink(missing_ok=True)
            report.removed_files += 1
        except OSError as exc:  # 单文件失败不中断整体回收
            logger.warning("删除孤儿外存文件失败 %s: %s", orphan.path, exc)
            continue

    base = report.root
    if base.is_dir():
        for entry in sorted(base.iterdir()):
            if entry.is_symlink() or not entry.is_dir():
                continue
            try:
                if not any(entry.iterdir()):
                    entry.rmdir()
                    report.removed_dirs += 1
            except OSError as exc:  # 目录非空/被占用属正常，跳过
                logger.warning("清理空外存目录失败 %s: %s", entry, exc)
    return report


__all__ = ["OrphanFile", "StorageReport", "purge_external_orphans", "scan_external_storage"]
