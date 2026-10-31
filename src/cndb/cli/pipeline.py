"""cndb pipeline 子命令 —— 流水线定时触发的运维入口（生产建议配系统 cron）.

子命令：
- ``tick``  到期扫描（cron 每分钟调一次；``--workflow-id`` 只看某条）

示例：
    cndb pipeline tick                       # 系统 cron：* * * * * cndb pipeline tick
    cndb pipeline tick --workspace-id 1 --json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

from sqlalchemy.orm import Session


def _get_session() -> Session:
    """按当前 settings.DATABASE_URL 打开 session（与 cndb sync / docs 同口径）."""
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker

    import cndb.plugins.datasource.models
    import cndb.plugins.documents.models
    import cndb.plugins.pipeline.models
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
    if not inspector.has_table("pipeline_workflow"):
        Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def cmd_tick(args: argparse.Namespace) -> dict[str, Any]:
    """执行一次到期扫描（同步执行，返回汇总）."""
    from cndb.plugins.pipeline.services.scheduler import DEFAULT_TICK_LIMIT, tick

    db = _get_session()
    try:
        report = tick(
            db,
            now=_now(),
            limit=int(getattr(args, "limit", None) or DEFAULT_TICK_LIMIT),
            workspace_id=int(args.workspace_id) if getattr(args, "workspace_id", None) else None,
            workflow_id=int(args.workflow_id) if getattr(args, "workflow_id", None) else None,
        )
        return report.to_dict()
    finally:
        db.close()


def _print_tick(payload: dict[str, Any]) -> None:
    print(
        f"[pipeline tick] 到期 {payload['examined']}，执行 {payload['executed']}"
        f"（成功 {payload['succeeded']} / 失败 {payload['failed']}），"
        f"活跃运行跳过 {payload['skipped_conflict']}"
    )
    if payload["workflow_ids"]:
        print(f"  执行流水线: {', '.join(f'#{workflow_id}' for workflow_id in payload['workflow_ids'])}")


def pipeline_command(args: argparse.Namespace) -> None:
    """分发 ``cndb pipeline <sub>``."""
    cmd = getattr(args, "pipeline_cmd", None)
    if cmd is None:
        print("[error] 缺少 pipeline 子命令，可用: tick", file=sys.stderr)
        sys.exit(2)
    if cmd != "tick":  # pragma: no cover - argparse 已收窄
        print(f"[error] 未知 pipeline 子命令: {cmd}", file=sys.stderr)
        sys.exit(2)
    payload = cmd_tick(args)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        _print_tick(payload)
    if payload.get("failed"):
        sys.exit(1)


def register_pipeline_subparser(sub: Any) -> None:
    """向顶层 ArgumentParser 注册 `cndb pipeline` 子命令组."""
    p_pipeline = sub.add_parser("pipeline", help="流水线定时触发（tick）")
    pipeline_sub = p_pipeline.add_subparsers(dest="pipeline_cmd")

    p_tick = pipeline_sub.add_parser("tick", help="到期扫描并执行（生产 cron 每分钟调用）")
    p_tick.add_argument("--workflow-id", type=int, help="只处理指定流水线")
    p_tick.add_argument("--workspace-id", type=int, help="只处理指定工作区")
    p_tick.add_argument("--limit", type=int, default=20, help="单次最多处理流水线数")
    p_tick.add_argument("--json", action="store_true", help="以 JSON 输出")


__all__ = [
    "cmd_tick",
    "pipeline_command",
    "register_pipeline_subparser",
]
