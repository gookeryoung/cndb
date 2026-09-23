"""数据备份模块.

提供完整的数据备份能力，覆盖：
1. SQLite 数据库文件（使用 sqlite3.Connection.backup 热备份，无需停服）
2. uploads 目录下的所有附件文件

输出格式为 ``.tar.gz`` 归档，包含 ``manifest.json`` 元信息供恢复端校验。

备份模式：
- ``native``（默认）：直接备份数据库文件，速度最快，仅 SQLite 可用
- ``sqlalchemy``：通过 SQLAlchemy 序列化所有表数据，跨数据库兼容

归档结构::

    backup-<timestamp>.tar.gz
    ├── manifest.json          # 备份元信息（版本、时间、表清单、文件统计、schema 版本）
    ├── database/              # 数据库备份
    │   ├── cndb.db            # native 模式下的原始文件（SQLite）
    │   └── dump.json          # sqlalchemy 模式下的 JSON 导出
    └── uploads/               # 附件文件目录（按 workspace_id 隔离）
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

__all__ = ["BackupError", "BackupManifest", "create_backup"]

MANIFEST_VERSION = "1"  # 当前 manifest 协议版本，restore 端检查此值做兼容性判断


class BackupError(RuntimeError):
    """备份过程中的业务错误基类."""


@dataclass
class UploadsInfo:
    """uploads 目录统计信息."""

    included: bool = False
    file_count: int = 0
    total_size: int = 0


@dataclass
class DatabaseInfo:
    """数据库备份统计."""

    path: str = ""
    db_type: str = "sqlite"
    backup_mode: str = "native"
    tables: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)
    # 备份时数据所处的 alembic schema 版本（空串表示无迁移记录，如旧版备份或手动建表库）
    schema_version: str = ""
    # 内嵌兜底导出的恢复模式（native 备份内嵌 dump.json 时为 "sqlalchemy"，
    # 供不支持 native 备份 schema 的程序按交集导入恢复；空串表示无兜底导出）
    fallback_mode: str = ""


@dataclass
class BackupManifest:
    """备份元信息（序列化写入 manifest.json）."""

    version: str = MANIFEST_VERSION
    app_version: str = ""
    created_at: str = ""
    database: DatabaseInfo = field(default_factory=DatabaseInfo)
    uploads: UploadsInfo = field(default_factory=UploadsInfo)


def _is_sqlite_url(database_url: str) -> bool:
    """判断 DATABASE_URL 是否为 SQLite."""
    parsed = urlparse(database_url)
    return parsed.scheme.startswith("sqlite")


def _resolve_sqlite_path(database_url: str) -> Path:
    """从 SQLite DATABASE_URL 解析出实际文件路径."""
    # sqlite:///absolute/path/to/db → absolute/path/to/db
    # sqlite:///./relative/path  → 处理相对路径
    parsed = urlparse(database_url)
    # netloc 为空时，path 开头已有斜杠
    path_str = parsed.path
    # 去掉前导斜杠（sqlite:/// 产生三个斜杠）
    if path_str.startswith("/"):
        path_str = path_str[1:]
    return Path(path_str).resolve()


def _read_schema_version_sqlite(conn: sqlite3.Connection) -> str:
    """从 SQLite 连接读取 alembic_version 表的 version_num.

    Returns:
        schema 版本号；alembic_version 表不存在或为空时返回空串.
    """
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.OperationalError:
        return ""
    return str(row[0]) if row else ""


def _backup_sqlite_native(db_path: Path, target_dir: Path) -> tuple[str, dict[str, int], str]:
    """使用 sqlite3 的 backup() API 热备份数据库文件.

    Returns:
        (备份文件名, 表名 → 行数 映射, 备份库的 schema 版本)
    """
    dest = target_dir / "cndb.db"
    # 使用 sqlite3.Connection.backup() 做联机备份
    src_conn = sqlite3.connect(str(db_path))
    try:
        dest_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()

    # 统计表行数 + 读取 schema 版本
    row_counts: dict[str, int] = {}
    conn = sqlite3.connect(str(dest))
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        for table in tables:
            count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            row_counts[table] = count
        schema_version = _read_schema_version_sqlite(conn)
    finally:
        conn.close()
    return "cndb.db", row_counts, schema_version


def _coerce_raw_value(raw: Any, column_type: Any) -> Any:
    """将 SQLite 原生返回值安全转换为 Python 类型.

    SQLite 是动态类型系统，声明为 TIMESTAMP/DATETIME 的列实际可能存了：
    - ISO 格式字符串（SQLAlchemy 的 str_to_date 能处理）
    - NULL（处理器已做 null 检查）
    - Unix 时间戳（int / float）—— str_to_date 直接 ``fromisoformat(int)`` 炸
    - 空字符串 —— ``fromisoformat('')`` 抛 ValueError

    因此绕开 SQLAlchemy 的自动 processor，用原生 SQL 拉值后按列声明类型手动转换.
    """
    import datetime as dt

    from sqlalchemy.types import Date, DateTime, Time

    if raw is None:
        return None

    if isinstance(column_type, DateTime):
        if isinstance(raw, dt.datetime):
            return raw
        if isinstance(raw, (int, float)):
            return dt.datetime.fromtimestamp(raw)
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return None
            try:
                return dt.datetime.fromisoformat(s)
            except ValueError:
                # 兼容 SQLite 原生格式 'YYYY-MM-DD HH:MM:SS'
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
                    try:
                        return dt.datetime.strptime(s, fmt)
                    except ValueError:
                        continue
                return raw  # 无法解析则原样保留
        # bytes / 其他类型 —— 让 _to_json_safe 兜底

    elif isinstance(column_type, Date):
        if isinstance(raw, dt.date):
            return raw
        if isinstance(raw, (int, float)):
            return dt.date.fromtimestamp(raw)
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return None
            try:
                return dt.date.fromisoformat(s)
            except ValueError:
                return raw

    elif isinstance(column_type, Time):
        if isinstance(raw, dt.time):
            return raw
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return None
            try:
                return dt.time.fromisoformat(s)
            except ValueError:
                return raw

    return raw


def _backup_sqlalchemy(database_url: str, target_dir: Path) -> tuple[str, dict[str, int], list[str], str]:
    """通过 SQLAlchemy 序列化所有表数据（跨数据库兼容）.

    绕过 SQLAlchemy DateTime/Date/Time 列的自动 processor，改用原生 SQL 拉取
    SQLite 原始值（避免动态类型库中 Unix 时间戳、空字符串等非法输入让
    ``str_to_date`` / ``str_to_datetime`` 崩溃），再按反射出的列声明类型手动转换.

    Returns:
        (备份文件名, 表名 → 行数 映射, 表清单, 源库 schema 版本)
    """
    from sqlalchemy import MetaData, create_engine, text
    from sqlalchemy.exc import SQLAlchemyError

    from cndb.core.plugin_registry import plugin_registry

    plugin_registry.discover_and_load()

    engine = create_engine(database_url)
    try:
        metadata = MetaData()
        metadata.reflect(bind=engine)
        tables_info: list[dict[str, Any]] = []
        row_counts: dict[str, int] = {}
        schema_version = ""

        with engine.connect() as conn:
            for table_name in sorted(metadata.tables.keys()):
                sa_table = metadata.tables[table_name]
                # 反射列名（按顺序）+ 列类型字典，用于后续安全转换
                columns = [str(c.name) for c in sa_table.columns]
                col_types: dict[str, Any] = {str(c.name): c.type for c in sa_table.columns}
                # 统计行数
                count = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar() or 0
                row_counts[table_name] = count
                # 用原生 SQL 拉取原始值，绕开 DateTime 列的 str_to_date processor
                # 该 processor 假定 SQLite 返回 ISO 字符串，遇到 Unix 时间戳（int）会直接 TypeError
                rows = [
                    dict(raw_row) for raw_row in conn.execute(text(f'SELECT * FROM "{table_name}"')).mappings().all()
                ]
                if len(rows) > 1_000_000:
                    print(f"[backup] 警告：表 {table_name} 行数 {len(rows)} 超过一百万，序列化体积较大")
                # 按声明类型安全转换后再做 JSON safe 序列化
                clean_rows = [
                    {str(k): _to_json_safe(_coerce_raw_value(v, col_types.get(str(k)))) for k, v in row.items()}
                    for row in rows
                ]
                tables_info.append({"table": table_name, "columns": columns, "rows": clean_rows})
            # 读取源库 schema 版本（alembic_version 表不存在时静默跳过）
            try:
                schema_version = str(conn.execute(text("SELECT version_num FROM alembic_version")).scalar() or "")
            except SQLAlchemyError:
                schema_version = ""

        dump = {"tables": tables_info}
    finally:
        engine.dispose()

    dest = target_dir / "dump.json"
    dest.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
    return "dump.json", row_counts, sorted(metadata.tables.keys()), schema_version


def _to_json_safe(value: Any) -> Any:
    """将 datetime/bytes/Decimal/UUID 等不可 JSON 序列化的类型转为安全值.

    约定用 ``{"__tag__": ...}`` 形式携带还原信号，与 bytes 的 ``__base64__`` 一致。
    """
    import uuid
    from decimal import Decimal

    if value is None:
        return None
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        import base64

        return {"__base64__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _collect_uploads(upload_dir: Path, target_dir: Path) -> UploadsInfo:
    """收集 uploads 目录并复制到目标临时目录.

    保留子目录结构（按 workspace_id 隔离）。空目录自动跳过。
    """
    info = UploadsInfo(included=False, file_count=0, total_size=0)
    if not upload_dir.is_dir():
        return info

    target_uploads = target_dir / "uploads"
    target_uploads.mkdir(parents=True, exist_ok=True)

    for root, dirs, files in os.walk(upload_dir):
        # 跳过隐藏目录
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if fname.startswith("."):
                continue
            src_file = Path(root) / fname
            rel_path = src_file.relative_to(upload_dir)
            dst_file = target_uploads / rel_path
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            info.file_count += 1
            info.total_size += src_file.stat().st_size

    if info.file_count > 0:
        info.included = True
    return info


def _make_tar_archive(source_dir: Path, output_path: Path) -> None:
    """将 source_dir 打包为 output_path（.tar.gz）.

    使用 GNU 长文件格式以支持 Windows 下的长路径。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_path, "w:gz", format=tarfile.GNU_FORMAT) as tar:
        tar.add(source_dir, arcname="backup")


