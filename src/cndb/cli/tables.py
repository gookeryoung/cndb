"""cndb tables 子命令 —— 行回收站运维（ADR 0139 C5）.

子命令：
- purge-trash   按保留期物理清理回收站里的行（默认 dry-run，--apply 才实际删除）

**为什么需要这个出口**：软删只打标记，行会一直占库；`_trashed_at` 为空的存量已删行
无法推定删除时间，因此「自动清理」把时间未知的行排除在外，只列进 dry-run 报告，
由运维确认后再决定（ADR 0139 D5）。生产用 cron 定时跑 `cndb tables purge-trash --apply`。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy.orm import Session


def _get_session() -> Session:
    """按当前 settings.DATABASE_URL 打开一个 DB session（与 cndb views / docs 一致）."""
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker

    import cndb.plugins.tables.models  # noqa: F401  确保 Base.metadata 完整
    from cndb.core.config import settings
    from cndb.core.database import register_sqlite_pragmas
    from cndb.models.base import Base

    connect_args: dict[str, Any] = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, echo=settings.DEBUG)
    if "sqlite" in settings.DATABASE_URL:
        register_sqlite_pragmas(engine)
    if not inspect(engine).has_table("tables_datatable"):
        Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def cmd_purge_trash(args: argparse.Namespace) -> dict[str, Any]:
    """体检 / 清理回收站过期行，返回可序列化报告."""
    from cndb.plugins.tables.services.core.rows_retention import purge_expired_rows

    db = _get_session()
    try:
        return purge_expired_rows(
            db,
            days=getattr(args, "days", None),
            dry_run=not getattr(args, "apply", False),
            workspace_id=getattr(args, "workspace_id", None),
            table_id=getattr(args, "table_id", None),
        )
    finally:
        db.close()


def _print_report(payload: dict[str, Any]) -> None:
    mode = "体检（dry-run，未删除）" if payload["dry_run"] else "清理"
    if payload["days"] <= 0:
        print("[tables purge-trash] 保留期已关闭（TRASH_RETENTION_DAYS <= 0），未做任何清理")
        return
    print(f"[tables purge-trash] {mode} — 保留期 {payload['days']} 天，截止 {payload['cutoff']}")
    print(
        f"[tables purge-trash] 涉及数据表 {len(payload['tables'])} 张，到期行 {sum(t['expired'] for t in payload['tables'])} 行"
    )
    for item in payload["tables"]:
        print(
            f"  - 工作区 {item['workspace_name']}(id={item['workspace_id']}) / 表 {item['table_name']}"
            f"(id={item['table_id']})：到期 {item['expired']} 行"
            + (f"，已清理 {item['purged']} 行" if not payload["dry_run"] else "")
            + (f"，删除时间未知 {item['unknown_time']} 行（不会自动清理）" if item["unknown_time"] else "")
        )
    if payload["unknown_time"]:
        print(
            f"[tables purge-trash] 另有 {payload['unknown_time']} 行删除时间未知（早期已删行），"
            "按 ADR 0139 D5 不自动清理；确认后请手工按 id 彻底删除"
        )
    if payload["dry_run"] and payload["tables"]:
        print("[tables purge-trash] 加 --apply 执行清理")


def tables_command(args: argparse.Namespace) -> None:
    """分发 ``cndb tables <sub>``."""
    cmd = getattr(args, "tables_cmd", None)
    if cmd is None:  # pragma: no cover - argparse 已要求子命令
        print("[error] 缺少 tables 子命令，可用: purge-trash", file=sys.stderr)
        sys.exit(2)
    if cmd == "purge-trash":
        payload = cmd_purge_trash(args)
        if getattr(args, "json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_report(payload)
        return
    print(f"[error] 未知 tables 子命令: {cmd}", file=sys.stderr)  # pragma: no cover
    sys.exit(2)


def register_tables_subparser(sub: Any) -> None:
    """向顶层 ArgumentParser 注册 `cndb tables` 子命令组."""
    p_tables = sub.add_parser("tables", help="数据表运维（purge-trash：回收站保留期清理）")
    tables_sub = p_tables.add_subparsers(dest="tables_cmd")

    p_purge = tables_sub.add_parser(
        "purge-trash",
        help="按保留期物理清理回收站里的行（默认仅体检，--apply 才删除）",
    )
    p_purge.add_argument(
        "--days",
        type=int,
        default=None,
        help="保留天数（默认取 TRASH_RETENTION_DAYS，默认 30；0 = 关闭）",
    )
    p_purge.add_argument("--apply", action="store_true", help="实际删除到期行（默认 dry-run）")
    p_purge.add_argument(
        "--dry-run",
        action="store_true",
        help="显式声明仅体检（默认行为，仅用于脚本可读性；与 --apply 同时给出时以 --apply 为准）",
    )
    p_purge.add_argument("--workspace", dest="workspace_id", type=int, default=None, help="限定工作区 id")
    p_purge.add_argument("--table", dest="table_id", type=int, default=None, help="限定数据表 id")
    p_purge.add_argument("--json", action="store_true", help="以 JSON 输出报告")
