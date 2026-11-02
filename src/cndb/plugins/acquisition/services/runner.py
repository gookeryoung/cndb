"""策略执行编排：租约 → 轮次循环（抓取/去重/筛选/落点/扩展/复核）→ 留痕（ADR 0085 §3）.

唯一执行入口：

- :func:`execute_strategy`  正常执行（手动 / CLI / 调度共用；多轮迭代 + 复核闸口）
- :func:`resume_run`        ``awaiting_review`` 的运行续跑（用户可调，也可不调）
- :func:`preview_strategy`  只抓首轮、零写入（预览）

失败口径（I5）：单渠道 / 单落点失败只降级该渠道 / 该条，已落数据不回滚；
全渠道失败 → ``failed``；部分失败、预算触顶 → ``partial``；复核暂停 → ``awaiting_review``。
"""

from __future__ import annotations

import datetime as dt
import logging
import re
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
from cndb.plugins.acquisition.services.rules.expand import apply_user_edit, build
from cndb.plugins.acquisition.services.rules.expr import RuleError, render_query
from cndb.plugins.acquisition.services.rules.filter import FilterRule, apply_filters
from cndb.plugins.acquisition.services.rules.keywords import extract_keywords
from cndb.plugins.acquisition.services.rules.stop import decide_stop
from cndb.plugins.acquisition.services.targets import (
    TargetReport,
    dispatch_document_target,
    dispatch_table_target,
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
    "identity_fields",
    "preview_strategy",
    "resume_run",
    "snapshot_rules",
]

#: 预览返回的样例行数
SAMPLE_SIZE = 5
#: 单次运行默认请求预算
DEFAULT_MAX_REQUESTS = 1000
#: 累计条目上限
DEFAULT_MAX_TOTAL_ITEMS = 5000
#: 关键词语料上限（条）：控制内存，够覆盖跨轮词频
CORPUS_LIMIT = 2000
#: 每轮默认扩展词数
DEFAULT_TOP_KEYWORDS = 5
#: 复核模式（manual 与 ReviewState 的字面量保持一致）
REVIEW_MANUAL = "manual"


class StrategyBusyError(RuntimeError):
    """同一策略已有运行在跑（租约被占用）."""


@dataclass(slots=True)
class StrategyExecution:
    """一次执行的产物（预览态 ``run`` 为 ``None``）."""

    run: AcquisitionRun | None = None
    round: AcquisitionRound | None = None
    report: TargetReport = field(default_factory=TargetReport)
    samples: list[dict[str, Any]] = field(default_factory=list)
    collected: int = 0
    after_dedup: int = 0
    after_filter: int = 0
    #: 预览时按原因聚合的拦截计数（must_have / date / …），供前端解释「命中 0」
    rejected_by: dict[str, int] = field(default_factory=dict)
    by_channel: dict[str, int] = field(default_factory=dict)
    channel_errors: list[dict[str, str]] = field(default_factory=list)
    status: str = RunStatus.SUCCESS.value
    rounds: int = 0
    llm: dict[str, Any] = field(default_factory=dict)


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
        .values(lease_owner=default_owner(), lease_until=now + dt.timedelta(seconds=LEASE_TTL_SECONDS))
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


# ── 规则辅助 ─────────────────────────────────────


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


def _base_terms(base_query: str) -> list[str]:
    """基础检索式里已有的词（不重复用作扩展词）."""
    return [word.lower() for word in re.findall(r"[\w\u4e00-\u9fff]{2,}", str(base_query or ""))]


def _review_mode(iteration: Mapping[str, Any]) -> str:
    expand = iteration.get("expand")
    if isinstance(expand, Mapping):
        mode = str(expand.get("review") or ReviewState.AUTO.value)
        if mode in (ReviewState.AUTO.value, ReviewState.LLM.value, REVIEW_MANUAL):
            return mode
    return ReviewState.AUTO.value


