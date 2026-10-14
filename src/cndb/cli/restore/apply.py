"""恢复落库：SQLite 原生替换、SQLAlchemy 交集导入、附件恢复与恢复后迁移.

``restore_backup`` 是外部入口；``restore_command`` 是 CLI 子命令入口。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, cast

from cndb.cli.restore.inspect import (
    _check_target_safe,
    _detect_backup_format,
    _is_sqlite_url,
    _resolve_sqlite_path,
    inspect_backup,
)
from cndb.cli.restore.types import RestoreError, RestoreLossReport

logger = logging.getLogger(__name__)


def _dispose_global_engine() -> None:
    """归还并关闭全局 engine 连接池中的闲置连接.

    同进程恢复（Web 管理台 / GUI）场景下，恢复完成后旧连接池中的连接
    可能携带恢复前的库状态（预编译语句、页缓存）；dispose 后新请求会用
    全新连接打开恢复后的库文件，确保读到一致的新数据。
    """
    try:
        from cndb.core.database import engine

        engine.dispose()
        print("[restore] 已重置数据库连接池")
    except Exception as exc:  # pragma: no cover - engine 未初始化等边缘场景
        logger.debug("重置连接池失败（忽略）: %s", exc)


def _extracted_db_dir(extracted_dir: Path) -> Path:
    """定位备份内的数据库目录.

    新版归档使用 ``data/``（与用户数据目录 ~/.cndb/data 命名一致）；
    旧版归档使用 ``database/``，恢复时自动回退兼容.
    """
    for name in ("data", "database"):
        candidate = extracted_dir / name
        if candidate.is_dir():
            return candidate
    return extracted_dir / "data"


def _restore_sqlite_native(extracted_dir: Path, target_db_path: Path) -> None:
    """native 模式：用 SQLite backup API 把备份 .db 的内容恢复到目标.

    使用 ``sqlite3.Connection.backup`` 而非"删除目标文件再复制"：
    - 不删除目标文件 → Windows 下即使服务进程（或同进程连接池）仍持有
      目标文件的打开句柄，恢复也不会因文件占用（WinError 32）而失败；
    - backup API 走 SQLite 自身的页级覆盖协议，会正确推进 change counter
      并重置目标 WAL，持有旧连接的进程在下一个事务即可读到新数据；
    - 目标文件不存在时自动创建。
    """
    src_db = _extracted_db_dir(extracted_dir) / "cndb.db"
    if not src_db.is_file():
        raise RestoreError(f"native 备份缺失 cndb.db: {src_db}")
    target_db_path.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(str(src_db))
    try:
        dst_conn = sqlite3.connect(str(target_db_path))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    print(f"[restore] SQLite 数据库已恢复 → {target_db_path}")


def _restore_sqlalchemy_json(extracted_dir: Path, database_url: str) -> RestoreLossReport:
    """sqlalchemy 模式：清空重建所有表结构，再按顺序导入数据.

    Returns:
        数据裁剪报告（备份中本地不存在的表与列），供降级恢复显式展示数据丢失面.
    """
    from sqlalchemy import MetaData, create_engine

    from cndb.core.plugin_registry import plugin_registry
    from cndb.models.base import Base

    dump_file = _extracted_db_dir(extracted_dir) / "dump.json"
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
            logger.debug("日期时间解析失败，按原始文本处理", exc_info=True)
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
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.exc import SQLAlchemyError

    from cndb.core import migrations
    from cndb.core.plugin_registry import plugin_registry
    from cndb.models.base import Base

    print(f"[restore] 执行 schema 迁移（备份版本: {backup_schema_version or '未知'} → 当前 head）...")

    # 旧版备份（0.1.x 时代）库内无 alembic_version 表，upgrade head 会从 base
    # 重放全部迁移并撞上 "table already exists"；改走 stamp head + create_all
    # + 自愈对齐 schema（与启动期 ensure_db_migrated 的兜底路径同源）
    probe = create_engine(database_url)
    try:
        has_version_table = bool(sa_inspect(probe).has_table("alembic_version"))
    finally:
        probe.dispose()

    if not has_version_table:
        print("[restore] 备份无迁移版本记录（旧版备份），改用 stamp + create_all + 自愈对齐")
        try:
            migrations.stamp_head(database_url)
        except (SQLAlchemyError, CommandError) as exc:
            raise RestoreError(f"恢复后补写迁移版本标记失败: {exc}") from exc
    else:
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

    # schema 自愈：对照 ORM 元数据补建缺列/缺索引。迁移链可能存在缺口
    # （历史上有列只加在 ORM 上没写迁移），仅靠 upgrade head 无法保证
    # 恢复库 schema 与当前模型一致；缺列会让业务查询直接报 no such column。
    try:
        from cndb.core.migrations import heal_schema_drift

        healed = heal_schema_drift(database_url)
        if healed:
            print(f"[restore] schema 自愈补建: {', '.join(healed)}")
    except SQLAlchemyError as exc:
        raise RestoreError(f"恢复后 schema 自愈失败: {exc}") from exc
    print("[restore] schema 迁移完成")


def _restore_uploads(extracted_dir: Path, target_upload_dir: Path, included: bool) -> int:
    """恢复 uploads 目录.

    原子替换策略，避免"先删后复制"中途失败导致旧附件永久丢失：
    1. 先把备份 uploads 完整复制到目标同级临时目录 ``uploads.new``
    2. 全部复制成功后，把旧目录 rename 为 ``uploads.bak``
    3. 把 ``uploads.new`` rename 为正式名
    4. 删除 ``uploads.bak``
    任一步骤失败均回滚——旧目录保持不动或被恢复.

    - 若备份未包含 uploads → 跳过，返回 0
    - 备份目录不存在 → 返回 0
    """
    if not included:
        return 0
    src_uploads = extracted_dir / "uploads"
    if not src_uploads.is_dir():
        return 0

    # 目标同级临时路径（确保与正式目录在同一文件系统，rename 是原子操作）
    target_parent = target_upload_dir.parent
    staging_dir = target_parent / f"{target_upload_dir.name}.new"
    backup_dir = target_parent / f"{target_upload_dir.name}.bak"

    # ── 步骤 1：复制到临时目录 ──
    # 清理残留（上次失败遗留，理论上不应存在）
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    try:
        count = 0
        for src_file in src_uploads.rglob("*"):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(src_uploads)
            dst = staging_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst)
            count += 1
    except Exception:
        # 复制中途失败 — 清理临时目录，旧 uploads 保持不变
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    # ── 步骤 2-4：原子替换 ──
    try:
        if target_upload_dir.exists():
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            target_upload_dir.rename(backup_dir)  # 旧目录 → .bak
        staging_dir.rename(target_upload_dir)  # .new → 正式名py
    except Exception:
        # 替换失败 — 把 .bak 恢复为正式名
        if backup_dir.exists() and not target_upload_dir.exists():
            try:
                backup_dir.rename(target_upload_dir)
            except Exception:  # pragma: no cover - 尽力回滚
                logger.warning("恢复 uploads 回滚失败，旧目录位于 %s", backup_dir)
        # 清理残留的 staging
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    # 成功后删除 .bak
    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)

    print(f"[restore] 附件已恢复: {count} 个文件 → {target_upload_dir}")
    return count


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
            temp_root = cast(Path, temp_root)  # 类型收窄（archive 分支已创建）
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

        # 同进程恢复（Web 管理台 / GUI）：重置连接池，避免旧连接携带恢复前的库状态
        _dispose_global_engine()

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
