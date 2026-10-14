"""恢复流程的异常与结果结构（不含任何 I/O）."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class RestoreError(RuntimeError):
    """恢复过程中的业务错误基类."""


@dataclass
class RestoreLossReport:
    """sqlalchemy 降级恢复的数据裁剪报告.

    交集导入时，备份中本地不存在的表被整体跳过、本地不存在的列被丢弃；
    本报告显式呈现这些数据丢失面，避免静默丢数据。
    """

    skipped_tables: list[str] = field(default_factory=list)
    dropped_columns: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_loss(self) -> bool:
        """是否存在数据丢失."""
        return bool(self.skipped_tables or self.dropped_columns)

    def summary(self) -> str:
        """生成人类可读的丢失报告."""
        parts: list[str] = []
        if self.skipped_tables:
            parts.append(f"跳过未知表 {len(self.skipped_tables)} 个: {', '.join(self.skipped_tables)}")
        for table_name, cols in self.dropped_columns.items():
            parts.append(f"表 {table_name} 丢弃列 {len(cols)} 个: {', '.join(cols)}")
        return "\n".join(parts)


@dataclass
class BackupInspection:
    """备份归档检查结果（dry-run 输出）."""

    manifest: dict[str, Any]
    archive_size: int
    temp_extract_path: Path | None = None

    @property
    def summary(self) -> str:
        """生成人类可读的摘要."""
        db = self.manifest.get("database", {})
        up = self.manifest.get("uploads", {})
        schema_version = db.get("schema_version", "")
        parts: list[str] = [
            f"应用版本: {self.manifest.get('app_version', '?')}",
            f"备份时间: {self.manifest.get('created_at', '?')}",
            f"数据库类型: {db.get('db_type', '?')} ({db.get('backup_mode', '?')})",
            f"Schema 版本: {schema_version or '未知（旧版备份）'}",
            f"数据表数: {len(db.get('tables', []))}",
            f"总行数: {sum(db.get('row_counts', {}).values())}",
        ]
        if db.get("backup_mode", "") == "native" and schema_version:
            parts.append("提示: 备份 schema 旧于当前程序时，恢复时将自动迁移至当前 schema")
            if not _schema_revision_known(schema_version):
                parts.append(
                    "提示: 备份 schema 新于当前程序，native 恢复将失败；"
                    "可改用 sqlalchemy 模式降级恢复（丢弃新版本字段数据）"
                )
        fallback = db.get("fallback_mode", "")
        if fallback:
            parts.append(f"内嵌兜底导出: 有（fallback_mode={fallback}，可用 sqlalchemy 模式降级恢复）")
        else:
            parts.append("内嵌兜底导出: 无")
        if up.get("included"):
            parts.append(f"附件: {up.get('file_count', 0)} 个文件, {up.get('total_size', 0)} 字节")
        else:
            parts.append("附件: 未包含")
        parts.append(f"归档大小: {self.archive_size / 1024 / 1024:.2f} MB")
        return "\n".join(f"  {p}" for p in parts)


def _schema_revision_known(revision: str) -> bool:
    """判断 revision 是否存在于当前程序的迁移链上.

    用于检测备份 schema 是否领先于当前程序（备份 revision 不在本地链上
    即意味着备份由更新版本程序生成）。空串（旧版备份无版本记录）返回 False.
    """
    import alembic.script
    from alembic.util.exc import CommandError

    from cndb.core.migrations import _build_config

    if not revision:
        return False
    cfg = _build_config("sqlite:///:memory:")
    try:
        return alembic.script.ScriptDirectory.from_config(cfg).get_revision(revision) is not None
    except CommandError:
        # alembic 对未知 revision 抛 CommandError（"Can't locate revision"）
        return False