def _llm_enabled(strategy: AcquisitionStrategy, action: str = "keyword_refine") -> bool:
    """语义辅助开关：``llm.enabled`` 为真，且动作在 ``llm.actions`` 白名单里（空 = 全部允许）."""
    config = dict(strategy.llm or {})
    if not config.get("enabled"):
        return False
    actions = config.get("actions")
    if isinstance(actions, list) and actions:
        return action in {str(item) for item in actions}
    return True


def table_targets_present(strategy: AcquisitionStrategy) -> bool:
    return any(str(target.get("kind")) == "table" for target in list(strategy.targets or []))


def document_targets_present(strategy: AcquisitionStrategy) -> bool:
    return any(str(target.get("kind")) == "document" for target in list(strategy.targets or []))


# ── 执行入口 ─────────────────────────────────────


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
    """执行一次策略（``dry_run=True`` 只抓首轮 + 筛选，零写入）."""
    started = _as_utc(now or dt.datetime.now(dt.UTC))
    today = started.date().isoformat()
    clock = time.perf_counter()

    if dry_run:
        return _preview_pass(db, strategy, user=user, fetch=fetch, today=today)

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
        execution = _run_loop(
            db,
            strategy,
            run,
            user=_resolve_user(db, strategy, user),
            fetch=fetch,
            today=today,
            start_round=1,
            current_query=_render_base(strategy, today),
        )
        _finalize(db, strategy, execution, started=started, clock=clock, user=_resolve_user(db, strategy, user))
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


def resume_run(
    db: Session,
    run: AcquisitionRun,
    *,
    user: Any = None,
    fetch: FetchFn | None = None,
    now: dt.datetime | None = None,
    keywords: Sequence[str] | None = None,
    query: str | None = None,
    timeout: bool = False,
) -> StrategyExecution:
    """续跑 ``awaiting_review`` 的运行：可带关键词 / 检索式（调整），也可不带（不调）.

    ``timeout=True`` 表示由调度超时兜底发起（D14：72h 未确认按「不调」续跑），
    在 ``run.detail.review_timeout`` 留痕，便于区分「用户没调」与「没人管」。
    """
    strategy = db.get(AcquisitionStrategy, run.strategy_id)
    if strategy is None:
        raise RuleError("采集策略不存在")
    if run.status != RunStatus.AWAITING_REVIEW.value:
        raise RuleError(f"运行不处于待复核状态（当前 {run.status}）")

    started = _as_utc(now or dt.datetime.now(dt.UTC))
    clock = time.perf_counter()
    pending = _pending_round(db, run.id)
    if pending is None:
        raise RuleError("没有待复核的轮次")

    if not _acquire_lease(db, strategy, started):
        raise StrategyBusyError("同一策略已有运行在进行中")

    try:
        next_query = (query or "").strip() or pending.next_query
        if not next_query:
            next_query = _render_base(strategy, started.date().isoformat())
        if keywords:
            pending.top_keywords = apply_user_edit(_keywords_from_round(pending), list(keywords))
            pending.next_query = next_query[:500]
        pending.review_state = ReviewState.CONFIRMED.value
        if timeout:
            run.detail = {**dict(run.detail or {}), "review_timeout": True}
        run.status = RunStatus.RUNNING.value
        run.progress_message = f"第 {pending.round_no} 轮复核完成，继续第 {pending.round_no + 1} 轮"
        db.add_all([pending, run])
        db.commit()

        execution = _run_loop(
            db,
            strategy,
            run,
            user=_resolve_user(db, strategy, user),
            fetch=fetch,
            today=started.date().isoformat(),
            start_round=pending.round_no + 1,
            current_query=next_query,
            execution=_seed_execution(run),
        )
        _finalize(db, strategy, execution, started=started, clock=clock, user=_resolve_user(db, strategy, user))
        return execution
    finally:
        _release_lease(db, strategy)


# ── 轮次循环 ─────────────────────────────────────


