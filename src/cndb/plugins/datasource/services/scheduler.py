"""调度器 —— 到期扫描 + DB 租约互斥 + 执行.

形态（ADR 0006 D3）：生产用 ``cndb sync tick`` + 系统 cron，开发 / 单机可起内置
守护线程；两者都调 :func:`tick`，靠 ``datasource_sync_job`` 上的租约保证
**同一 job 任意时刻至多一个执行者**（I4）。租约是 DB 行级原子 UPDATE，
不依赖进程内锁，因此多副本、cron 与内置调度器混跑都安全。
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import socket
import uuid
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.orm import Session

from cndb.plugins.datasource.models import DatasourceSyncJob, RunStatus, RunTrigger
from cndb.plugins.datasource.providers.base import FetchFn
from cndb.plugins.datasource.services.runner import execute_job
from cndb.plugins.datasource.services.schedule import ScheduleConfig, is_due

logger = logging.getLogger(__name__)

# 租约有效期：覆盖一次正常运行的耗时，超时即视为执行者已死（可被抢占）
LEASE_TTL_SECONDS = 300
# 单次 tick 最多处理的任务数（避免一次扫太多把请求打爆）
DEFAULT_TICK_LIMIT = 20


@dataclass(slots=True)
class TickReport:
    """一次 tick 的汇总（CLI 直接打印 / JSON 输出）."""

    examined: int = 0
    executed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped_leased: int = 0
    job_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "examined": self.examined,
            "executed": self.executed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped_leased": self.skipped_leased,
            "job_ids": self.job_ids,
        }


def default_owner() -> str:
    """租约持有者标识：主机名 + pid + 随机后缀（同机多进程也不撞）."""
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


def acquire_lease(
    db: Session,
    job_id: int,
    owner: str,
    *,
    now: dt.datetime,
    ttl_seconds: int = LEASE_TTL_SECONDS,
) -> bool:
    """原子抢占租约；已被他人持有且未过期时返回 ``False``."""
    current = _as_utc(now)
    until = current + dt.timedelta(seconds=ttl_seconds)
    result = cast(
        "CursorResult[Any]",
        db.execute(
            update(DatasourceSyncJob)
            .where(DatasourceSyncJob.id == job_id)
            .where(
                or_(
                    DatasourceSyncJob.lease_owner.is_(None),
                    DatasourceSyncJob.lease_until.is_(None),
                    DatasourceSyncJob.lease_until < current,
                )
            )
            .values(lease_owner=owner, lease_until=until)
            .execution_options(synchronize_session=False)
        ),
    )
    db.commit()
    return bool(result.rowcount)


def release_lease(db: Session, job_id: int, owner: str) -> None:
    """释放自己持有的租约（不是自己持有的不动）."""
    db.execute(
        update(DatasourceSyncJob)
        .where(DatasourceSyncJob.id == job_id)
        .where(DatasourceSyncJob.lease_owner == owner)
        .values(lease_owner=None, lease_until=None)
        .execution_options(synchronize_session=False)
    )
    db.commit()


def due_jobs(
    db: Session,
    *,
    now: dt.datetime,
    limit: int = DEFAULT_TICK_LIMIT,
    workspace_id: int | None = None,
    job_id: int | None = None,
) -> list[DatasourceSyncJob]:
    """列出当前到期的 job（按上次运行时间升序，最久没跑的优先）."""
    stmt = select(DatasourceSyncJob).where(DatasourceSyncJob.enabled.is_(True))
    if workspace_id is not None:
        stmt = stmt.where(DatasourceSyncJob.workspace_id == workspace_id)
    if job_id is not None:
        stmt = stmt.where(DatasourceSyncJob.id == job_id)
    stmt = stmt.order_by(DatasourceSyncJob.last_run_at.asc().nulls_first()).limit(limit)
    jobs = list(db.execute(stmt).scalars())
    due: list[DatasourceSyncJob] = []
    for job in jobs:
        try:
            config = ScheduleConfig.from_dict(job.schedule)
        except Exception as exc:
            # 配置坏掉的 job 不能让整轮 tick 挂掉
            logger.warning("同步任务 %s 调度配置非法，跳过: %s", job.id, exc)
            continue
        if is_due(config, now=now, last_run_at=job.last_run_at, last_status=job.last_status):
            due.append(job)
    return due


def tick(
    db: Session,
    *,
    now: dt.datetime | None = None,
    owner: str | None = None,
    limit: int = DEFAULT_TICK_LIMIT,
    workspace_id: int | None = None,
    job_id: int | None = None,
    fetch: FetchFn | None = None,
) -> TickReport:
    """扫描到期任务并逐个执行（手动 ``--job-id`` 也可复用，忽略调度判定外的租约）."""
    current = _as_utc(now or dt.datetime.now(dt.UTC))
    holder = owner or default_owner()
    jobs = due_jobs(db, now=current, limit=limit, workspace_id=workspace_id, job_id=job_id)
    report = TickReport(examined=len(jobs))
    for job in jobs:
        if not acquire_lease(db, job.id, holder, now=current):
            report.skipped_leased += 1
            logger.info("同步任务 %s 已被其他执行者持有租约，跳过", job.id)
            continue
        try:
            execution = execute_job(db, job, trigger=RunTrigger.SCHEDULER, fetch=fetch, now=current)
            report.executed += 1
            report.job_ids.append(job.id)
            if execution.run.status == RunStatus.FAILED.value:
                report.failed += 1
            else:
                report.succeeded += 1
        finally:
            release_lease(db, job.id, holder)
    return report


def _as_utc(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


__all__ = [
    "DEFAULT_TICK_LIMIT",
    "LEASE_TTL_SECONDS",
    "TickReport",
    "acquire_lease",
    "default_owner",
    "due_jobs",
    "release_lease",
    "tick",
]
