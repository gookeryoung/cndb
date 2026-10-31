"""流水线定时触发：到期扫描与同步执行（ADR 0076 D5 / P2）.

形态与 ``cndb sync tick`` 对齐：生产由系统 cron 每分钟调用 ``cndb pipeline tick``；
到期判定在 DB 层完成（读定义 ``compiled.on.schedule`` 的 5 段 cron），不做进程内
状态。tick 内**同步执行**运行，避免 CLI 退出时守护线程被杀导致运行卡在 pending。

时间口径：cron 按 UTC+8 解释（与数据源调度 ``DEFAULT_TZ_OFFSET_MINUTES`` 一致），
落库时间一律 aware UTC。同一分钟只触发一次（以最近一条 ``schedule`` 运行的
``created_at`` 分钟槽为水位）；同一定义已有活跃运行时静默跳过（I6 / D8）。
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.plugins.datasource.providers.base import ProviderError
from cndb.plugins.datasource.services.schedule import cron_matches
from cndb.plugins.pipeline.models import (
    RUN_STATUS_FAILED,
    TRIGGER_SCHEDULE,
    PipelineRun,
    PipelineWorkflow,
)
from cndb.plugins.pipeline.services.dsl.parse import WorkflowIR
from cndb.plugins.pipeline.services.errors import PipelineConflictError
from cndb.plugins.pipeline.services.runner import create_run, execute_pipeline_run

logger = logging.getLogger(__name__)

#: 单次 tick 最多处理的流水线数（避免一次扫太多把 cron 窗口拉长）
DEFAULT_TICK_LIMIT = 20
#: cron 解释时区（UTC+8，与数据源调度默认偏移一致）
TZ_OFFSET_MINUTES = 480
_TZ = dt.timezone(dt.timedelta(minutes=TZ_OFFSET_MINUTES))


@dataclass(slots=True)
class PipelineTickReport:
    """一次定时扫描的汇总（CLI 打印 / JSON 输出）."""

    examined: int = 0
    executed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped_conflict: int = 0
    workflow_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转为 JSON 友好字典."""
        return {
            "examined": self.examined,
            "executed": self.executed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped_conflict": self.skipped_conflict,
            "workflow_ids": self.workflow_ids,
        }


def _as_utc(value: dt.datetime) -> dt.datetime:
    """naive 视为 UTC（SQLite 读回可能丢失 tzinfo）."""
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def schedule_expr(workflow: PipelineWorkflow) -> str:
    """取定义 ``on.schedule`` 的 cron 表达式；未配置或快照损坏返回空串."""
    try:
        ir = WorkflowIR.from_dict(workflow.compiled or {})
    except Exception:  # pragma: no cover - 保存期已编译，历史脏数据兜底
        logger.warning("流水线 %s 编译快照损坏，跳过定时触发", workflow.id)
        return ""
    expr = ir.triggers.get("schedule")
    return expr if isinstance(expr, str) else ""


def last_schedule_run_at(db: Session, workflow_id: int) -> dt.datetime | None:
    """最近一次 ``schedule`` 触发的运行创建时间（用于分钟槽水位判定）."""
    row = (
        db.query(PipelineRun)
        .filter(PipelineRun.workflow_id == workflow_id, PipelineRun.trigger == TRIGGER_SCHEDULE)
        .order_by(PipelineRun.created_at.desc(), PipelineRun.id.desc())
        .first()
    )
    return row.created_at if row is not None else None


def is_due(
    expr: str,
    *,
    now: dt.datetime,
    last_run_at: dt.datetime | None,
) -> bool:
    """判定当前分钟槽是否命中 cron 且尚未在该分钟触发过."""
    current = _as_utc(now)
    slot = current.replace(second=0, microsecond=0)
    if not cron_matches(expr, slot.astimezone(_TZ)):
        return False
    return last_run_at is None or _as_utc(last_run_at) < slot


def due_workflows(
    db: Session,
    *,
    now: dt.datetime,
    limit: int = DEFAULT_TICK_LIMIT,
    workspace_id: int | None = None,
    workflow_id: int | None = None,
) -> list[tuple[PipelineWorkflow, str]]:
    """列出当前到期的启用定义（按 id 升序，最多 ``limit`` 条）."""
    stmt = select(PipelineWorkflow).where(PipelineWorkflow.enabled.is_(True))
    if workspace_id is not None:
        stmt = stmt.where(PipelineWorkflow.workspace_id == workspace_id)
    if workflow_id is not None:
        stmt = stmt.where(PipelineWorkflow.id == workflow_id)
    stmt = stmt.order_by(PipelineWorkflow.id)
    due: list[tuple[PipelineWorkflow, str]] = []
    for workflow in db.execute(stmt).scalars():
        expr = schedule_expr(workflow)
        if not expr:
            continue
        try:
            if is_due(expr, now=now, last_run_at=last_schedule_run_at(db, workflow.id)):
                due.append((workflow, expr))
        except ProviderError as exc:
            # 单个定义 cron 非法不能让整轮 tick 挂掉（编译期只校验段数）
            logger.warning("流水线 %s 调度表达式非法，跳过: %s", workflow.id, exc)
        if len(due) >= limit:
            break
    return due


def tick(
    db: Session,
    *,
    now: dt.datetime | None = None,
    limit: int = DEFAULT_TICK_LIMIT,
    workspace_id: int | None = None,
    workflow_id: int | None = None,
) -> PipelineTickReport:
    """扫描到期定义并逐个同步执行（cron 每分钟调用；冲突静默跳过）."""
    current = _as_utc(now or dt.datetime.now(dt.UTC))
    due = due_workflows(db, now=current, limit=limit, workspace_id=workspace_id, workflow_id=workflow_id)
    report = PipelineTickReport(examined=len(due))
    for workflow, expr in due:
        try:
            run = create_run(
                db,
                workflow,
                trigger=TRIGGER_SCHEDULE,
                payload={"event": "schedule", "cron": expr},
            )
        except PipelineConflictError:
            report.skipped_conflict += 1
            logger.info("流水线 %s 已有活跃运行，跳过定时触发", workflow.id)
            continue
        execute_pipeline_run(db, run.id)
        db.refresh(run)
        report.executed += 1
        report.workflow_ids.append(workflow.id)
        if run.status == RUN_STATUS_FAILED:
            report.failed += 1
        else:
            report.succeeded += 1
    return report


__all__ = [
    "DEFAULT_TICK_LIMIT",
    "TZ_OFFSET_MINUTES",
    "PipelineTickReport",
    "due_workflows",
    "is_due",
    "last_schedule_run_at",
    "schedule_expr",
    "tick",
]
