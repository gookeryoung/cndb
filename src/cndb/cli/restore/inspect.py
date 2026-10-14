"""备份体检：manifest 兼容性、目标安全性、表分组与 dry-run 元信息.

``inspect_backup`` 是外部入口；``classify_table_groups`` 供恢复侧与 system_api 复用。
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import tarfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cndb.cli.restore.types import BackupInspection, RestoreError

SUPPORTED_MANIFEST_VERSIONS = {"1"}

# 用户表物理表名前缀：table_（数据表）/ trash_（行回收站影子表）/ link_（关联字段关联表）。
# 其余为程序固定 ORM 表与迁移版本表（alembic_version），见 plugins/tables/models.py。
_USER_TABLE_PREFIXES = ("table_", "trash_", "link_")


def classify_table_groups(tables: list[str]) -> dict[str, list[str]]:
    """按「系统表 / 用户表」对物理表名分类.

    用户表指用户在应用内创建的动态数据表及其影子表、关联表，物理表名带
    ``table_`` / ``trash_`` / ``link_`` 前缀（见 ``plugins/tables/models.py``）；
    系统表指程序固定的 ORM 表与迁移版本表（如 ``accounts_user``、
    ``workspaces_workspace``、``alembic_version``）.

    Args:
        tables: 物理表名列表（来自 manifest 的 ``database.tables``）.

    Returns:
        ``{"system": [...], "user": [...]}``，两键恒存在；组内保持入参顺序.
    """
    system: list[str] = []
    user: list[str] = []
    for name in tables:
        (user if name.startswith(_USER_TABLE_PREFIXES) else system).append(name)
    return {"system": system, "user": user}


def _is_sqlite_url(database_url: str) -> bool:
    """判断 DATABASE_URL 是否为 SQLite."""
    parsed = urlparse(database_url)
    return parsed.scheme.startswith("sqlite")


def _resolve_sqlite_path(database_url: str) -> Path:
    """从 SQLite DATABASE_URL 解析出实际文件路径."""
    parsed = urlparse(database_url)
    path_str = parsed.path
    if path_str.startswith("/"):
        path_str = path_str[1:]
    return Path(path_str).resolve()


def _ensure_manifest_compatible(manifest: dict[str, Any]) -> None:
    """检查 manifest 版本兼容性.

    版本不在 SUPPORTED_MANIFEST_VERSIONS 集合内时视为不兼容，
    错误信息列出当前支持的全部版本，便于用户判断是否需升级程序。
    """
    version = manifest.get("version", "?")
    if version not in SUPPORTED_MANIFEST_VERSIONS:
        supported = ", ".join(sorted(SUPPORTED_MANIFEST_VERSIONS))
        raise RestoreError(f"不支持的备份版本: {version}（当前支持: {supported}）。请升级程序后再恢复。")


def _check_target_safe(database_url: str, force: bool) -> None:
    """检查目标数据库是否安全可覆盖.

    - SQLite：若 db 文件存在且有数据，未加 --force 时拒绝
    - 其它 DB：直接信任用户（已有数据本身需要 --force 明示）
    """
    if not _is_sqlite_url(database_url):
        return

    db_path = _resolve_sqlite_path(database_url)
    if not db_path.is_file():
        return  # 文件不存在 = 安全

    # 简单检查表是否非空
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [r[0] for r in cursor.fetchall()]
        if not tables:
            return  # 空库 = 安全
        # 有表 → 统计总行数
        total = 0
        for t in tables:
            with contextlib.suppress(sqlite3.Error):
                total += conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]  # nosec B608 - 表名来自 sqlite_master 枚举
        if total > 0 and not force:
            raise RestoreError(
                f"目标数据库已有 {len(tables)} 张表、{total} 行数据。若确认要覆盖，请使用 --force 参数。"
            )
    finally:
        conn.close()


def _detect_backup_format(path: Path) -> str:
    """判断备份源是 ``archive``（.tar.gz）还是 ``directory``（文件夹）."""
    if path.is_dir():
        return "directory"
    name = path.name.lower()
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return "archive"
    # 不是目录也不是已知后缀 → 尝试当归档打开，失败再报错
    return "archive"


def inspect_backup(archive_path: Path) -> BackupInspection:
    """检查备份源（归档或目录）完整性并返回元信息（dry-run 核心）.

    不修改任何文件系统状态，仅验证 tar 可打开、manifest 可读。
    自动根据路径类型识别归档或目录模式。
    """
    archive_path = Path(archive_path).resolve()
    fmt = _detect_backup_format(archive_path)

    if fmt == "directory":
        manifest_path = archive_path / "manifest.json"
        if not manifest_path.is_file():
            raise RestoreError(f"目录备份缺少 manifest.json: {archive_path}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RestoreError(f"manifest.json 不是合法 JSON: {exc}") from exc
        archive_size = sum(f.stat().st_size for f in archive_path.rglob("*") if f.is_file())
        _ensure_manifest_compatible(manifest)
        return BackupInspection(manifest=manifest, archive_size=archive_size)

    # archive 模式
    if not archive_path.is_file():
        raise RestoreError(f"备份归档不存在: {archive_path}")

    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            names = tar.getnames()
            if "backup/manifest.json" not in names:
                raise RestoreError("归档缺少 manifest.json，非合法备份归档")
            manifest_member = tar.getmember("backup/manifest.json")
            manifest_file = tar.extractfile(manifest_member)
            if manifest_file is None:
                raise RestoreError("归档 manifest.json 无法读取")
            manifest = json.loads(manifest_file.read().decode("utf-8"))
    except (tarfile.TarError, OSError, EOFError) as exc:
        # EOFError：gzip 流被截断（如磁盘写满中断下载）时由 zlib 抛出
        raise RestoreError(f"归档损坏或无法打开: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RestoreError(f"manifest.json 不是合法 JSON: {exc}") from exc

    _ensure_manifest_compatible(manifest)
    return BackupInspection(manifest=manifest, archive_size=archive_path.stat().st_size)
