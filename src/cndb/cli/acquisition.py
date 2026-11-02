"""cndb acquisition 子命令 —— 采集策略的运维入口（ADR 0085 P0）.

子命令：

- ``list``     列出采集策略（名称 / 渠道数 / 落点 / 最近状态）
- ``run``      立即执行一条策略（同步执行，受预算上限约束）
- ``preview``  只抓取 + 筛选，不落表 / 不写台账 / 不落运行记录
- ``resume``   续跑 ``awaiting_review`` 的运行（可带关键词 / 检索式，也可不带）
- ``tick``     扫描到期策略并执行（配合系统 cron，ADR 0085 P2）

示例：
    cndb acquisition list --workspace-id 1
    cndb acquisition run --strategy-id 3 --json
    cndb acquisition preview --strategy-id 3
    cndb acquisition resume --run-id 5 --keywords 固态 电解质
    cndb acquisition tick --limit 10
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

from sqlalchemy.orm import Session


def _get_session() -> Session:
    """按当前 settings.DATABASE_URL 打开 session（与 cndb sync / pipeline 同口径）."""
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker

    import cndb.plugins.acquisition.models
    import cndb.plugins.datasource.models
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
    if not inspector.has_table("acquisition_strategy"):
        Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def cmd_list(args: argparse.Namespace) -> dict[str, Any]:
    from sqlalchemy import select

    from cndb.plugins.acquisition.models import AcquisitionStrategy

    db = _get_session()
    try:
        stmt = select(AcquisitionStrategy).order_by(AcquisitionStrategy.id)
        workspace_id = getattr(args, "workspace_id", None)
        if workspace_id is not None:
            stmt = stmt.where(AcquisitionStrategy.workspace_id == workspace_id)
        strategies = list(db.execute(stmt).scalars())
        return {
            "total": len(strategies),
            "strategies": [
                {
                    "id": item.id,
                    "workspace_id": item.workspace_id,
                    "name": item.name,
                    "enabled": item.enabled,
                    "rule_version": item.rule_version,
                    "channels": list((item.scope or {}).get("channels") or []),
                    "targets": [target.get("kind") for target in list(item.targets or [])],
                    "last_status": item.last_status,
                    "last_run_at": item.last_run_at.isoformat() if item.last_run_at else None,
                }
                for item in strategies
            ],
        }
    finally:
        db.close()


def _load_strategy(db: Session, strategy_id: int) -> Any:
    from cndb.plugins.acquisition.models import AcquisitionStrategy

    strategy = db.get(AcquisitionStrategy, strategy_id)
    if strategy is None:
        raise SystemExit(f"[error] 采集策略不存在: {strategy_id}")
    return strategy


def cmd_run(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.acquisition.models import RunTrigger
    from cndb.plugins.acquisition.services.runner import StrategyBusyError, execute_strategy

    db = _get_session()
    try:
        strategy = _load_strategy(db, int(args.strategy_id))
        try:
            execution = execute_strategy(db, strategy, trigger=RunTrigger.CLI, now=_now())
        except StrategyBusyError as exc:
            return {"strategy_id": strategy.id, "skipped": str(exc), "status": "skipped"}
        run = execution.run
        return {
            "strategy_id": strategy.id,
            "name": strategy.name,
            "run_id": run.id if run is not None else None,
            "status": execution.status,
            "collected": execution.collected,
            "after_dedup": execution.after_dedup,
            "after_filter": execution.after_filter,
            "inserted": execution.report.inserted,
            "updated": execution.report.updated,
            "skipped": execution.report.skipped,
            "channel_errors": execution.channel_errors,
            "target_errors": execution.report.errors,
            "error": run.error_message if run is not None else "",
        }
    finally:
        db.close()


def cmd_preview(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.acquisition.services.runner import SAMPLE_SIZE, preview_strategy

    db = _get_session()
    try:
        strategy = _load_strategy(db, int(args.strategy_id))
        execution = preview_strategy(db, strategy, now=_now())
        limit = int(getattr(args, "limit", SAMPLE_SIZE) or SAMPLE_SIZE)
        return {
            "strategy_id": strategy.id,
            "name": strategy.name,
            "status": execution.status,
            "collected": execution.collected,
            "after_dedup": execution.after_dedup,
            "after_filter": execution.after_filter,
            "by_channel": execution.by_channel,
            "channel_errors": execution.channel_errors,
            "samples": execution.samples[:limit],
        }
    finally:
        db.close()


def cmd_tick(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.acquisition.services.scheduler import DEFAULT_TICK_LIMIT, tick

    db = _get_session()
    try:
        report = tick(
            db,
            now=_now(),
            limit=int(getattr(args, "limit", DEFAULT_TICK_LIMIT) or DEFAULT_TICK_LIMIT),
            workspace_id=getattr(args, "workspace_id", None),
            strategy_id=getattr(args, "strategy_id", None),
        )
        return report.to_dict()
    finally:
        db.close()


def cmd_resume(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.acquisition.models import AcquisitionRun
    from cndb.plugins.acquisition.services.runner import StrategyBusyError, resume_run

    db = _get_session()
    try:
        run = db.get(AcquisitionRun, int(args.run_id))
        if run is None:
            raise SystemExit(f"[error] 运行记录不存在: {args.run_id}")
        keywords = list(getattr(args, "keywords", None) or [])
        try:
            execution = resume_run(
                db,
                run,
                keywords=keywords or None,
                query=getattr(args, "query", None),
                now=_now(),
            )
        except StrategyBusyError as exc:
            return {"run_id": run.id, "skipped": str(exc), "status": "skipped"}
        except Exception as exc:  # 规则错误等按可读结果返回（CLI 不抛栈）
            return {"run_id": run.id, "status": "failed", "error": str(exc)}
        return {
            "run_id": run.id,
            "strategy_id": run.strategy_id,
            "status": execution.status,
            "rounds": execution.rounds,
            "collected": execution.collected,
            "after_filter": execution.after_filter,
            "inserted": execution.report.inserted,
            "updated": execution.report.updated,
            "docs_created": execution.report.docs_created,
            "docs_updated": execution.report.docs_updated,
        }
    finally:
        db.close()


def _print_list(payload: dict[str, Any]) -> None:
    print(f"[acquisition] 共 {payload['total']} 条策略")
    for item in payload["strategies"]:
        state = "启用" if item["enabled"] else "停用"
        kinds = ",".join(kind for kind in item["targets"] if kind) or "-"
        print(
            f"  #{item['id']} {item['name']} [{state}] v{item['rule_version']} "
            f"channels={len(item['channels'])} targets={kinds} "
            f"last={item['last_status'] or '-'}@{item['last_run_at'] or '-'}"
        )


def _print_run(payload: dict[str, Any]) -> None:
    if payload.get("skipped"):
        print(f"  #{payload['strategy_id']} 跳过：{payload['skipped']}")
        return
    print(
        f"  #{payload['strategy_id']} {payload['name']} run#{payload['run_id']} "
        f"status={payload['status']} collected={payload['collected']} "
        f"dedup={payload['after_dedup']} filtered={payload['after_filter']} "
        f"inserted={payload['inserted']} updated={payload['updated']} skipped={payload['skipped']}"
    )
    for failure in payload["channel_errors"]:
        print(f"    ! {failure['channel']}: {failure['error']}")
    for failure in payload["target_errors"]:
        print(f"    ! {failure['target']}: {failure['error']}")
    if payload.get("error"):
        print(f"    ! {payload['error']}")


def _print_tick(payload: dict[str, Any]) -> None:
    print(
        f"[acquisition tick] 扫描 {payload['examined']} 条，执行 {payload['executed']} 条 "
        f"(success={payload['succeeded']} partial={payload['partial']} failed={payload['failed']} "
        f"review={payload['awaiting_review']}) 超时续跑 {payload['resumed_timeout']} "
        f"跳过：租约 {payload['skipped_leased']} / 待复核 {payload['skipped_pending']}"
    )
    for strategy_id in payload["strategy_ids"]:
        print(f"  - strategy#{strategy_id}")


def _print_resume(payload: dict[str, Any]) -> None:
    if payload.get("skipped"):
        print(f"  run#{payload['run_id']} 跳过：{payload['skipped']}")
        return
    if payload.get("error"):
        print(f"  run#{payload['run_id']} 失败：{payload['error']}")
        return
    print(
        f"  run#{payload['run_id']} strategy#{payload['strategy_id']} status={payload['status']} "
        f"rounds={payload['rounds']} collected={payload['collected']} filtered={payload['after_filter']} "
        f"inserted={payload['inserted']} updated={payload['updated']} "
        f"docs+{payload['docs_created']}/~{payload['docs_updated']}"
    )


def _print_preview(payload: dict[str, Any]) -> None:
    print(
        f"[acquisition preview] #{payload['strategy_id']} {payload['name']} "
        f"status={payload['status']} collected={payload['collected']} "
        f"dedup={payload['after_dedup']} filtered={payload['after_filter']}"
    )
    for channel, count in payload["by_channel"].items():
        print(f"  - {channel}: {count} 条")
    for failure in payload["channel_errors"]:
        print(f"  ! {failure['channel']}: {failure['error']}")
    for row in payload["samples"]:
        print(f"  {json.dumps(row, ensure_ascii=False, default=str)}")


def acquisition_command(args: argparse.Namespace) -> None:
    """分发 ``cndb acquisition <sub>``."""
    cmd = getattr(args, "acquisition_cmd", None)
    if cmd is None:
        print("[error] 缺少 acquisition 子命令，可用: list / run / preview / resume / tick", file=sys.stderr)
        sys.exit(2)
    handlers = {
        "list": cmd_list,
        "run": cmd_run,
        "preview": cmd_preview,
        "resume": cmd_resume,
        "tick": cmd_tick,
    }
    printers = {
        "list": _print_list,
        "run": _print_run,
        "preview": _print_preview,
        "resume": _print_resume,
        "tick": _print_tick,
    }
    handler = handlers.get(cmd)
    if handler is None:  # pragma: no cover - argparse 已收窄
        print(f"[error] 未知 acquisition 子命令: {cmd}", file=sys.stderr)
        sys.exit(2)
    payload = handler(args)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        printers[cmd](payload)
    if cmd == "run" and payload.get("status") == "failed":
        sys.exit(1)
    if cmd == "tick" and payload.get("failed"):
        sys.exit(1)


def register_acquisition_subparser(sub: Any) -> None:
    """向顶层 ArgumentParser 注册 `cndb acquisition` 子命令组."""
    p_acq = sub.add_parser("acquisition", help="采集策略（list / run / preview / resume / tick）")
    acq_sub = p_acq.add_subparsers(dest="acquisition_cmd")

    p_list = acq_sub.add_parser("list", help="列出采集策略")
    p_list.add_argument("--workspace-id", type=int, help="只看某个工作区")
    p_list.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_run = acq_sub.add_parser("run", help="立即执行一条策略")
    p_run.add_argument("--strategy-id", type=int, required=True, help="策略 id")
    p_run.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_preview = acq_sub.add_parser("preview", help="只抓取 + 筛选，不落库")
    p_preview.add_argument("--strategy-id", type=int, required=True, help="策略 id")
    p_preview.add_argument("--limit", type=int, default=5, help="打印样例条数上限")
    p_preview.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_resume = acq_sub.add_parser("resume", help="续跑待复核的运行（可带关键词 / 检索式）")
    p_resume.add_argument("--run-id", type=int, required=True, help="运行 id")
    p_resume.add_argument("--keywords", nargs="*", help="调整后的扩展词（留空表示不调）")
    p_resume.add_argument("--query", help="直接指定下一轮检索式")
    p_resume.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_tick = acq_sub.add_parser("tick", help="扫描到期策略并执行（cron 调用）")
    p_tick.add_argument("--workspace-id", type=int, help="只处理某个工作区")
    p_tick.add_argument("--strategy-id", type=int, help="只跑指定策略（忽略调度到期判定）")
    p_tick.add_argument("--limit", type=int, default=20, help="单次最多执行的策略数")
    p_tick.add_argument("--json", action="store_true", help="以 JSON 输出")


__all__ = [
    "acquisition_command",
    "cmd_list",
    "cmd_preview",
    "cmd_resume",
    "cmd_run",
    "cmd_tick",
    "register_acquisition_subparser",
]