def _run_loop(
    db: Session,
    strategy: AcquisitionStrategy,
    run: AcquisitionRun,
    *,
    user: Any,
    fetch: FetchFn | None,
    today: str,
    start_round: int,
    current_query: str,
    execution: StrategyExecution | None = None,
) -> StrategyExecution:
    """逐轮执行：抓取 → 去重 → 筛选 → 落点 → 扩展 → 复核闸口 → 停止判定."""
    scope = dict(strategy.scope or {})
    iteration = dict(strategy.iteration or {})
    budget_cfg = dict(iteration.get("budget") or {})
    stop_cfg = dict(iteration.get("stop") or {})
    max_requests = int(budget_cfg.get("max_requests") or DEFAULT_MAX_REQUESTS)
    max_total_items = int(stop_cfg.get("max_total_items") or DEFAULT_MAX_TOTAL_ITEMS)
    max_rounds = max(1, min(int(iteration.get("max_rounds") or 1), 5))
    top_keywords = int(iteration.get("top_keywords_per_round") or DEFAULT_TOP_KEYWORDS)
    review_mode = _review_mode(iteration)
    identity = identity_fields(strategy)
    rule = FilterRule.from_dict(strategy.filter_rule)
    base_terms = _base_terms(current_query)

    state = execution or StrategyExecution()
    state.run = run
    counters = _counters_from_run(run)
    corpus: list[dict[str, Any]] = []
    used_keywords: set[str] = set()
    consecutive_empty = 0
    status: str | None = None

    for round_no in range(start_round, max_rounds + 1):
        # 取消只在轮边界生效（不中断在途 HTTP）：刷新一次能看到其它进程写入的取消标记
        db.refresh(run)
        if (dict(run.detail or {})).get("cancel_requested"):
            status = RunStatus.CANCELLED.value
            run.detail = {**dict(run.detail or {}), "cancelled_at_round": round_no - 1}
            break
        round_clock = time.perf_counter()
        run.progress = min(95, 5 + int((round_no - 1) * 80 / max_rounds))
        run.progress_message = f"第 {round_no}/{max_rounds} 轮：抓取中（检索式：{current_query[:80]}）"
        db.add(run)
        db.commit()

        specs, channel_errors = build_channel_specs(
            db,
            workspace_id=strategy.workspace_id,
            scope=scope,
            query=current_query,
            today=today,
            user_id=getattr(user, "id", None) or strategy.created_by_id,
        )
        total_channels = len(specs) + len(channel_errors)

        collected: list[dict[str, Any]] = []
        by_channel: dict[str, int] = {}
        budget_exhausted = counters["requests"] >= max_requests

        for spec in specs:
            if budget_exhausted:
                break
            rows, used_requests, error = _fetch_channel(spec, fetch=fetch)
            counters["requests"] += used_requests
            if error is not None:
                channel_errors.append({"channel": spec.channel, "error": error})
                by_channel[spec.channel] = 0
                continue
            by_channel[spec.channel] = len(rows)
            collected.extend(rows)
            if counters["requests"] >= max_requests:
                budget_exhausted = True

        fresh, _keys = _dedupe_batch(collected)
        filtered = apply_filters(fresh, rule)

        remaining = max(0, max_total_items - counters["rows"])
        items = filtered.items[:remaining]
        report = TargetReport()
        if items:
            if table_targets_present(strategy):
                _merge_report(
                    report,
                    dispatch_table_target(
                        db,
                        strategy=strategy,
                        items=items,
                        run_id=run.id,
                        round_no=round_no,
                        user=user,
                        identity=identity,
                    ),
                )
            if document_targets_present(strategy):
                _merge_report(
                    report,
                    dispatch_document_target(
                        db,
                        strategy=strategy,
                        items=items,
                        run_id=run.id,
                        round_no=round_no,
                        user=user,
                    ),
                )

        counters["fetched"] += len(collected)
        counters["dedup"] += len(fresh)
        counters["filtered"] += len(items)
        counters["rows"] += report.written
        counters["inserted"] += report.inserted
        counters["updated"] += report.updated
        counters["skipped"] += report.skipped
        counters["docs_created"] += report.docs_created
        counters["docs_updated"] += report.docs_updated
        counters["docs_skipped"] += report.docs_skipped
        corpus.extend(items)
        if len(corpus) > CORPUS_LIMIT:
            del corpus[: len(corpus) - CORPUS_LIMIT]

        keywords, llm_meta = _keywords_for_next_round(
            db,
            strategy,
            run,
            user=user,
            corpus=corpus,
            base_query=current_query,
            used=used_keywords | set(base_terms),
            top_n=top_keywords,
            mode=review_mode,
            counters=counters,
            budget_cfg=budget_cfg,
        )
        if llm_meta:
            state.llm = llm_meta
            run.detail = {**dict(run.detail or {}), "llm": _merge_llm_detail(run.detail, llm_meta)}
        next_query = build(current_query, [item for item in keywords if not item.get("dropped")], ())
        used_keywords.update(str(item.get("term") or "").lower() for item in keywords if item.get("term"))

        consecutive_empty = consecutive_empty + 1 if report.changed == 0 else 0
        stop_reason = decide_stop(
            round_no=round_no,
            max_rounds=max_rounds,
            new_items=report.changed,
            stop_config=stop_cfg,
            consecutive_empty=consecutive_empty,
            budget_exhausted=budget_exhausted,
        )
        pause = stop_reason is None and review_mode == REVIEW_MANUAL and next_query != current_query

        round_status = _round_status(
            channel_errors,
            report.errors,
            budget_exhausted,
            total_channels=total_channels,
        )
        round_row = AcquisitionRound(
            run_id=run.id,
            round_no=round_no,
            query=current_query[:500],
            channels=[spec.channel for spec in specs],
            stats={
                "total_collected": len(collected),
                "after_dedup": len(fresh),
                "after_filter": len(items),
                "by_channel": by_channel,
                "channel_errors": channel_errors,
                "target_errors": report.errors,
            },
            new_items=report.changed,
            accumulated_items=counters["rows"],
            top_keywords=keywords,
            next_query=next_query[:500],
            gap={"target": max_total_items, "covered": counters["rows"], "missing": remaining},
            review_state=ReviewState.PENDING.value if pause else ReviewState.AUTO.value,
            stop_reason=stop_reason or "",
            status=round_status,
            duration_ms=int((time.perf_counter() - round_clock) * 1000),
        )
        db.add(round_row)
        run.round_count = round_no
        run.fetched = counters["fetched"]
        run.inserted = counters["inserted"]
        run.updated = counters["updated"]
        run.skipped = counters["skipped"]
        run.docs_created = counters["docs_created"]
        run.docs_updated = counters["docs_updated"]
        run.docs_skipped = counters["docs_skipped"]
        run.budget_used = {
            "requests": counters["requests"],
            "rows": counters["rows"],
            "llm_calls": counters["llm_calls"],
            "llm_tokens": counters["llm_tokens"],
        }
        run.detail = {
            **dict(run.detail or {}),
            "channels": by_channel,
            "channel_errors": channel_errors,
            "target_errors": report.errors,
            "budget_exhausted": budget_exhausted,
            "rounds": round_no,
        }
        db.add(run)
        db.commit()
        db.refresh(round_row)

        state.round = round_row
        state.collected = counters["fetched"]
        state.after_dedup = counters["dedup"]
        state.after_filter = counters["filtered"]
        state.by_channel = by_channel
        state.channel_errors = channel_errors
        state.report = report
        state.rounds = round_no

        if pause:
            state.status = RunStatus.AWAITING_REVIEW.value
            return state
        if stop_reason:
            status = round_status
            break
        current_query = next_query

    state.status = status or _aggregate_status(db, run.id)
    return state