def _copy_to_directory(source_dir: Path, output_dir: Path) -> None:
    """将 source_dir 完整复制到 output_dir.

    output_dir 不存在则创建；存在时要求为空目录，避免与已有文件冲突。
    目录模式下，manifest.json、database/、uploads/ 直接位于 output_dir 根下。
    """
    if output_dir.exists():
        if not output_dir.is_dir():
            raise BackupError(f"输出路径已存在且不是目录: {output_dir}")
        # 允许已存在但为空的目录（常见于文件选择对话框选定的目标）
        existing = list(output_dir.iterdir())
        if existing:
            raise BackupError(f"输出目录已包含文件，请选择空目录: {output_dir}")
    else:
        output_dir.mkdir(parents=True)

    for item in source_dir.iterdir():
        dst = output_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dst)
        else:
            shutil.copy2(item, dst)


def _total_size(path: Path) -> int:
    """计算目录或文件总字节数."""
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _detect_format(output: Path) -> str:
    """根据 output 后缀判断输出格式 — ``archive`` 或 ``directory``.

    ``.tar.gz`` / ``.tgz`` → archive；其它一律视为目录（让调用方也能显式指定）。
    """
    name = output.name.lower()
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return "archive"
    return "directory"


def create_backup(
    output: Path | None = None,
    mode: str = "auto",
    include_uploads: bool = True,
    database_url: str | None = None,
    upload_dir: Path | None = None,
    fmt: str | None = None,
    include_fallback: bool = True,
) -> Path:
    """创建完整数据备份.

    Args:
        output: 输出路径 — ``archive`` 模式下是 ``.tar.gz`` 文件路径；``directory`` 模式下是目标目录。
            默认按格式生成文件名：``backup-<timestamp>.tar.gz``（归档）或 ``backup-<timestamp>``（目录）.
        mode: 备份模式 — ``auto``（SQLite 用 native，其它 sqlalchemy）/ ``native`` / ``sqlalchemy``.
        include_uploads: 是否包含 uploads 目录附件.
        database_url: 覆盖 settings.DATABASE_URL（测试用）.
        upload_dir: 覆盖 settings.UPLOAD_DIR（测试用）.
        fmt: 输出格式 — ``archive`` / ``directory``. 默认 None，自动根据 output 后缀推断；
            若 output 未指定则默认 archive。
        include_fallback: native 模式是否内嵌 sqlalchemy 兜底导出（dump.json）。
            内嵌后归档体积增大，但旧版程序或 native 恢复失败时可用 sqlalchemy
            模式按交集导入恢复（降级恢复，丢弃新版字段数据）；超大库可关闭。

    Returns:
        备份产物的绝对路径（归档文件或目录）.

    Raises:
        BackupError: 备份过程中的业务错误（DB 不可用、路径不存在等）.
    """
    import cndb
    from cndb.core.config import settings

    db_url = database_url or settings.DATABASE_URL
    up_dir = upload_dir or settings.UPLOAD_DIR
    is_sqlite = _is_sqlite_url(db_url)

    # 解析最终使用的模式
    resolved_mode = mode
    if mode == "auto":
        resolved_mode = "native" if is_sqlite else "sqlalchemy"
    if resolved_mode == "native" and not is_sqlite:
        raise BackupError("native 备份模式仅支持 SQLite，当前数据库类型不支持，请使用 --mode sqlalchemy")

    # 解析输出格式
    if fmt is not None:
        resolved_fmt = fmt
    elif output is not None:
        resolved_fmt = _detect_format(output)
    else:
        resolved_fmt = "archive"

    # 设置默认输出路径
    if output is None:
        ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        if resolved_fmt == "archive":
            output = Path(f"backup-{ts}.tar.gz").resolve()
        else:
            output = Path(f"backup-{ts}").resolve()
    else:
        output = Path(output).resolve()

    # 临时目录：拼装 manifest / database / uploads 后一次性打包
    temp_root = Path(tempfile.mkdtemp(prefix="cndb-backup-"))
    try:
        db_dir = temp_root / "database"
        db_dir.mkdir()

        manifest = BackupManifest(
            app_version=cndb.__version__,
            created_at=dt.datetime.now(dt.UTC).isoformat(),
            database=DatabaseInfo(db_type="sqlite" if is_sqlite else "other", backup_mode=resolved_mode),
        )

        print(f"[backup] 模式: {resolved_mode}，数据库: {db_url}")

        # 1) 备份数据库
        if resolved_mode == "native":
            db_path = _resolve_sqlite_path(db_url)
            if not db_path.is_file():
                raise BackupError(f"SQLite 数据库文件不存在: {db_path}")
            db_file, row_counts, schema_version = _backup_sqlite_native(db_path, db_dir)
            manifest.database.path = db_file
            manifest.database.tables = sorted(row_counts.keys())
            manifest.database.row_counts = row_counts
            manifest.database.schema_version = schema_version
            # 内嵌兜底导出：从一致性快照（而非源库）生成 dump.json，
            # 保证与 .db 产物数据一致；旧版程序可按交集导入降级恢复
            if include_fallback:
                _backup_sqlalchemy(f"sqlite:///{db_dir / 'cndb.db'}", db_dir)
                manifest.database.fallback_mode = "sqlalchemy"
        else:
            db_file, row_counts, tables, schema_version = _backup_sqlalchemy(db_url, db_dir)
            manifest.database.path = db_file
            manifest.database.tables = tables
            manifest.database.row_counts = row_counts
            manifest.database.schema_version = schema_version

        total_rows = sum(row_counts.values())
        print(f"[backup] 数据库备份完成: {len(row_counts)} 张表, 共 {total_rows} 行")

        # 2) 收集 uploads
        if include_uploads:
            print(f"[backup] 收集附件目录: {up_dir}")
            manifest.uploads = _collect_uploads(up_dir, temp_root)
            if manifest.uploads.included:
                size_kb = manifest.uploads.total_size / 1024
                print(f"[backup] 附件: {manifest.uploads.file_count} 个文件, {size_kb:.1f} KB")
            else:
                print("[backup] uploads 目录为空或不存在，跳过附件备份")

        # 3) 写入 manifest
        manifest_path = temp_root / "manifest.json"
        manifest_path.write_text(json.dumps(asdict(manifest), ensure_ascii=False, indent=2), encoding="utf-8")

        # 4) 输出（归档 / 目录）
        if resolved_fmt == "archive":
            print(f"[backup] 打包归档 → {output}")
            _make_tar_archive(temp_root, output)
            size_mb = output.stat().st_size / 1024 / 1024
            print(f"[backup] 完成！归档大小: {size_mb:.2f} MB")
        else:
            print(f"[backup] 复制到目录 → {output}")
            _copy_to_directory(temp_root, output)
            size_mb = _total_size(output) / 1024 / 1024
            print(f"[backup] 完成！目录大小: {size_mb:.2f} MB")
        return output

    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def backup_command(args: argparse.Namespace) -> None:
    """CLI 命令：``cndb backup``."""
    try:
        output = Path(args.output).resolve() if args.output else None
        include_uploads = not args.no_uploads
        fmt = getattr(args, "format", None)  # argparse 可能用 format / fmt
        if fmt is None and getattr(args, "dir", False):
            fmt = "directory"
        include_fallback = not getattr(args, "no_fallback", False)
        result = create_backup(
            output=output,
            mode=args.mode,
            include_uploads=include_uploads,
            fmt=fmt,
            include_fallback=include_fallback,
        )
        print(f"[ok] 备份成功: {result}")
    except BackupError as exc:
        print(f"[error] {exc}", file=os.sys.stderr)
        os.sys.exit(1)
    except Exception as exc:  # 兜底：捕获并格式化未预期异常
        print(f"[error] 备份失败: {exc}", file=os.sys.stderr)
        os.sys.exit(1)
