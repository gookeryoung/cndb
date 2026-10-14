"""cndb restore 子命令 —— 从备份归档/目录恢复数据库与附件（facade）.

按层次拆到同包：types（异常与结构）/ inspect（体检与 dry-run）/ apply（实际落库）。
本模块只做同名转发，保证 `from cndb.cli.restore import X`（含 tests/test_restore.py
引用的多个私有辅助）与 core/system_api.py、gui/main_window.py 的导入不变。
"""

from __future__ import annotations

from cndb.cli.restore.apply import (
    _dispose_global_engine,
    _extracted_db_dir,
    _from_json_safe,
    _migrate_after_restore,
    _restore_sqlalchemy_json,
    _restore_sqlite_native,
    _restore_uploads,
    restore_backup,
    restore_command,
)
from cndb.cli.restore.inspect import (
    _USER_TABLE_PREFIXES,
    SUPPORTED_MANIFEST_VERSIONS,
    _check_target_safe,
    _detect_backup_format,
    _ensure_manifest_compatible,
    _is_sqlite_url,
    _resolve_sqlite_path,
    classify_table_groups,
    inspect_backup,
)
from cndb.cli.restore.types import (
    BackupInspection,
    RestoreError,
    RestoreLossReport,
    _schema_revision_known,
)

__all__ = [
    "SUPPORTED_MANIFEST_VERSIONS",
    "_USER_TABLE_PREFIXES",
    "BackupInspection",
    "RestoreError",
    "RestoreLossReport",
    "_check_target_safe",
    "_detect_backup_format",
    "_dispose_global_engine",
    "_ensure_manifest_compatible",
    "_extracted_db_dir",
    "_from_json_safe",
    "_is_sqlite_url",
    "_migrate_after_restore",
    "_resolve_sqlite_path",
    "_restore_sqlalchemy_json",
    "_restore_sqlite_native",
    "_restore_uploads",
    "_schema_revision_known",
    "classify_table_groups",
    "inspect_backup",
    "restore_backup",
    "restore_command",
]
