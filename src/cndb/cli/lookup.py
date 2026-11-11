"""cndb lookup 子命令 —— lookup 冗余列回填（ADR 0131）.

子命令：
- backfill   为历史数据补齐 lookup 冗余列并回填（幂等，可重复执行）

迁移会做一次同样的回填；本命令用于：旧库升级后补跑、字段配置被关闭期间
产生的滞后数据、以及排障时的显式重算。写入路径本身已在同事务维护冗余列，
正常情况下不需要手工执行。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy.orm import Session


def _get_session() -> Session:
    """按当前 settings.DATABASE_URL 打开 DB session（与其它运维子命令一致）."""
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


def cmd_backfill(args: argparse.Namespace) -> dict[str, Any]:
    """补齐并回填 lookup 冗余列；返回每张表的处理结果."""
    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.tables.services.core.ddl import ensure_lookup_columns
    from cndb.plugins.tables.services.core.lookup_sync import backfill_lookup_columns

    db = _get_session()
    try:
        engine = db.get_bind().engine
        query = db.query(DataTable).filter(DataTable.trashed == False)  # noqa: E712
        if getattr(args, "workspace", None):
            query = query.filter(DataTable.workspace_id == int(args.workspace))
        if getattr(args, "table", None):
            query = query.filter(DataTable.id == int(args.table))

        tables = [
            t for t in query.order_by(DataTable.id).all() if any(f.field_type == "lookup" for f in t.active_fields())
        ]
        results: list[dict[str, Any]] = []
        failures = 0
        for table in tables:
            try:
                changed = ensure_lookup_columns(engine, table)
                rows = backfill_lookup_columns(engine, table, db=db, batch_size=getattr(args, "batch_size", None))
                results.append(
                    {
                        "table_id": table.id,
                        "table": table.name,
                        "rows": rows,
                        "columns_created": bool(changed),
                    }
                )
            except Exception as exc:  # 单表失败不阻塞其余表，最终以非 0 退出
                failures += 1
                db.rollback()
                results.append({"table_id": table.id, "table": table.name, "error": str(exc)})
        return {"tables": results, "failures": failures, "processed_tables": len(tables)}
    finally:
        db.close()


def _print_result(payload: dict[str, Any]) -> None:
    for item in payload["tables"]:
        if "error" in item:
            print(f"[error] 表 {item['table']}(id={item['table_id']}): {item['error']}", file=sys.stderr)
            continue
        print(
            f"[ok] 表 {item['table']}(id={item['table_id']}): 回填 {item['rows']} 行"
            f"{'，已补齐冗余列' if item['columns_created'] else ''}"
        )
    print(f"[done] 处理 {payload['processed_tables']} 张表，失败 {payload['failures']} 张")


def lookup_command(args: argparse.Namespace) -> None:
    """分发 ``cndb lookup <sub>``."""
    cmd = getattr(args, "lookup_cmd", None)
    if cmd is None:
        print("[error] 缺少 lookup 子命令，可用: backfill", file=sys.stderr)
        sys.exit(2)
    if cmd == "backfill":
        payload = cmd_backfill(args)
        if getattr(args, "json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_result(payload)
        if payload["failures"]:
            sys.exit(1)
        return
    print(f"[error] 未知 lookup 子命令: {cmd}", file=sys.stderr)  # pragma: no cover - argparse 已收窄
    sys.exit(2)


def register_lookup_subparser(sub: Any) -> None:
    """向顶层 ArgumentParser 注册 `cndb lookup` 子命令组."""
    p_lookup = sub.add_parser("lookup", help="lookup 冗余列运维（backfill：历史数据回填）")
    lookup_sub = p_lookup.add_subparsers(dest="lookup_cmd")

    p_backfill = lookup_sub.add_parser("backfill", help="补齐并回填 lookup 冗余列（幂等，可重复执行）")
    p_backfill.add_argument("--workspace", default=None, help="限定工作区 id")
    p_backfill.add_argument("--table", default=None, help="限定数据表 id")
    p_backfill.add_argument("--batch-size", type=int, default=None, help="每批处理行数（默认取配置）")
    p_backfill.add_argument("--json", action="store_true", help="以 JSON 输出报告")


__all__ = ["cmd_backfill", "lookup_command", "register_lookup_subparser"]
