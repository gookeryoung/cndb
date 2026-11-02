"""策略执行编排：租约 → 轮次抓取 → 去重 → 筛选 → 落点 → 留痕（ADR 0085 §3）.

唯一执行入口 :func:`execute_strategy`（手动 / CLI / 调度 / 预览共用）。
本期（P0）跑单轮：轮次循环结构已就位，扩展词与多轮在 P1 接入。

失败口径（I5）：

- 单渠道失败只记 ``detail.channel_errors``，其它渠道继续；
- 全部渠道失败 → ``failed``；部分失败 / 落点失败 / 预算触顶 → ``partial``；
- 已落表数据不回滚（``upsert_rows`` 幂等，重跑安全）。
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.orm import Session

from cndb.plugins.acquisition.models import (
    AcquisitionRound,
    AcquisitionRun,
    AcquisitionStrategy,
    ReviewState,
    RunStatus,
    RunTrigger,
)
from cndb.plugins.acquisition.services.channels import ChannelSpec, build_channel_specs
from cndb.plugins.acquisition.services.rules.dedupe import dedupe_key
from cndb.plugins.acquisition.services.rules.expr import RuleError, render_query
from cndb.plugins.acquisition.services.rules.filter import FilterRule, apply_filters
from cndb.plugins.acquisition.services.targets import (
    TargetReport,
    dispatch_table_target,
    existing_keys,
)
from cndb.plugins.datasource.providers.base import FetchFn
from cndb.plugins.datasource.services.pipeline import run_pipeline
from cndb.plugins.datasource.services.scheduler import LEASE_TTL_SECONDS, default_owner

logger = logging.getLogger(__name__)

__all__ = [
    "SAMPLE_SIZE",
    "StrategyBusyError",
    "StrategyExecution",
    "execute_strategy",
    "preview_strategy",
]

#: 预览返回的样例行数
SAMPLE_SIZE = 5
#: 单次运行默认请求预算（``iteration.budget.max_requests`` 缺省时）
DEFAULT_MAX_REQUESTS = 1000
#: 累计条目上限（``iteration.stop.max_total_items`` 缺省时）
DEFAULT_MAX_TOTAL_ITEMS = 5000


class StrategyBusyError(RuntimeError):
    """同一策略已有运行在跑（租约被占用）."""


@dataclass(slots=True)
class StrategyExecution:
    """一次执行的产物（``run`` 在预览态为 ``None``）."""

    run: AcquisitionRun | None = None
    round: AcquisitionRound | None = None
    report: TargetReport = field(default_factory=TargetReport)
    samples: list[dict[str, Any]] = field(default_factory=list)
    collected: int = 0
    after_dedup: int = 0
    after_filter: int = 0
    by_channel: dict[str, int] = field(default_factory=dict)
    channel_errors: list[dict[str, str]] = field(default_factory=list)
    status: str = RunStatus.SUCCESS.value


# ── 租约 ─────────────────────────────────────────


def _acquire_lease(db: Session, strategy: AcquisitionStrategy, now: dt.datetime) -> bool:
    """抢占策略租约（过期可抢）；返回是否拿到."""
    stmt = (
        update(AcquisitionStrategy)
        .where(
            AcquisitionStrategy.id == strategy.id,
            or_(
                AcquisitionStrategy.lease_owner.is_(None),
                AcquisitionStrategy.lease_until.is_(None),
                AcquisitionStrategy.lease_until < now,
            ),
        )
        .values(
            lease_owner=default_owner(),
            lease_until=now + dt.timedelta(seconds=LEASE_TTL_SECONDS),
        )
        .execution_options(synchronize_session=False)
    )
    result = cast("CursorResult[Any]", db.execute(stmt))
    db.commit()
    db.refresh(strategy)
    return bool(result.rowcount)


def _release_lease(db: Session, strategy: AcquisitionStrategy) -> None:
    strategy.lease_owner = None
    strategy.lease_until = None
    db.add(strategy)
    db.commit()


# ── 快照 ─────────────────────────────────────────


def snapshot_rules(strategy: AcquisitionStrategy) -> dict[str, Any]:
    """运行期规则快照（不含任何 Key / 个人地址，可随运行记录导出）."""
    return {
        "rule_version": strategy.rule_version,
        "scope": dict(strategy.scope or {}),
        "filter_rule": dict(strategy.filter_rule or {}),
        "targets": list(strategy.targets or []),
        "iteration": dict(strategy.iteration or {}),
        "llm": dict(strategy.llm or {}),
    }


def identity_fields(strategy: AcquisitionStrategy) -> tuple[str, ...]:
    """表落点的业务身份（``match_keys``）；台账去重键与行幂等共用同一组字段（D4）."""
    for target in list(strategy.targets or []):
        if str(target.get("kind")) == "table":
            return tuple(str(key) for key in (target.get("match_keys") or ()) if str(key).strip())
    return ()


def _ledger_blocks(strategy: AcquisitionStrategy) -> bool:
    """台账是否拦截已采条目：仅「只追加」落点（文档）需要，表落点靠 upsert 更新（D4）."""
    kinds = {str(target.get("kind")) for target in list(strategy.targets or [])}
    return "document" in kinds and "table" not in kinds


# ── 执行 ─────────────────────────────────────────


def execute_strategy(
    db: Session,
    strategy: AcquisitionStrategy,
    *,
    trigger: RunTrigger | str = RunTrigger.MANUAL,
    user: Any = None,
    fetch: FetchFn | None = None,
    now: dt.datetime | None = None,
    dry_run: bool = False,
) -> StrategyExecution:
    """执行一次策略（``dry_run=True`` 时只抓取 + 筛选，不写表 / 不写台账 / 不落运行）."""
    started = _as_utc(now or dt.datetime.now(dt.UTC))
    today = started.date().isoformat()
    clock = time.perf_counter()

    if dry_run:
        return _run_rounds(
            db,
            strategy,
            user=user,
            fetch=fetch,
            today=today,
            clock=clock,
            dry_run=True,
        )

    if not _acquire_lease(db, strategy, started):
        raise StrategyBusyError("同一策略已有运行在进行中")

    run: AcquisitionRun | None = None
    try:
        run = AcquisitionRun(
            strategy_id=strategy.id,
            trigger=str(trigger),
            status=RunStatus.RUNNING.value,
            rule_snapshot=snapshot_rules(strategy),
            started_at=started,
            progress=2,
            progress_message="正在解析渠道...",
        )
        db.add(run)
        strategy.last_run_at = started
        strategy.last_status = RunStatus.RUNNING.value
        db.add(strategy)
        db.commit()
        db.refresh(run)
        execution = _run_rounds(
            db,
            strategy,
            user=user,
            fetch=fetch,
            today=today,
            clock=clock,
            dry_run=False,
            run=run,
        )
        _finalize(db, strategy, execution, started=started, clock=clock)
        return execution
    except StrategyBusyError:
        raise
    except Exception as exc:  # 异常不外抛给调度器，落 failed 后返回
        logger.warning("采集策略 %s 执行失败: %s", strategy.id, exc, exc_info=True)
        db.rollback()
        if run is not None:
            run.status = RunStatus.FAILED.value
            run.error_message = str(exc)[:1000]
            run.finished_at = _as_utc(started)
            run.duration_ms = int((time.perf_counter() - clock) * 1000)
            db.add(run)
            db.commit()
        strategy.last_status = RunStatus.FAILED.value
        db.add(strategy)
        db.commit()
        return StrategyExecution(run=run, status=RunStatus.FAILED.value)
    finally:
        _release_lease(db, strategy)


def _run_rounds(
    db: Session,
    strategy: AcquisitionStrategy,
    *,
    user: Any,
    fetch: FetchFn | None,
    today: str,
    clock: float,
    dry_run: bool,
    run: AcquisitionRun | None = None,
) -> StrategyExecution:
    """单轮执行（P0）：抓取 → 去重 → 筛选 → 落点 → 轮次留痕."""
    scope = dict(strategy.scope or {})
    iteration = dict(strategy.iteration or {})
    budget_cfg = dict(iteration.get("budget") or {})
    max_requests = int(budget_cfg.get("max_requests") or DEFAULT_MAX_REQUESTS)
    stop_cfg = dict(iteration.get("stop") or {})
    max_total_items = int(stop_cfg.get("max_total_items") or DEFAULT_MAX_TOTAL_ITEMS)

    try:
        query = render_query(str(scope.get("query") or ""), {"today": today})
    except RuleError as exc:
        raise RuleError(f"scope.query 渲染失败: {exc}") from exc

    specs, channel_errors = build_channel_specs(
        db,
        workspace_id=strategy.workspace_id,
        scope=scope,
        query=query,
        today=today,
        user_id=getattr(user, "id", None) or strategy.created_by_id,
    )
    expand_errors = len(channel_errors)

    if run is not None:
        run.progress = 8
        run.progress_message = f"已展开 {len(specs)} 个渠道，开始抓取（检索式：{query[:80]}）"
        db.add(run)
        db.commit()

    collected: list[dict[str, Any]] = []
    by_channel: dict[str, int] = {}
    requests = 0
    budget_exhausted = False

    for spec in specs:
        if requests >= max_requests:
            budget_exhausted = True
            break
        rows, used, error = _fetch_channel(spec, fetch=fetch)
        requests += used
        if error is not None:
            channel_errors.append({"channel": spec.channel, "error": error})
            by_channel[spec.channel] = 0
            continue
        by_channel[spec.channel] = len(rows)
        collected.extend(rows)

    if run is not None:
        run.progress = 50
        run.progress_message = f"抓取完成（{len(collected)} 条），正在跨来源去重..."
        db.add(run)
        db.commit()

    # 跨轮 / 跨运行去重：运行内 seen 必去重；台账拦截只对「只追加」落点（文档）生效，
    # 表落点的重复由 upsert（match_keys）承担 —— 拦截会变成「永不更新」（D4）
    identity = identity_fields(strategy)
    unique: list[dict[str, Any]] = []
    keys: list[str] = []
    seen: set[str] = set()
    for item in collected:
        key = dedupe_key(item, str(item.get("channel") or ""), identity)
        if key in seen:
            continue
        seen.add(key)
        keys.append(key)
        unique.append(item)
    known = existing_keys(db, strategy.id, keys) if keys and _ledger_blocks(strategy) else set()
    fresh = [item for item, key in zip(unique, keys, strict=True) if key not in known]

    if run is not None:
        run.progress = 62
        run.progress_message = f"去重后新增 {len(fresh)} 条，正在应用筛选规则..."
        db.add(run)
        db.commit()

    rule = FilterRule.from_dict(strategy.filter_rule)
    filtered = apply_filters(fresh, rule)
    items = filtered.items[:max_total_items]

    report = TargetReport()
    if not dry_run:
        report = dispatch_table_target(
            db,
            strategy=strategy,
            items=items,
            run_id=run.id if run is not None else None,
            round_no=1,
            user=user,
            identity=identity,
        )
        if run is not None:
            run.progress = 88
            run.progress_message = "落点写入完成，正在记录轮次..."
            db.add(run)
            db.commit()

    status = _decide_status(
        total_channels=len(specs) + expand_errors,
        failed_channels=len(channel_errors),
        report_errors=report.errors,
        budget_exhausted=budget_exhausted,
    )

    stats = {
        "total_collected": len(collected),
        "after_dedup": len(fresh),
        "after_filter": len(items),
        "by_channel": by_channel,
        "channel_errors": channel_errors,
    }

    round_row: AcquisitionRound | None = None
    if not dry_run and run is not None:
        round_row = AcquisitionRound(
            run_id=run.id,
            round_no=1,
            query=query[:500],
            channels=[spec.channel for spec in specs],
            stats=stats,
            new_items=report.written,
            accumulated_items=report.written,
            top_keywords=[],
            next_query="",
            gap={"target": max_total_items, "covered": len(items), "missing": max(0, max_total_items - len(items))},
            review_state=ReviewState.AUTO.value,
            stop_reason="max_rounds" if items else "empty_round",
            status=status,
            duration_ms=int((time.perf_counter() - clock) * 1000),
        )
        db.add(round_row)
        run.round_count = 1
        run.fetched = len(collected)
        run.inserted = report.inserted
        run.updated = report.updated
        run.skipped = report.skipped
        run.budget_used = {"requests": requests, "rows": report.written, "llm_calls": 0, "llm_tokens": 0}
        run.detail = {
            "channels": by_channel,
            "channel_errors": channel_errors,
            "target_errors": report.errors,
            "budget_exhausted": budget_exhausted,
        }
        db.add(run)
        db.commit()
        db.refresh(round_row)

    return StrategyExecution(
        run=run,
        round=round_row,
        report=report,
        samples=items[:SAMPLE_SIZE],
        collected=len(collected),
        after_dedup=len(fresh),
        after_filter=len(items),
        by_channel=by_channel,
        channel_errors=channel_errors,
        status=status,
    )


def _fetch_channel(
    spec: ChannelSpec,
    *,
    fetch: FetchFn | None,
) -> tuple[list[dict[str, Any]], int, str | None]:
    """抓取单个渠道；返回 ``(候选行, 请求数, 错误文案)``."""
    try:
        outcome = run_pipeline(spec.spec, fetch=fetch, rate_limit_ms=spec.rate_limit_ms)
    except Exception as exc:
        logger.info("渠道 %s 抓取失败: %s", spec.channel, exc)
        return [], 0, str(exc)[:300]

    rows: list[dict[str, Any]] = []
    for row in list(outcome.rows)[: spec.max_items]:
        item = dict(row)
        item.setdefault("channel", spec.channel)
        rows.append(item)
    return rows, outcome.plans, None


def _decide_status(
    *,
    total_channels: int,
    failed_channels: int,
    report_errors: Sequence[Mapping[str, str]],
    budget_exhausted: bool,
) -> str:
    """运行状态判定（I5）：无渠道 / 全渠道失败 → failed；有任一部分失败或预算触顶 → partial."""
    if total_channels == 0 or failed_channels >= total_channels:
        return RunStatus.FAILED.value
    if failed_channels or report_errors or budget_exhausted:
        return RunStatus.PARTIAL.value
    return RunStatus.SUCCESS.value


def _finalize(
    db: Session,
    strategy: AcquisitionStrategy,
    execution: StrategyExecution,
    *,
    started: dt.datetime,
    clock: float,
) -> None:
    """写运行收尾状态与策略 last_status（租约在调用方释放）."""
    run = execution.run
    if run is not None:
        run.status = execution.status
        run.progress = 100
        run.progress_message = _progress_message(execution)
        run.finished_at = _as_utc(started)
        run.duration_ms = int((time.perf_counter() - clock) * 1000)
        if execution.status == RunStatus.FAILED.value and not run.error_message:
            run.error_message = "全部渠道均未返回数据或均失败"
        db.add(run)
    strategy.last_status = execution.status
    db.add(strategy)
    db.commit()


def _progress_message(execution: StrategyExecution) -> str:
    return (
        f"采集完成：抓取 {execution.collected} 条 / 去重后新增 {execution.after_dedup} 条 / "
        f"筛选后 {execution.after_filter} 条 / 写入 {execution.report.written} 行"
    )


def preview_strategy(
    db: Session,
    strategy: AcquisitionStrategy,
    *,
    fetch: FetchFn | None = None,
    now: dt.datetime | None = None,
    user: Any = None,
) -> StrategyExecution:
    """预览：真实抓取 + 真实筛选，**不写表 / 不写台账 / 不落运行记录**（I6）."""
    return execute_strategy(db, strategy, user=user, fetch=fetch, now=now, dry_run=True)


def list_runs(db: Session, strategy_id: int, *, limit: int = 20) -> list[AcquisitionRun]:
    """按时间倒序列出运行记录（前端轮询 / CLI 展示）."""
    stmt = (
        select(AcquisitionRun)
        .where(AcquisitionRun.strategy_id == strategy_id)
        .order_by(AcquisitionRun.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def _as_utc(value: dt.datetime) -> dt.datetime:
    """统一成带时区 UTC（SQLite 读出来是 naive）."""
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
