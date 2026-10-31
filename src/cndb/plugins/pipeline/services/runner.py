"""流水线执行器：DAG 编排、检查动作调用与结论推导（ADR 0076 D9 / I3 / I6）.

入口分两步（I3 唯一执行语义）：

1. :func:`create_run` 做单飞检查并落 ``pipeline_run`` 记录（冲突抛 409）；
2. :func:`run_pipeline_in_background` 在后台线程执行 :func:`execute_pipeline_run`。

执行只读业务数据（I1）：检查上下文 ``CheckContext`` 不暴露写 API；执行结果写
``pipeline_run`` / ``pipeline_finding`` 与事件流，属流水自身数据。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from cndb.core.database import checkpoint_wal
from cndb.core.events import record_event
from cndb.plugins.pipeline.models import (
    ACTIVE_RUN_STATUSES,
    CONCLUSION_FAILED,
    CONCLUSION_SKIPPED,
    CONCLUSION_SUCCESS,
    RUN_STATUS_FAILED,
    RUN_STATUS_PARTIAL,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCESS,
    SEVERITIES,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_RANK,
    TRIGGER_MANUAL,
    PipelineFinding,
    PipelineRun,
    PipelineWorkflow,
)
from cndb.plugins.pipeline.services.checks.base import CheckContext, FindingDraft
from cndb.plugins.pipeline.services.checks.registry import coerce_params, require_check
from cndb.plugins.pipeline.services.dsl.expressions import (
    ExpressionEvalError,
    evaluate_expression,
    is_expression,
)
from cndb.plugins.pipeline.services.dsl.parse import JobIR, StepIR, WorkflowIR, topological_jobs
from cndb.plugins.pipeline.services.errors import PipelineConflictError

logger = logging.getLogger(__name__)

#: 单个检查动作在一次运行内的 finding 上限（超出聚合为一条 info）
MAX_FINDINGS_PER_CHECK = 1000

_background_threads: list[threading.Thread] = []
_background_lock = threading.Lock()


def create_run(
    db: Session,
    workflow: PipelineWorkflow,
    *,
    trigger: str = TRIGGER_MANUAL,
    payload: dict[str, Any] | None = None,
) -> PipelineRun:
    """单飞检查 + 建运行记录（I6；冲突抛 :class:`PipelineConflictError`）.

    检查与插入在同一请求事务内完成：SQLite 单写者场景下足以避免同 workflow 的
    并发建 run；跨进程竞争由数据库唯一写入时序兜底（P0 不引入租约，D8）。
    """
    active = (
        db.query(PipelineRun)
        .filter(
            PipelineRun.workflow_id == workflow.id,
            PipelineRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .first()
    )
    if active is not None:
        raise PipelineConflictError(f"流水线「{workflow.name}」已有进行中的运行，请稍后再试")
    run = PipelineRun(
        workflow_id=workflow.id,
        workspace_id=workflow.workspace_id,
        trigger=trigger,
        trigger_payload=dict(payload or {}),
        status=RUN_STATUS_PENDING,
        stats={},
        error_message="",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_pipeline_in_background(db_session_factory: Callable[[], Session], run_id: int) -> None:
    """在后台线程中执行一次运行（线程生命周期与治理任务同构）."""

    def _worker() -> None:
        session = db_session_factory()
        try:
            execute_pipeline_run(session, run_id)
        finally:
            session.close()

    thread = threading.Thread(target=_worker, daemon=True)
    with _background_lock:
        _background_threads.append(thread)
    thread.start()


def join_background_threads(timeout: float = 10.0) -> None:
    """等待全部流水线后台线程结束（测试收尾与关停时使用）."""
    with _background_lock:
        threads = list(_background_threads)
        _background_threads.clear()
    for thread in threads:
        thread.join(timeout=timeout)


def execute_pipeline_run(db: Session, run_id: int) -> None:
    """执行一次运行：读 ``compiled`` IR，按拓扑序执行 job / step，落结论与发现物."""
    run = db.get(PipelineRun, run_id)
    if run is None:  # pragma: no cover - 运行时记录已被删除
        return
    workflow = db.get(PipelineWorkflow, run.workflow_id)
    started = time.perf_counter()
    engine = db.get_bind()
    run.status = RUN_STATUS_RUNNING
    db.commit()

    if workflow is None:  # pragma: no cover - 定义在运行前被删除（外键级联本应删除 run）
        _finish(
            db,
            run,
            status=RUN_STATUS_FAILED,
            stats=_empty_stats(started),
            error_message="流水线定义已删除",
            engine=engine,
        )
        return

    try:
        ir = WorkflowIR.from_dict(workflow.compiled or {})
        stats = _execute_ir(db, run, ir, started)
        status = _run_status(stats)
        error_message = ""
    except Exception as exc:  # pragma: no cover - 引擎级兜底（检查异常已在 step 内隔离）
        logger.exception("流水线运行 %s 失败: %s", run_id, exc)
        stats = _empty_stats(started)
        status = RUN_STATUS_FAILED
        error_message = str(exc)

    _finish(db, run, status=status, stats=stats, error_message=error_message, engine=engine)


def _finish(
    db: Session,
    run: PipelineRun,
    *,
    status: str,
    stats: dict[str, Any],
    error_message: str,
    engine: Any,
) -> None:
    """落运行状态 / 汇总，写事件流并做 WAL 收尾."""
    run.status = status
    run.stats = stats
    run.error_message = error_message[:2000]
    db.commit()
    record_event(
        db,
        "pipeline.run",
        summary=f"流水线运行 #{run.id} 完成：{status}",
        target_type="pipeline_run",
        target_id=run.id,
        workspace_id=run.workspace_id,
        detail={
            "status": status,
            "findings": stats.get("findings", {}),
            "duration_ms": stats.get("duration_ms", 0),
        },
    )
    checkpoint_wal(engine)


def _execute_ir(db: Session, run: PipelineRun, ir: WorkflowIR, started: float) -> dict[str, Any]:
    """按拓扑序执行 job，返回汇总 ``stats``（含逐 job / step 结论树）."""
    context: dict[str, Any] = {"vars": {}, "on": run.trigger_payload, "jobs": {}}
    warnings: list[str] = []
    context["vars"] = _evaluate_vars(ir, context, warnings)
    ctx = CheckContext(db, run.workspace_id)
    counts = dict.fromkeys(SEVERITIES, 0)
    check_counts: dict[str, int] = {}
    job_stats: list[dict[str, Any]] = []
    jobs_done = 0

    for job in topological_jobs(ir.jobs):
        needed = [context["jobs"][need]["conclusion"] for need in job.needs if need in context["jobs"]]
        needs_ok = all(conclusion == CONCLUSION_SUCCESS for conclusion in needed)
        if needs_ok and job.condition is not None:
            needs_ok = _evaluate_condition(job, context, warnings)
        if not needs_ok:
            conclusion = CONCLUSION_SKIPPED
            steps_stats: list[dict[str, Any]] = []
        else:
            jobs_done += 1
            steps_stats, conclusion = _run_job(db, run, ctx, job, context, warnings, counts, check_counts)
        context["jobs"][job.job_id] = {"conclusion": conclusion}
        job_stats.append({"id": job.job_id, "conclusion": conclusion, "steps": steps_stats})

    return {
        "jobs_total": len(ir.jobs),
        "jobs_done": jobs_done,
        "steps_total": sum(len(job.steps) for job in topological_jobs(ir.jobs)),
        "findings": counts,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "jobs": job_stats,
        "warnings": warnings,
    }


def _evaluate_vars(ir: WorkflowIR, context: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    """按声明顺序求值 ``vars``（可引用更早声明的变量与触发上下文）."""
    resolved: dict[str, Any] = {}
    for key, value in ir.vars.items():
        resolved[key] = _evaluate_value(value, {**context, "vars": dict(resolved)}, warnings, f"vars.{key}")
    return resolved


def _evaluate_condition(job: JobIR, context: dict[str, Any], warnings: list[str]) -> bool:
    """求值 ``jobs.<id>.if``；失败按 ``false`` 处理并记 warning（边界 3）."""
    try:
        return bool(evaluate_expression(job.condition or "", context))
    except ExpressionEvalError as exc:
        warnings.append(f"jobs.{job.job_id}.if 求值失败，按 false 处理：{exc}")
        return False


def _run_job(
    db: Session,
    run: PipelineRun,
    ctx: CheckContext,
    job: JobIR,
    context: dict[str, Any],
    warnings: list[str],
    counts: dict[str, int],
    check_counts: dict[str, int],
) -> tuple[list[dict[str, Any]], str]:
    """顺序执行 job 内 step，返回 step 结论树与 job 结论（D9）."""
    step_stats: list[dict[str, Any]] = []
    job_failed = False
    for step in job.steps:
        stats = _run_step(db, run, ctx, step, context, warnings, counts, check_counts)
        step_stats.append(stats)
        if stats["conclusion"] == CONCLUSION_FAILED:
            job_failed = True
    return step_stats, CONCLUSION_FAILED if job_failed else CONCLUSION_SUCCESS


def _run_step(
    db: Session,
    run: PipelineRun,
    ctx: CheckContext,
    step: StepIR,
    context: dict[str, Any],
    warnings: list[str],
    counts: dict[str, int],
    check_counts: dict[str, int],
) -> dict[str, Any]:
    """执行单个 step：求值参数 → 调用检查 → 落发现物 → 推导 step 结论."""
    stats: dict[str, Any] = {
        "uses": step.uses,
        "severity": step.severity,
        "conclusion": CONCLUSION_SUCCESS,
        "findings": dict.fromkeys(SEVERITIES, 0),
        "error": "",
    }
    try:
        spec, runner = require_check(step.uses)
        params = {
            key: _evaluate_value(value, context, warnings, f"jobs.step.{step.uses}.{key}")
            for key, value in step.params.items()
        }
        findings = list(runner(ctx, coerce_params(spec, params)))
    except Exception as exc:
        # 检查实现异常 / 参数解析失败：该 step 失败，其余 step 与 job 继续（边界 4）
        logger.warning("检查动作 %s 执行失败: %s", step.uses, exc)
        stats["conclusion"] = CONCLUSION_FAILED
        stats["error"] = str(exc)[:500]
        return stats

    existing = check_counts.get(step.uses, 0)
    overflow = 0
    has_error = False
    for draft in findings:
        severity = _severity_of(draft, step.severity)
        if existing >= MAX_FINDINGS_PER_CHECK:
            overflow += 1
            continue
        db.add(_finding_row(run, step.uses, severity, draft))
        existing += 1
        counts[severity] += 1
        stats["findings"][severity] += 1
        has_error = has_error or severity == SEVERITY_ERROR
    check_counts[step.uses] = existing
    if overflow:
        db.add(
            _finding_row(
                run,
                step.uses,
                SEVERITY_INFO,
                FindingDraft(
                    message=f"另有 {overflow} 条 {step.uses} 发现被截断",
                    detail={"truncated": overflow, "limit": MAX_FINDINGS_PER_CHECK},
                ),
            )
        )
        counts[SEVERITY_INFO] += 1
        stats["findings"][SEVERITY_INFO] += 1
    if has_error and not step.continue_on_error:
        stats["conclusion"] = CONCLUSION_FAILED
    return stats


def _severity_of(draft: FindingDraft, default: str) -> str:
    """发现物严重度：动作显式声明优先，否则取 step 默认."""
    severity = draft.severity or default
    if severity not in SEVERITY_RANK:
        return default
    return severity


def _finding_row(run: PipelineRun, check: str, severity: str, draft: FindingDraft) -> PipelineFinding:
    """构造发现物行（消息截断到列宽，定位信息不含业务值）."""
    return PipelineFinding(
        run_id=run.id,
        check=check[:64],
        severity=severity,
        target_type=str(draft.target_type or "")[:16],
        target_id=draft.target_id,
        locator=dict(draft.locator or {}),
        message=str(draft.message)[:500],
        detail=dict(draft.detail or {}),
    )


def _evaluate_value(value: Any, context: dict[str, Any], warnings: list[str], what: str) -> Any:
    """递归求值 ``${{ }}`` 表达式；列表逐项求值，失败记 warning 并置 ``None``."""
    if is_expression(value):
        try:
            return evaluate_expression(str(value), context)
        except ExpressionEvalError as exc:
            warnings.append(f"{what} 求值失败：{exc}")
            return None
    if isinstance(value, list):
        return [_evaluate_value(item, context, warnings, f"{what}[{index}]") for index, item in enumerate(value)]
    return value


def _run_status(stats: dict[str, Any]) -> str:
    """由 job 结论与 finding 计数推导运行结论（I4 / D9）."""
    if any(job["conclusion"] == CONCLUSION_FAILED for job in stats.get("jobs", [])):
        return RUN_STATUS_FAILED
    findings = stats.get("findings", {})
    # 任意发现物都意味着"非全绿"：error 被 continue-on-error 豁免后同样归 partial
    if any(int(findings.get(severity, 0)) for severity in SEVERITIES):
        return RUN_STATUS_PARTIAL
    return RUN_STATUS_SUCCESS


def _empty_stats(started: float) -> dict[str, Any]:
    """引擎级失败时的最小汇总."""
    return {
        "jobs_total": 0,
        "jobs_done": 0,
        "steps_total": 0,
        "findings": dict.fromkeys(SEVERITIES, 0),
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "jobs": [],
        "warnings": [],
    }


__all__ = [
    "MAX_FINDINGS_PER_CHECK",
    "create_run",
    "execute_pipeline_run",
    "join_background_threads",
    "run_pipeline_in_background",
]
