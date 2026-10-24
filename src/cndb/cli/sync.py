"""cndb sync 子命令 —— 数据源同步的运维入口（生产建议配系统 cron）。

子命令：
- ``list``         列出同步任务（名称 / 来源 / 目标表 / 调度 / 上次状态）
- ``run``          立即执行（``--job-id`` 指定一条，或 ``--all`` 跑全部启用的）
- ``tick``         到期扫描（cron 每分钟调一次；``--job-id`` 只看某条）
- ``preview``      只抓不落库，打印前 N 行与失败明细

示例：
    cndb sync tick                       # 系统 cron：* * * * * cndb sync tick
    cndb sync run --job-id 3 --dry-run   # 演练：只抓不写
    cndb sync list --json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session


def _get_session() -> Session:
    """按当前 settings.DATABASE_URL 打开 session（与 cndb docs / users 同口径）."""
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker

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
    if not (inspector.has_table("datasource_sync_job") and inspector.has_table("datasource_session")):
        Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def cmd_list(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.datasource.models import DatasourceSyncJob

    db = _get_session()
    try:
        stmt = select(DatasourceSyncJob).order_by(DatasourceSyncJob.id)
        workspace_id = getattr(args, "workspace_id", None)
        if workspace_id is not None:
            stmt = stmt.where(DatasourceSyncJob.workspace_id == workspace_id)
        jobs = list(db.execute(stmt).scalars())
        return {
            "total": len(jobs),
            "jobs": [
                {
                    "id": job.id,
                    "workspace_id": job.workspace_id,
                    "name": job.name,
                    "provider": job.provider,
                    "table_id": job.table_id,
                    "enabled": job.enabled,
                    "schedule": job.schedule,
                    "last_run_at": job.last_run_at.isoformat() if job.last_run_at else None,
                    "last_status": job.last_status,
                    "cursor": job.cursor,
                }
                for job in jobs
            ],
        }
    finally:
        db.close()


def cmd_run(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.datasource.models import DatasourceSession, DatasourceSyncJob, RunStatus, RunTrigger
    from cndb.plugins.datasource.services.runner import execute_job, preview_job
    from cndb.plugins.datasource.services.scheduler import (
        LEASE_TTL_SECONDS,
        acquire_lease,
        default_owner,
        release_lease,
    )

    db = _get_session()
    owner = default_owner()
    try:
        if getattr(args, "job_id", None):
            job = db.get(DatasourceSyncJob, int(args.job_id))
            if job is None:
                raise SystemExit(f"[error] 同步任务不存在: {args.job_id}")
            jobs = [job]
        else:
            jobs = list(db.execute(select(DatasourceSyncJob).where(DatasourceSyncJob.enabled.is_(True))).scalars())

        results: list[dict[str, Any]] = []
        for job in jobs:
            if getattr(args, "dry_run", False):
                session = db.get(DatasourceSession, job.session_id) if job.session_id else None
                preview = preview_job(job, limit=int(getattr(args, "limit", 20) or 20), session=session, db=db)
                results.append(
                    {
                        "job_id": job.id,
                        "name": job.name,
                        "dry_run": True,
                        "status": preview.status,
                        "total": preview.total,
                        "columns": preview.columns,
                        "failures": preview.failures,
                        "rows": preview.rows,
                        # ADR 0019：llm_prompt 预览会给出自动识别的幂等键
                        "suggested_match_keys": preview.suggested_match_keys,
                    }
                )
                continue

            if not acquire_lease(db, job.id, owner, now=_now(), ttl_seconds=LEASE_TTL_SECONDS):
                results.append({"job_id": job.id, "name": job.name, "skipped": "租约已被占用"})
                continue
            try:
                execution = execute_job(db, job, trigger=RunTrigger.CLI)
                run = execution.run
                results.append(
                    {
                        "job_id": job.id,
                        "name": job.name,
                        "run_id": run.id,
                        "status": run.status,
                        "fetched": run.fetched,
                        "inserted": run.inserted,
                        "updated": run.updated,
                        "skipped_rows": run.skipped,
                        "cursor_from": execution.cursor_from,
                        "cursor_to": execution.cursor_to,
                        "error": run.error_message,
                    }
                )
            finally:
                release_lease(db, job.id, owner)
        failed = [item for item in results if item.get("status") == RunStatus.FAILED.value]
        return {"total": len(results), "failed": len(failed), "results": results}
    finally:
        db.close()


def cmd_tick(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.datasource.services.scheduler import tick

    db = _get_session()
    try:
        report = tick(
            db,
            now=_now(),
            limit=int(getattr(args, "limit", 20) or 20),
            job_id=int(args.job_id) if getattr(args, "job_id", None) else None,
            workspace_id=int(args.workspace_id) if getattr(args, "workspace_id", None) else None,
        )
        return report.to_dict()
    finally:
        db.close()


def cmd_preview(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.datasource.models import DatasourceSession, DatasourceSyncJob
    from cndb.plugins.datasource.services.runner import preview_job

    db = _get_session()
    try:
        job = db.get(DatasourceSyncJob, int(args.job_id))
        if job is None:
            raise SystemExit(f"[error] 同步任务不存在: {args.job_id}")
        session = db.get(DatasourceSession, job.session_id) if job.session_id else None
        preview = preview_job(job, limit=int(getattr(args, "limit", 20) or 20), session=session, db=db)
        return {
            "job_id": job.id,
            "name": job.name,
            "status": preview.status,
            "plans": preview.plans,
            "succeeded": preview.succeeded,
            "total": preview.total,
            "columns": preview.columns,
            "cursor_from": preview.cursor_from,
            "cursor_to": preview.cursor_to,
            "failures": preview.failures,
            "normalize_failures": preview.normalize_failures,
            # ADR 0019：llm_prompt 预览会给出自动识别的幂等键
            "suggested_match_keys": preview.suggested_match_keys,
            "rows": preview.rows,
        }
    finally:
        db.close()


def _print_list(payload: dict[str, Any]) -> None:
    print(f"[sync] 共 {payload['total']} 个任务")
    for job in payload["jobs"]:
        state = "启用" if job["enabled"] else "停用"
        schedule = job["schedule"].get("mode", "manual") if isinstance(job["schedule"], dict) else "manual"
        print(
            f"  #{job['id']} {job['name']} [{state}] provider={job['provider']} "
            f"table={job['table_id']} schedule={schedule} "
            f"last={job['last_status'] or '-'}@{job['last_run_at'] or '-'}"
        )


def _print_run(payload: dict[str, Any]) -> None:
    for item in payload["results"]:
        if "skipped" in item:
            print(f"  #{item['job_id']} {item['name']} 跳过：{item['skipped']}")
            continue
        if item.get("dry_run"):
            print(
                f"  #{item['job_id']} {item['name']} [dry-run] status={item['status']} "
                f"rows={item['total']} columns={','.join(item['columns']) or '-'}"
            )
            for failure in item["failures"]:
                print(f"    ! {failure['label']}: {failure['error']}")
            continue
        print(
            f"  #{item['job_id']} {item['name']} run#{item['run_id']} status={item['status']} "
            f"fetched={item['fetched']} inserted={item['inserted']} updated={item['updated']} "
            f"cursor={item['cursor_from'] or '-'}→{item['cursor_to'] or '-'}"
        )
        if item.get("error"):
            print(f"    ! {item['error']}")
    print(f"[sync] 共 {payload['total']} 条，失败 {payload['failed']} 条")


def _print_tick(payload: dict[str, Any]) -> None:
    print(
        f"[sync tick] 到期 {payload['examined']}，执行 {payload['executed']}"
        f"（成功 {payload['succeeded']} / 失败 {payload['failed']}），"
        f"租约占用跳过 {payload['skipped_leased']}"
    )
    if payload["job_ids"]:
        print(f"  执行任务: {', '.join(f'#{job_id}' for job_id in payload['job_ids'])}")


def _print_preview(payload: dict[str, Any]) -> None:
    print(
        f"[sync preview] #{payload['job_id']} {payload['name']} status={payload['status']} "
        f"plans={payload['plans']} rows={payload['total']} "
        f"cursor={payload['cursor_from'] or '-'}→{payload['cursor_to'] or '-'}"
    )
    print(f"  列: {', '.join(payload['columns']) or '-'}")
    for failure in payload["failures"]:
        print(f"  ! {failure['label']}: {failure['error']}")
    for row in payload["rows"]:
        print(f"  {json.dumps(row, ensure_ascii=False, default=str)}")


def sync_command(args: argparse.Namespace) -> None:
    """分发 ``cndb sync <sub>``."""
    cmd = getattr(args, "sync_cmd", None)
    if cmd is None:
        print("[error] 缺少 sync 子命令，可用: list / run / tick / preview", file=sys.stderr)
        sys.exit(2)
    handlers = {
        "list": cmd_list,
        "run": cmd_run,
        "tick": cmd_tick,
        "preview": cmd_preview,
    }
    printers = {
        "list": _print_list,
        "run": _print_run,
        "tick": _print_tick,
        "preview": _print_preview,
    }
    handler = handlers.get(cmd)
    if handler is None:  # pragma: no cover - argparse 已收窄
        print(f"[error] 未知 sync 子命令: {cmd}", file=sys.stderr)
        sys.exit(2)
    payload = handler(args)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        printers[cmd](payload)
    if cmd in ("run", "tick") and payload.get("failed"):
        sys.exit(1)


def register_sync_subparser(sub: Any) -> None:
    """向顶层 ArgumentParser 注册 `cndb sync` 子命令组."""
    p_sync = sub.add_parser("sync", help="数据源同步（list / run / tick / preview）")
    sync_sub = p_sync.add_subparsers(dest="sync_cmd")

    p_list = sync_sub.add_parser("list", help="列出同步任务")
    p_list.add_argument("--workspace-id", type=int, help="只看某个工作区")
    p_list.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_run = sync_sub.add_parser("run", help="立即执行（--job-id 指定一条，缺省跑全部启用的）")
    p_run.add_argument("--job-id", type=int, help="任务 id")
    p_run.add_argument("--dry-run", action="store_true", help="只抓不落库")
    p_run.add_argument("--limit", type=int, default=20, help="dry-run 打印行数上限")
    p_run.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_tick = sync_sub.add_parser("tick", help="到期扫描并执行（生产 cron 每分钟调用）")
    p_tick.add_argument("--job-id", type=int, help="只处理指定任务")
    p_tick.add_argument("--workspace-id", type=int, help="只处理指定工作区")
    p_tick.add_argument("--limit", type=int, default=20, help="单次最多处理任务数")
    p_tick.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_preview = sync_sub.add_parser("preview", help="只抓不落库，打印预览行")
    p_preview.add_argument("--job-id", type=int, required=True, help="任务 id")
    p_preview.add_argument("--limit", type=int, default=20, help="打印行数上限")
    p_preview.add_argument("--json", action="store_true", help="以 JSON 输出")


__all__ = [
    "cmd_list",
    "cmd_preview",
    "cmd_run",
    "cmd_tick",
    "register_sync_subparser",
    "sync_command",
]
