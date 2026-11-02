"""采集策略调度 —— 到期扫描 + 租约互斥 + 执行（ADR 0085 P2）.

形态与 ``datasource`` 的 ``tick`` 一致：生产用 ``cndb acquisition tick`` + 系统 cron，
开发 / 单机可起内置守护线程；两者都调 :func:`tick`，租约（``acquisition_strategy``
上的行级租约）由 :func:`execute_strategy` 自行抢占 / 释放，保证**同一策略任意时刻
至多一个执行者**。

与数据同步调度的两点差异：

- **待复核不抢跑**：策略存在 ``awaiting_review`` 的运行时不因到期而新起一轮
  （否则用户未确认的扩展词会被调度覆盖），记 ``skipped_pending``；
- **复用同一份调度语义**：``schedule`` JSON 与 ``datasource_sync_job`` 完全一致
  （``manual`` / ``daily`` / ``interval`` / ``cron`` + 时区 + 失败退避），
  到期判定直接复用 ``datasource.services.schedule.is_due``。
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from cndb.plugins.acquisition.models import (
    AcquisitionRound,
    AcquisitionRun,
    AcquisitionStrategy,
    ReviewState,
    RunStatus,
    RunTrigger,
)
from cndb.plugins.acquisition.services.runner import (
    StrategyBusyError,
    StrategyExecution,
    execute_strategy,
    resume_run,
)
from cndb.plugins.datasource.providers.base import FetchFn, ProviderError
from cndb.plugins.datasource.services.schedule import ScheduleConfig, is_due

logger = logging.getLogger(__name__)

#: 单次 tick 最多处理的策略数（防止一次扫太多把上游打爆）
DEFAULT_TICK_LIMIT = 20
#: 复核超时（D14）：``awaiting_review`` 超过该时长未确认，按「不调」自动续跑
REVIEW_TIMEOUT_SECONDS = 72 * 3600

__all__ = ["DEFAULT_TICK_LIMIT", "REVIEW_TIMEOUT_SECONDS", "TickReport", "due_strategies", "tick"]


@dataclass(slots=True)
class TickReport:
    """一次 tick 的汇总（CLI 打印 / JSON 输出）."""

    examined: int = 0
    executed: int = 0
    succeeded: int = 0
    partial: int = 0
    failed: int = 0
    awaiting_review: int = 0
    skipped_leased: int = 0
    skipped_pending: int = 0
    resumed_timeout: int = 0
    strategy_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "examined": self.examined,
            "executed": self.executed,
            "succeeded": self.succeeded,
            "partial": self.partial,
            "failed": self.failed,
            "awaiting_review": self.awaiting_review,
            "skipped_leased": self.skipped_leased,
            "skipped_pending": self.skipped_pending,
            "resumed_timeout": self.resumed_timeout,
            "strategy_ids": self.strategy_ids,
        }


def _as_utc(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def _schedule_of(strategy: AcquisitionStrategy) -> ScheduleConfig | None:
    """解析策略调度声明；非法声明记日志后跳过（不让一条坏配置拖垮整个 tick）."""
    try:
        return ScheduleConfig.from_dict(dict(strategy.schedule or {}))
    except (ProviderError, TypeError, ValueError) as exc:
        logger.warning("采集策略 %s 的调度声明非法，已跳过: %s", strategy.id, exc)
        return None


def due_strategies(
    db: Session,
    *,
    now: dt.datetime,
    limit: int = DEFAULT_TICK_LIMIT,
    workspace_id: int | None = None,
    strategy_id: int | None = None,
) -> list[AcquisitionStrategy]:
    """到期策略（只判调度与租约空闲，不判待复核）.

    ``strategy_id`` 显式指定时忽略调度判定（运维补跑），但仍跳过租约占用中的策略。
    """
    if limit <= 0:
        return []
    current = _as_utc(now)
    stmt = select(AcquisitionStrategy).where(AcquisitionStrategy.enabled.is_(True))
    if workspace_id is not None:
        stmt = stmt.where(AcquisitionStrategy.workspace_id == workspace_id)
    if strategy_id is not None:
        stmt = stmt.where(AcquisitionStrategy.id == strategy_id)
    stmt = (
        stmt.where(
            or_(
                AcquisitionStrategy.lease_owner.is_(None),
                AcquisitionStrategy.lease_until.is_(None),
                AcquisitionStrategy.lease_until < current,
            )
        )
        .order_by(AcquisitionStrategy.id)
        .limit(limit)
    )

    due: list[AcquisitionStrategy] = []
    for strategy in db.execute(stmt).scalars():
        if strategy_id is not None:
            due.append(strategy)
            continue
        config = _schedule_of(strategy)
        if config is None:
            continue
        if is_due(
            config,
            now=current,
            last_run_at=strategy.last_run_at,
            last_status=strategy.last_status,
        ):
            due.append(strategy)
    return due


def _has_pending_review(db: Session, strategy_id: int) -> bool:
    """该策略是否还有等用户确认的轮次（有则不抢占）."""
    return (
        db.execute(
            select(AcquisitionRun.id)
            .where(
                AcquisitionRun.strategy_id == strategy_id,
                AcquisitionRun.status == RunStatus.AWAITING_REVIEW.value,
            )
            .limit(1)
        ).first()
        is not None
    )


def _pending_reviews(db: Session) -> list[tuple[AcquisitionRun, dt.datetime]]:
    """所有待复核运行 → ``(run, 待确认轮次的创建时间)``（超时兜底用）."""
    runs = list(
        db.execute(select(AcquisitionRun).where(AcquisitionRun.status == RunStatus.AWAITING_REVIEW.value)).scalars()
    )
    pending: list[tuple[AcquisitionRun, dt.datetime]] = []
    for run in runs:
        round_row = (
            db.execute(
                select(AcquisitionRound)
                .where(
                    AcquisitionRound.run_id == run.id,
                    AcquisitionRound.review_state == ReviewState.PENDING.value,
                )
                .order_by(AcquisitionRound.round_no.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        pending.append((run, _as_utc(round_row.created_at if round_row is not None else run.started_at)))
    return pending


def resume_expired_reviews(
    db: Session,
    *,
    now: dt.datetime,
    timeout_seconds: int = REVIEW_TIMEOUT_SECONDS,
    fetch: FetchFn | None = None,
) -> tuple[int, int]:
    """超时复核兜底续跑（D14）：返回 ``(续跑成功数, 因租约占用跳过数)``."""
    resumed = 0
    skipped = 0
    for run, pending_since in _pending_reviews(db):
        if (now - pending_since).total_seconds() < timeout_seconds:
            continue
        try:
            resume_run(db, run, fetch=fetch, now=now, timeout=True)
            resumed += 1
        except StrategyBusyError:
            skipped += 1
        except Exception as exc:  # 单条续跑失败不阻断 tick
            logger.warning("运行 %s 超时续跑失败: %s", run.id, exc)
    return resumed, skipped


def tick(
    db: Session,
    *,
    now: dt.datetime | None = None,
    limit: int = DEFAULT_TICK_LIMIT,
    workspace_id: int | None = None,
    strategy_id: int | None = None,
    fetch: FetchFn | None = None,
) -> TickReport:
    """扫描到期策略并逐个执行（``strategy_id`` 手动指定时忽略调度判定）."""
    current = _as_utc(now or dt.datetime.now(dt.UTC))
    # 先做一次超时复核兜底：把卡住的运行推走，避免它们一直占着「待复核」把调度挡在门外
    resumed, resume_skipped = resume_expired_reviews(db, now=current, fetch=fetch)
    strategies = due_strategies(
        db,
        now=current,
        limit=limit,
        workspace_id=workspace_id,
        strategy_id=strategy_id,
    )
    report = TickReport(examined=len(strategies), resumed_timeout=resumed, skipped_leased=resume_skipped)

    for strategy in strategies:
        if _has_pending_review(db, strategy.id):
            report.skipped_pending += 1
            logger.info("采集策略 %s 有待复核轮次，调度跳过", strategy.id)
            continue
        try:
            execution = execute_strategy(
                db,
                strategy,
                trigger=RunTrigger.SCHEDULER,
                fetch=fetch,
                now=current,
            )
        except StrategyBusyError:
            report.skipped_leased += 1
            continue

        report.executed += 1
        report.strategy_ids.append(strategy.id)
        _count_status(report, execution)

    return report


def _count_status(report: TickReport, execution: StrategyExecution) -> None:
    """按运行终态归类计数（``awaiting_review`` 单独统计，便于运维判断卡在哪）."""
    status = execution.status
    if status == RunStatus.AWAITING_REVIEW.value:
        report.awaiting_review += 1
    elif status == RunStatus.FAILED.value:
        report.failed += 1
    elif status == RunStatus.PARTIAL.value:
        report.partial += 1
    else:
        report.succeeded += 1
