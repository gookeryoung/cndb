"""cndb docs 子命令 —— 文档数据运维（外存内容体检与物理回收）.

子命令：
- gc    外存孤儿文件体检 / 回收（默认 dry-run，--apply 才实际删除）

CLI 是运维侧工具，调用者已具备服务端文件系统访问权限，等价于超级管理员。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy.orm import Session


def _get_session() -> Session:
    """按当前 settings.DATABASE_URL 打开一个 DB session.

    每次调用新建 engine（与 ``cndb users`` 一致），保证 monkeypatch settings 的
    测试能拿到独立 DB；目标库缺少 documents 表时按 ORM 元数据建表兜底。
    """
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker

    import cndb.plugins.documents.models  # noqa: F401  确保 Base.metadata 完整
    from cndb.core.config import settings
    from cndb.core.database import register_sqlite_pragmas
    from cndb.models.base import Base

    connect_args: dict[str, Any] = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, echo=settings.DEBUG)
    if "sqlite" in settings.DATABASE_URL:
        register_sqlite_pragmas(engine)
    if not inspect(engine).has_table("documents_document"):
        Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def cmd_gc(args: argparse.Namespace) -> dict[str, Any]:
    """执行外存体检/回收，返回可序列化报告."""
    from cndb.plugins.documents.services.storage import purge_external_orphans

    db = _get_session()
    try:
        report = purge_external_orphans(db, dry_run=not getattr(args, "apply", False))
    finally:
        db.close()
    return {
        "root": str(report.root),
        "dry_run": report.dry_run,
        "referenced_files": report.referenced_files,
        "missing_files": [str(path) for path in report.missing_files],
        "orphan_files": [
            {"path": str(item.path), "size": item.size, "reason": item.reason} for item in report.orphan_files
        ],
        "orphan_bytes": report.orphan_bytes,
        "removed_files": report.removed_files,
        "removed_dirs": report.removed_dirs,
    }


def _print_gc(payload: dict[str, Any]) -> None:
    mode = "体检（dry-run，未删除）" if payload["dry_run"] else "回收"
    print(f"[docs gc] 外存根目录: {payload['root']} — {mode}")
    print(
        f"[docs gc] 有效引用文件 {payload['referenced_files']} 个，"
        f"丢失 {len(payload['missing_files'])} 个，孤儿 {len(payload['orphan_files'])} 个"
        f"（{payload['orphan_bytes']} 字节）"
    )
    for item in payload["orphan_files"]:
        print(f"  - {item['path']} ({item['size']} 字节, {item['reason']})")
    for path in payload["missing_files"]:
        print(f"  ! 丢失: {path}")
    if payload["dry_run"] and payload["orphan_files"]:
        print("[docs gc] 加 --apply 执行删除")
    elif not payload["dry_run"]:
        print(f"[docs gc] 已删除文件 {payload['removed_files']} 个，清理空目录 {payload['removed_dirs']} 个")


def docs_command(args: argparse.Namespace) -> None:
    """分发 ``cndb docs <sub>``."""
    cmd = getattr(args, "docs_cmd", None)
    if cmd is None:
        print("[error] 缺少 docs 子命令，可用: gc", file=sys.stderr)
        sys.exit(2)
    if cmd == "gc":
        payload = cmd_gc(args)
        if getattr(args, "json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_gc(payload)
        return
    print(f"[error] 未知 docs 子命令: {cmd}", file=sys.stderr)  # pragma: no cover - argparse 已收窄
    sys.exit(2)


def register_docs_subparser(sub: Any) -> None:
    """向顶层 ArgumentParser 注册 `cndb docs` 子命令组."""
    p_docs = sub.add_parser("docs", help="文档数据运维（gc：外存孤儿文件体检与回收）")
    docs_sub = p_docs.add_subparsers(dest="docs_cmd")

    p_gc = docs_sub.add_parser("gc", help="外存内容体检/回收（默认仅体检，不删除）")
    p_gc.add_argument("--apply", action="store_true", help="实际删除孤儿文件（默认 dry-run）")
    p_gc.add_argument("--json", action="store_true", help="以 JSON 输出报告")


__all__ = ["cmd_gc", "docs_command", "register_docs_subparser"]