def _keywords_for_next_round(
    db: Session,
    strategy: AcquisitionStrategy,
    run: AcquisitionRun,
    *,
    user: Any,
    corpus: Sequence[Mapping[str, Any]],
    base_query: str,
    used: set[str],
    top_n: int,
    mode: str,
    counters: dict[str, int],
    budget_cfg: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """① 迭代产出候选 → ② 模型第二次判断（可跳过）."""
    candidates = extract_keywords(corpus, top_n, exclude=sorted(used))
    if not candidates:
        return [], {}
    deterministic = [
        {"term": item["term"], "count": item["count"], "df": item["df"], "source": "tf", "dropped": False}
        for item in candidates
    ]
    if mode not in (ReviewState.LLM.value, REVIEW_MANUAL) or not _llm_enabled(strategy):
        return deterministic, {}
    max_calls = int(budget_cfg.get("max_llm_calls") or 0)
    if max_calls and counters["llm_calls"] >= max_calls:
        return deterministic, {"degraded": "budget"}

    from cndb.plugins.acquisition.services.ai import refine_keywords

    final, rejected, meta = refine_keywords(
        db,
        user,
        candidates=candidates,
        base_query=base_query,
        used=sorted(used),
        workspace_id=strategy.workspace_id,
        strategy_id=strategy.id,
    )
    counters["llm_calls"] += 0 if meta.get("degraded") else 1
    counters["llm_tokens"] += int(meta.get("tokens") or 0)
    return final, {**meta, "rejected": rejected, "strategy": strategy.id, "run": run.id}


def _preview_pass(
    db: Session,
    strategy: AcquisitionStrategy,
    *,
    user: Any,
    fetch: FetchFn | None,
    today: str,
    query_override: str | None = None,
    filter_override: Mapping[str, Any] | None = None,
) -> StrategyExecution:
    """预览：真实抓取 + 筛选，**不写表 / 不写文档 / 不写台账 / 不落运行记录**（I6）.

    ``query_override`` / ``filter_override`` 用编辑器里尚未保存的表单值试算——否则用户
    改完筛选再点预览，看到的仍是旧规则的结果，容易被误判成「采集不到」。
    """
    scope = dict(strategy.scope or {})
    if query_override is not None and str(query_override).strip():
        try:
            query = render_query(str(query_override), {"today": today})
        except RuleError as exc:
            raise RuleError(f"scope.query 渲染失败: {exc}") from exc
    else:
        query = _render_base(strategy, today)
    specs, channel_errors = build_channel_specs(
        db,
        workspace_id=strategy.workspace_id,
        scope=scope,
        query=query,
        today=today,
        user_id=getattr(user, "id", None) or strategy.created_by_id,
    )
    collected: list[dict[str, Any]] = []
    by_channel: dict[str, int] = {}
    for spec in specs:
        rows, _used, error = _fetch_channel(spec, fetch=fetch)
        if error is not None:
            channel_errors.append({"channel": spec.channel, "error": error})
            by_channel[spec.channel] = 0
            continue
        by_channel[spec.channel] = len(rows)
        collected.extend(rows)

    fresh, _keys = _dedupe_batch(collected)
    rule_payload = strategy.filter_rule if filter_override is None else filter_override
    filtered = apply_filters(fresh, FilterRule.from_dict(rule_payload))
    status = RunStatus.FAILED.value if (not specs and channel_errors) else RunStatus.SUCCESS.value
    return StrategyExecution(
        samples=filtered.items[:SAMPLE_SIZE],
        collected=len(collected),
        after_dedup=len(fresh),
        after_filter=filtered.passed,
        rejected_by=dict(filtered.rejected_by),
        by_channel=by_channel,
        channel_errors=channel_errors,
        status=status,
    )


def preview_strategy(
    db: Session,
    strategy: AcquisitionStrategy,
    *,
    fetch: FetchFn | None = None,
    now: dt.datetime | None = None,
    user: Any = None,
    query: str | None = None,
    filter_rule: Mapping[str, Any] | None = None,
) -> StrategyExecution:
    """预览入口（供 API / CLI 复用）.

    ``query`` / ``filter_rule`` 为可选的表单覆盖值（保存前试算），不落库。
    """
    started = _as_utc(now or dt.datetime.now(dt.UTC))
    return _preview_pass(
        db,
        strategy,
        user=user,
        fetch=fetch,
        today=started.date().isoformat(),
        query_override=query,
        filter_override=filter_rule,
    )


# ── 辅助 ─────────────────────────────────────────


def _render_base(strategy: AcquisitionStrategy, today: str) -> str:
    try:
        return render_query(str((strategy.scope or {}).get("query") or ""), {"today": today})
    except RuleError as exc:
        raise RuleError(f"scope.query 渲染失败: {exc}") from exc


def _resolve_user(db: Session, strategy: AcquisitionStrategy, user: Any) -> Any:
    """文档落点 / 模型调用需要用户上下文：优先显式传入，其次策略创建人."""
    if user is not None:
        return user
    if strategy.created_by_id is None:
        return None
    from cndb.plugins.accounts.models import User

    return db.get(User, strategy.created_by_id)


def _dedupe_batch(collected: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """运行内去重，返回 ``(unique_items, keys)``（键序与 items 对齐）."""
    unique: list[dict[str, Any]] = []
    keys: list[str] = []
    seen: set[str] = set()
    for item in collected:
        key = dedupe_key(item, str(item.get("channel") or ""))
        if key in seen:
            continue
        seen.add(key)
        keys.append(key)
        unique.append(dict(item))
    return unique, keys


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


def _counters_from_run(run: AcquisitionRun) -> dict[str, int]:
    budget = dict(run.budget_used or {})
    return {
        "fetched": int(run.fetched or 0),
        "inserted": int(run.inserted or 0),
        "updated": int(run.updated or 0),
        "skipped": int(run.skipped or 0),
        "rows": int(budget.get("rows") or ((run.inserted or 0) + (run.updated or 0))),
        "requests": int(budget.get("requests") or 0),
        "llm_calls": int(budget.get("llm_calls") or 0),
        "llm_tokens": int(budget.get("llm_tokens") or 0),
        "docs_created": int(run.docs_created or 0),
        "docs_updated": int(run.docs_updated or 0),
        "docs_skipped": int(run.docs_skipped or 0),
        "dedup": 0,
        "filtered": 0,
    }


def _seed_execution(run: AcquisitionRun) -> StrategyExecution:
    rows = int((run.budget_used or {}).get("rows") or 0)
    return StrategyExecution(
        run=run,
        collected=int(run.fetched or 0),
        after_dedup=rows,
        after_filter=rows,
        rounds=int(run.round_count or 0),
    )


def _merge_report(target: TargetReport, source: TargetReport) -> None:
    target.inserted += source.inserted
    target.updated += source.updated
    target.skipped += source.skipped
    target.written += source.written
    target.docs_created += source.docs_created
    target.docs_updated += source.docs_updated
    target.docs_skipped += source.docs_skipped
    target.errors.extend(source.errors)


def _pending_round(db: Session, run_id: int) -> AcquisitionRound | None:
    stmt = (
        select(AcquisitionRound)
        .where(
            AcquisitionRound.run_id == run_id,
            AcquisitionRound.review_state == ReviewState.PENDING.value,
        )
        .order_by(AcquisitionRound.round_no.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _keywords_from_round(round_row: AcquisitionRound) -> list[dict[str, Any]]:
    return [dict(item) for item in list(round_row.top_keywords or []) if not item.get("dropped")]


def _merge_llm_detail(detail: Mapping[str, Any] | None, meta: Mapping[str, Any]) -> dict[str, Any]:
    current = dict((detail or {}).get("llm") or {})
    merged = dict(current)
    for key, value in meta.items():
        if key in ("tokens", "llm_calls"):
            merged[key] = int(merged.get(key) or 0) + int(value or 0)
        else:
            merged[key] = value
    return merged


def _round_status(
    channel_errors: Sequence[Mapping[str, str]],
    report_errors: Sequence[Mapping[str, str]],
    budget_exhausted: bool,
    *,
    total_channels: int,
) -> str:
    if total_channels == 0 or len(channel_errors) >= total_channels:
        return RunStatus.FAILED.value
    if channel_errors or report_errors or budget_exhausted:
        return RunStatus.PARTIAL.value
    return RunStatus.SUCCESS.value


def _aggregate_status(db: Session, run_id: int) -> str:
    """多轮汇总：任一轮 failed / partial → partial；全部 success → success."""
    rounds = list(db.execute(select(AcquisitionRound).where(AcquisitionRound.run_id == run_id)).scalars())
    if any(row.status in (RunStatus.FAILED.value, RunStatus.PARTIAL.value) for row in rounds):
        return RunStatus.PARTIAL.value
    return RunStatus.SUCCESS.value


def _finalize(
    db: Session,
    strategy: AcquisitionStrategy,
    execution: StrategyExecution,
    *,
    started: dt.datetime,
    clock: float,
    user: Any = None,
) -> None:
    """写运行收尾状态与策略 last_status（租约在调用方释放）.

    ``llm.actions`` 含 ``run_report`` 时追加一段模型报告到 ``run.detail.report``：
    只写 detail（不进业务表），失败降级为空串（L5 / L8）。
    """
    run = execution.run
    if run is not None:
        run.status = execution.status
        run.progress = 100 if execution.status != RunStatus.AWAITING_REVIEW.value else run.progress
        run.progress_message = _progress_message(execution)
        if execution.status != RunStatus.AWAITING_REVIEW.value:
            run.finished_at = _as_utc(started)
            run.duration_ms = int((time.perf_counter() - clock) * 1000)
        if execution.status == RunStatus.FAILED.value and not run.error_message:
            run.error_message = "全部渠道均未返回数据或均失败"
        if _llm_enabled(strategy, "run_report") and execution.status != RunStatus.AWAITING_REVIEW.value:
            _attach_run_report(db, strategy, run, user=user)
        db.add(run)
    strategy.last_status = execution.status
    db.add(strategy)
    db.commit()


def _attach_run_report(db: Session, strategy: AcquisitionStrategy, run: AcquisitionRun, *, user: Any) -> None:
    """运行报告：模型可用则写自然语言摘要，不可用则不留键（结构化统计已在 run 上）."""
    from cndb.plugins.acquisition.services import ai as acquisition_ai

    rows = db.execute(
        select(AcquisitionRound).where(AcquisitionRound.run_id == run.id).order_by(AcquisitionRound.round_no)
    ).scalars()
    rounds = [
        {
            "round_no": row.round_no,
            "query": row.query,
            "new_items": row.new_items,
            "stop_reason": row.stop_reason,
            "top_keywords": list(row.top_keywords or []),
        }
        for row in rows
    ]
    text, meta = acquisition_ai.write_run_report(
        db,
        user,
        run=run,
        rounds=rounds,
        workspace_id=strategy.workspace_id,
    )
    detail = dict(run.detail or {})
    if text:
        detail["report"] = {"text": text, "model": meta.get("model", ""), "run_id": meta.get("run_id")}
    if meta.get("degraded"):
        detail["llm_report_degraded"] = meta["degraded"]
    run.detail = detail


def _progress_message(execution: StrategyExecution) -> str:
    if execution.status == RunStatus.AWAITING_REVIEW.value:
        return f"第 {execution.rounds} 轮完成，等待复核扩展词（可直接继续或调整后再继续）"
    return (
        f"采集完成：{execution.rounds} 轮，抓取 {execution.collected} 条 / 去重后 {execution.after_dedup} 条 / "
        f"筛选后 {execution.after_filter} 条 / 写入 {execution.report.written} 行 / "
        f"文档新增 {execution.report.docs_created} 更新 {execution.report.docs_updated}"
    )


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
