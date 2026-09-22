"""数据恢复模块.

从 ``cndb backup`` 生成的 ``.tar.gz`` 归档中恢复完整数据，包括：
1. SQLite 数据库文件（native 模式下直接覆盖；sqlalchemy 模式下清空重建并导入）
2. uploads 目录下的所有附件文件（清理后重建）

恢复流程::

    1. 校验 tar 归档完整性（列出成员 + 确认 manifest.json 存在）
    2. 检查 manifest 版本兼容性（集合协商，见 SUPPORTED_MANIFEST_VERSIONS）
    3. 确认目标数据库可恢复（检测冲突 —— 有数据且未加 --force 时拒绝）
    4. 解压到临时目录
    5. 恢复数据库（根据 backup_mode 分支）
       - native：恢复旧 schema 备份后自动执行 alembic upgrade head 迁移
       - sqlalchemy：重建当前 schema 导入数据后补写 alembic 版本标记
    6. 恢复 uploads 目录（若备份包含）
    7. 校验并清理临时目录

关键特性：
- 数据库恢复前自动清理旧数据，避免外键冲突
- 支持 dry-run 预览备份内容而不实际恢复
- 旧版本备份在新版本程序上恢复时自动迁移 schema（向前兼容）
- 新版本备份在旧 schema 上以 sqlalchemy 模式降级恢复时，显式输出数据裁剪报告（跳过表/丢弃列）
- uploads 恢复时先清空目标目录，避免残留文件
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

__all__ = ["RestoreError", "RestoreLossReport", "inspect_backup", "restore_backup"]

# 当前支持恢复的 manifest 协议版本集合（向前兼容框架：新版本格式演进时在此追加）
SUPPORTED_MANIFEST_VERSIONS = {"1"}


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
                total += conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        if total > 0 and not force:
            raise RestoreError(
                f"目标数据库已有 {len(tables)} 张表、{total} 行数据。若确认要覆盖，请使用 --force 参数。"
            )
    finally:
        conn.close()


def _reset_sqlite_database(db_path: Path) -> None:
    """清空 SQLite 数据库（删除旧文件并创建空库）."""
    if db_path.exists():
        db_path.unlink()
    # 同时清理 WAL / SHM 等附属文件
    for suffix in ("-wal", "-shm", "-journal"):
        side = Path(str(db_path) + suffix)
        if side.exists():
            side.unlink()
    # 创建空文件
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.close()


def _restore_sqlite_native(extracted_dir: Path, target_db_path: Path) -> None:
    """native 模式：直接用备份的 .db 文件覆盖目标."""
    src_db = extracted_dir / "database" / "cndb.db"
    if not src_db.is_file():
        raise RestoreError(f"native 备份缺失 cndb.db: {src_db}")
    _reset_sqlite_database(target_db_path)
    shutil.copy2(src_db, target_db_path)
    print(f"[restore] SQLite 数据库已恢复 → {target_db_path}")


def _restore_sqlalchemy_json(extracted_dir: Path, database_url: str) -> RestoreLossReport:
    """sqlalchemy 模式：清空重建所有表结构，再按顺序导入数据.

    Returns:
        数据裁剪报告（备份中本地不存在的表与列），供降级恢复显式展示数据丢失面.
    """
    from sqlalchemy import MetaData, create_engine

    from cndb.core.plugin_registry import plugin_registry
    from cndb.models.base import Base

    dump_file = extracted_dir / "database" / "dump.json"
    if not dump_file.is_file():
        raise RestoreError(f"sqlalchemy 备份缺失 dump.json: {dump_file}")

    print("[restore] 读取 sqlalchemy JSON 导出...")
    dump = json.loads(dump_file.read_text(encoding="utf-8"))
    plugin_registry.discover_and_load()

    report = RestoreLossReport()
    engine = create_engine(database_url)
    try:
        # 1) 清库：先 drop_all 再 create_all，获得与 Base.metadata 对齐的空表
        #    （避免旧列残留或新表缺失导致导入失败）
        metadata = MetaData()
        metadata.reflect(bind=engine)
        metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        # 2) 按表顺序导入（JSON 内已按字母序排列）
        tables_data = dump.get("tables", [])
        imported_total = 0
        with engine.begin() as conn:
            for entry in tables_data:
                table_name = entry["table"]
                columns = entry["columns"]
                rows = entry["rows"]
                # 交集导入：本地不存在的表整体跳过、不存在的列丢弃，收集进降级报告
                sa_table = Base.metadata.tables.get(table_name)
                if sa_table is None:
                    print(f"[restore] 跳过未知表: {table_name}（可能来自更新版本）")
                    report.skipped_tables.append(table_name)
                    continue
                valid_cols = {c.name for c in sa_table.columns}
                insert_cols = [c for c in columns if c in valid_cols]
                dropped = sorted(set(columns) - valid_cols)
                if dropped:
                    report.dropped_columns[table_name] = dropped
                if not rows:
                    continue
                # 批量插入
                chunk_size = 500
                for i in range(0, len(rows), chunk_size):
                    chunk = rows[i : i + chunk_size]
                    conn.execute(
                        sa_table.insert(),
                        [{c: _from_json_safe(r.get(c)) for c in insert_cols} for r in chunk],
                    )
                imported_total += len(rows)
                print(f"[restore] 导入表 {table_name}: {len(rows)} 行")
        print(f"[restore] 数据库导入完成: {imported_total} 行")
    finally:
        engine.dispose()
    return report


def _from_json_safe(value: Any) -> Any:
    """还原备份时的 JSON safe 值 —— base64 还原 bytes，decimal 还原 Decimal，iso 字符串还原 datetime/date/time."""
    import re

    if value is None:
        return None
    if isinstance(value, dict):
        if "__base64__" in value:
            import base64

            return base64.b64decode(value["__base64__"])
        if "__decimal__" in value:
            from decimal import Decimal

            return Decimal(value["__decimal__"])
        return value
    if isinstance(value, str):
        # 尝试解析 ISO 时间戳：区分纯日期、纯时间与 datetime
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return dt.date.fromisoformat(value)
            if re.fullmatch(r"\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2})?", value):
                return dt.time.fromisoformat(value)
            if len(value) >= 10:
                return dt.datetime.fromisoformat(value)
        except ValueError:
            pass
    return value


def _migrate_after_restore(database_url: str, backup_schema_version: str) -> None:
    """native 恢复后把旧 schema 迁移到当前程序版本（向前兼容核心步骤）.

    备份的 .db 文件自带其创建时的 alembic_version，upgrade head 会自动
    补齐中间迁移。之后执行 create_all 补建迁移链从未覆盖的新插件表
    （幂等：已存在的表不受影响）。失败（含备份 schema 新于当前程序的
    "Can't locate revision"）时包装为 RestoreError，由上层终止恢复流程。

    Args:
        database_url: 目标数据库 URL.
        backup_schema_version: 备份来源的 schema 版本（仅用于日志展示）.
    """
    from alembic.util.exc import CommandError
    from sqlalchemy import create_engine
    from sqlalchemy.exc import SQLAlchemyError

    from cndb.core import migrations
    from cndb.core.plugin_registry import plugin_registry
    from cndb.models.base import Base

    print(f"[restore] 执行 schema 迁移（备份版本: {backup_schema_version or '未知'} → 当前 head）...")
    try:
        migrations.upgrade_to_head(database_url)
    except (SQLAlchemyError, CommandError) as exc:
        raise RestoreError(
            f"恢复后 schema 迁移失败：备份的 schema 可能新于当前程序，请升级程序后再恢复；"
            f"若备份内嵌了兜底导出（fallback_mode=sqlalchemy），也可改用 sqlalchemy 模式恢复"
            f"（按旧 schema 交集导入，丢弃新版本字段数据）。原始错误: {exc}"
        ) from exc

    # 补建迁移链未覆盖的新插件表（Base.metadata.create_all 只建缺失表，不影响已有表）
    try:
        plugin_registry.discover_and_load()
        engine = create_engine(database_url)
        try:
            Base.metadata.create_all(bind=engine)
        finally:
            engine.dispose()
    except SQLAlchemyError as exc:
        raise RestoreError(f"恢复后补建缺失表失败: {exc}") from exc
    print("[restore] schema 迁移完成")


def _restore_uploads(extracted_dir: Path, target_upload_dir: Path, included: bool) -> int:
    """恢复 uploads 目录.

    - 若备份未包含 uploads → 跳过，返回 0
    - 若目标已存在 → 先清空再复制（避免残留）
    - 备份目录不存在 → 返回 0
    """
    if not included:
        return 0
    src_uploads = extracted_dir / "uploads"
    if not src_uploads.is_dir():
        return 0

    # 清空并重建目标
    if target_upload_dir.exists():
        shutil.rmtree(target_upload_dir)
    target_upload_dir.mkdir(parents=True)

    # 复制（保留子目录结构）
    count = 0
    for src_file in src_uploads.rglob("*"):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(src_uploads)
        dst = target_upload_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst)
        count += 1
    print(f"[restore] 附件已恢复: {count} 个文件 → {target_upload_dir}")
    return count


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
    except (tarfile.TarError, OSError) as exc:
        raise RestoreError(f"归档损坏或无法打开: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RestoreError(f"manifest.json 不是合法 JSON: {exc}") from exc

    _ensure_manifest_compatible(manifest)
    return BackupInspection(manifest=manifest, archive_size=archive_path.stat().st_size)


def restore_backup(
    archive_path: Path,
    force: bool = False,
    database_url: str | None = None,
    upload_dir: Path | None = None,
    mode: str | None = None,
) -> RestoreLossReport | None:
    """从备份源（归档或目录）恢复数据.

    Args:
        archive_path: 备份路径 — ``.tar.gz`` 归档或 ``manifest.json`` 所在的目录.
        force: 强制覆盖已有数据（默认拒绝）.
        database_url: 覆盖 settings.DATABASE_URL（测试用）.
        upload_dir: 覆盖 settings.UPLOAD_DIR（测试用）.
        mode: 覆盖恢复模式 — ``native`` / ``sqlalchemy``. None 时按 manifest 的
            backup_mode 分支。备份 schema 新于当前程序导致 native 恢复失败时，
            可显式指定 ``sqlalchemy`` 按 dump.json 交集导入降级恢复（需备份
            内嵌兜底导出，丢弃新版本字段数据）.

    Returns:
        sqlalchemy 模式的数据裁剪报告（跳过表/丢弃列）；native 模式返回 None.
        有丢失时流程内同时打印报告。

    Raises:
        RestoreError: 恢复过程中的业务错误（版本不兼容、目标不安全等）.
    """
    from cndb.core.config import settings

    archive_path = Path(archive_path).resolve()
    fmt = _detect_backup_format(archive_path)

    if fmt == "archive" and not archive_path.is_file():
        raise RestoreError(f"备份归档不存在: {archive_path}")
    if fmt == "directory" and not archive_path.is_dir():
        raise RestoreError(f"备份目录不存在: {archive_path}")

    db_url = database_url or settings.DATABASE_URL
    up_dir = upload_dir or settings.UPLOAD_DIR

    # 1) 检查备份源 & 读取 manifest
    print(f"[restore] 读取备份（{'目录' if fmt == 'directory' else '归档'}）: {archive_path}")
    inspection = inspect_backup(archive_path)
    manifest = inspection.manifest
    print(f"[restore] 备份版本: {manifest['version']}，应用版本: {manifest['app_version']}")
    print(f"[restore] 创建时间: {manifest['created_at']}")

    db_info = manifest.get("database", {})
    up_info = manifest.get("uploads", {})
    manifest_mode = db_info.get("backup_mode", "native")
    if mode is not None and mode not in ("native", "sqlalchemy"):
        raise RestoreError(f"无效的恢复模式: {mode}（可选: native, sqlalchemy）")
    backup_mode = mode or manifest_mode
    if mode is not None and mode != manifest_mode:
        print(f"[restore] 显式指定恢复模式: {mode}（备份标记: {manifest_mode}）")

    # 2) 安全检查
    _check_target_safe(db_url, force)

    # 3) 准备 extracted 目录
    temp_root: Path | None = None
    if fmt == "archive":
        temp_root = Path(tempfile.mkdtemp(prefix="cndb-restore-"))
        extracted = temp_root / "backup"
    else:
        extracted = archive_path

    try:
        if fmt == "archive":
            print("[restore] 解压归档...")
            assert temp_root is not None  # 类型收窄
            with tarfile.open(archive_path, "r:gz") as tar:
                # filter="data"：跳过可能有安全风险的元数据，但保留正常文件内容（Python 3.12+ 推荐）
                tar.extractall(temp_root, filter="data")

        # 4) 恢复数据库
        from cndb.core import migrations

        loss_report: RestoreLossReport | None = None
        print(f"[restore] 恢复数据库（{backup_mode} 模式）...")
        if _is_sqlite_url(db_url):
            target_db = _resolve_sqlite_path(db_url)
            if backup_mode == "native":
                _restore_sqlite_native(extracted, target_db)
                # 向前兼容：备份来自旧 schema 时，自动迁移到当前程序版本
                _migrate_after_restore(db_url, db_info.get("schema_version", ""))
            else:
                loss_report = _restore_sqlalchemy_json(extracted, db_url)
                # sqlalchemy 恢复走 drop_all + create_all，alembic_version 会被删掉，补标记
                print("[restore] 补写 alembic 版本标记...")
                migrations.stamp_head(db_url)
        else:
            # 非 SQLite —— 只支持 sqlalchemy 模式
            if backup_mode != "sqlalchemy":
                raise RestoreError(f"备份为 {backup_mode} 模式，但当前数据库非 SQLite，无法恢复")
            loss_report = _restore_sqlalchemy_json(extracted, db_url)
            print("[restore] 补写 alembic 版本标记...")
            migrations.stamp_head(db_url)

        # 5) 恢复 uploads
        if up_info.get("included", False):
            _restore_uploads(extracted, up_dir, included=True)
        else:
            print("[restore] 备份未包含附件，跳过 uploads 恢复")

        if loss_report is not None and loss_report.has_loss:
            print("[restore] 降级恢复数据裁剪报告（交集导入丢弃内容）:")
            print(loss_report.summary())

        print("[ok] 恢复完成！")
        return loss_report

    finally:
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)


def restore_command(args: argparse.Namespace) -> None:
    """CLI 命令：``cndb restore``."""
    archive = Path(args.archive).resolve()

    try:
        if args.dry_run:
            inspection = inspect_backup(archive)
            print("[restore-dry-run] 备份归档有效，内容摘要：")
            print(inspection.summary)
            return

        restore_backup(archive, force=args.force, mode=getattr(args, "mode", None))
    except RestoreError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"[error] 恢复失败: {exc}", file=sys.stderr)
        sys.exit(1)
