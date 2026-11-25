"""cndb link 子命令 —— 工作区链接的运维入口（ADR 0154 D10）.

子命令：
- ``sweep``  回收过期链接创建的只读成员（cron 每 5 分钟调一次）

示例：
    cndb link sweep                  # 系统 cron：*/5 * * * * cndb link sweep
    cndb link sweep --json           # 机器可读输出
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy.orm import Session


def _get_session() -> Session:
    """按当前 settings.DATABASE_URL 打开 session（与 cndb sync / pipeline 同口径）."""
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker

    import cndb.plugins.accounts.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401
    from cndb.core.config import settings
    from cndb.core.database import register_sqlite_pragmas
    from cndb.models.base import Base

    connect_args: dict[str, Any] = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, echo=settings.DEBUG)
    if "sqlite" in settings.DATABASE_URL:
        register_sqlite_pragmas(engine)
    inspector = inspect(engine)
    if not inspector.has_table("workspaces_workspacelink"):
        Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def cmd_sweep(args: argparse.Namespace) -> dict[str, Any]:
    """回收过期链接（删除其创建的 viewer 成员、置 expired、写事件）."""
    from cndb.plugins.workspaces.services.links import sweep_expired_links

    db = _get_session()
    try:
        return sweep_expired_links(db, limit=args.limit)
    finally:
        db.close()


def _print_sweep(payload: dict[str, Any]) -> None:
    print(f"[link sweep] 过期链接 {payload['expired']} 条")
    for item in payload["details"]:
        print(f"  - link {item['link_id']}: 回收成员 {item['removed_members']} 个")
    if not payload["expired"]:
        print("  （无）")


def register_link_subparser(sub: Any) -> None:
    """向顶层 ArgumentParser 注册 `cndb link` 子命令组."""
    p_link = sub.add_parser("link", help="工作区链接运维（sweep）")
    link_sub = p_link.add_subparsers(dest="link_cmd")

    p_sweep = link_sub.add_parser("sweep", help="回收过期链接创建的只读成员（生产 cron 每 5 分钟）")
    p_sweep.add_argument("--limit", type=int, default=200, help="单次最多处理链接数")
    p_sweep.add_argument("--json", action="store_true", help="以 JSON 输出")


def link_command(args: argparse.Namespace) -> None:
    """分发 ``cndb link <sub>``."""
    cmd = getattr(args, "link_cmd", None)
    if cmd is None:
        print("[error] 缺少 link 子命令，可用: sweep", file=sys.stderr)
        sys.exit(2)
    if cmd != "sweep":  # pragma: no cover - argparse 已收窄
        print(f"[error] 未知 link 子命令: {cmd}", file=sys.stderr)
        sys.exit(2)
    payload = cmd_sweep(args)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        _print_sweep(payload)


__all__ = ["cmd_sweep", "link_command", "register_link_subparser"]
