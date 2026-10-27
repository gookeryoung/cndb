"""抓取管线 —— Provider 展开请求 → 抓取 → 解析 → 归一，单点失败不拖垮整体.

与领域无关：本模块不出现 symbol / city / stock 等词，标的一律叫 ``entrant``。

失败口径（ADR 0006 I3）：
- 单个请求失败记入 ``failures`` 并继续后续请求；
- 分页遇到空页即停止该组（entrant × 窗口）的后续请求，避免无谓翻页；
- 全部请求失败 → ``status="failed"``；部分失败 → ``partial``；否则 ``success``。

ADR 0034 扩展（大规模任务形态）：

- **并发**（D5）：``request.workers > 1`` 时按 (entrant × 窗口) 分组提交线程池，
  组内分页保持串行（空页停止语义不变）；``rate_limit_ms`` 升级为全局相邻请求
  最小出发间隔（并发下同样成立，``workers=1`` 时与旧的顺序 sleep 等价）。
- **流式落表**（D1）：``on_batch`` 回调下，归一后的行攒满 ``batch_size`` 即回调，
  不再全量攒内存；回调异常终止整轮（已回调批次由调用方保证幂等可续跑）。
- **行过滤 / 常量模板**（D4）：``row_filter`` 数值条件剔除行（如零值快照），
  ``row_defaults`` 的值支持 ``{today}`` / ``{entrant}`` 模板渲染。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, cast

from cndb.plugins.datasource.providers.base import FetchFn, NormalizeLike, RequestPlan, SourceProvider, SyncJobSpec
from cndb.plugins.datasource.providers.registry import get_provider
from cndb.plugins.datasource.providers.template import render_text
from cndb.plugins.tables.services.importing.api_fetch import fetch_json, open_http_client

logger = logging.getLogger(__name__)

# 流式落表的默认批大小（行）：足够摊薄单行开销，又不至于单批过大撑爆事务
# ADR 0039 D4：实测 10,000 行/批比 5,000 行/批吞吐高约 40%，更大批次无进一步收益
DEFAULT_BATCH_SIZE = 10000

# row_filter 支持的数值比较符
_FILTER_OPS: Mapping[str, Callable[[float, float], bool]] = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


@dataclass(slots=True)
class FetchFailure:
    """单次请求失败明细（进 datasource_sync_run.detail）."""

    label: str
    entrant: str | None = None
    page: int | None = None
    error: str = ""


@dataclass(slots=True)
class PipelineOutcome:
    """一次管线运行的结果（尚未落库）.

    流式模式（``on_batch``）下 ``rows`` 恒为空——行已分批交给回调，
    这里只保留计数与失败 / 归一明细。
    """

    rows: list[dict[str, Any]] = field(default_factory=list)
    plans: int = 0
    succeeded: int = 0
    failures: list[FetchFailure] = field(default_factory=list)
    normalize: NormalizeLike | None = None
    # 逐请求响应元信息（模型名 / token 用量等），由 provider 写入 plan.metadata
    metadata: list[dict[str, Any]] = field(default_factory=list)
    # row_filter 剔除的行数（ADR 0034 D4；不过滤时为 0）
    filtered: int = 0
    # 流式模式下已交给回调的行数（与非流式的 len(rows) 口径对应）
    flushed: int = 0
    # 每标的**抓取行数**（归一 / 过滤之前）：单轮翻页的短页判定用（ADR 0053 D3）
    entrant_rows: dict[str, int] = field(default_factory=dict)
    # 实际执行的轮数（单轮翻页回补 >1；其它形态恒为 1，运行记录留痕用）
    passes: int = 0
    # 达到单轮翻页上限而提前退出（ADR 0053 D3）：按 partial 留痕，不静默成功
    truncated: bool = False

    @property
    def failed(self) -> int:
        return len(self.failures)

    @property
    def status(self) -> str:
        """``success`` / ``partial`` / ``failed``."""
        if self.plans and self.succeeded == 0:
            return "failed"
        if self.failures or self.truncated:
            return "partial"
        return "success"


@dataclass(slots=True)
class _GroupResult:
    """一个分组（entrant × 窗口）串行执行完毕后的产物（线程间只传不可变结果）."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    succeeded: int = 0
    failures: list[FetchFailure] = field(default_factory=list)
    metadata: list[dict[str, Any]] = field(default_factory=list)
    # 该组每标的抓取行数（原始响应行数，归一 / 过滤之前）
    entrant_rows: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class _NormalizeAggregate:
    """流式模式下跨批聚合的归一明细（行不落地，只累计 dropped / failures）.

    失败明细只保留前 ``MAX_KEPT_FAILURES`` 条，另记 ``failed_total`` 全量计数
    （ADR 0043 D5）：海量失败源下内存不随行数线性增长，``detail`` 口径不变。
    """

    MAX_KEPT_FAILURES = 100

    rows: list[dict[str, Any]] = field(default_factory=list)
    dropped: int = 0
    failures: list[Any] = field(default_factory=list)
    failed_total: int = 0

    def add_failures(self, failures: Sequence[Any]) -> None:
        """累计一批归一失败：计数全量累加，明细只在额度内保留（超出丢弃不报错）."""
        if not failures:
            return
        self.failed_total += len(failures)
        room = self.MAX_KEPT_FAILURES - len(self.failures)
        if room <= 0:
            return
        self.failures.extend(failures[:room])


class RequestProgress:
    """线程安全的请求级进度计数器（ADR 0037 D4）.

    ``total`` = 本轮展开的计划请求数；``done`` = 已结束的请求数（成功 + 失败，
    空页提前停止后未发出的请求不计）。``entrant`` = 最近完成的标的，供运行记录展示。
    """

    __slots__ = ("_done", "_entrant", "_lock", "_total")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total = 0
        self._done = 0
        self._entrant = ""

    def set_total(self, total: int) -> None:
        """设置本轮计划请求数（展开后调用一次；允许并发线程读取）."""
        with self._lock:
            self._total = max(0, total)

    def add_total(self, extra: int) -> None:
        """累加计划请求数（单轮翻页回补多轮展开时用，ADR 0053 D3）.

        ``run_pipeline`` 每轮调用一次；单轮任务下与 :meth:`set_total` 结果相同。
        """
        with self._lock:
            self._total = max(0, self._total + max(0, extra))

    def tick(self, entrant: str | None) -> None:
        """完成一个请求（成功或失败）后调用."""
        with self._lock:
            self._done += 1
            if entrant:
                self._entrant = entrant[:64]

    def snapshot(self) -> tuple[int, int, str]:
        """返回 ``(total, done, entrant)`` 的一致快照."""
        with self._lock:
            return self._total, self._done, self._entrant


class _RateLimiter:
    """全局请求限速器：任意相邻两个请求的出发间隔 ≥ ``rate_limit_ms``（ADR 0034 D5）.

    锁内预约「下一个允许出发时刻」，锁外等待——并发线程排队出发，
    ``workers=1`` 时退化为顺序等待，与旧的 ``sent > 0 → sleep`` 行为一致。
    """

    __slots__ = ("_gap", "_lock", "_next_at", "_sleep")

    def __init__(self, rate_limit_ms: int, sleep: Callable[[float], None] | None = None) -> None:
        self._gap = rate_limit_ms / 1000.0 if rate_limit_ms > 0 else 0.0
        self._lock = threading.Lock()
        self._next_at = 0.0
        self._sleep = sleep or time.sleep

    def wait(self) -> None:
        """出发前调用；需要等待时睡到预约时刻."""
        if self._gap <= 0.0:
            return
        with self._lock:
            now = time.monotonic()
            delay = self._next_at - now
            self._next_at = max(now, self._next_at) + self._gap
        if delay > 0.0:
            self._sleep(delay)


def run_pipeline(
    job: SyncJobSpec,
    *,
    provider: SourceProvider | None = None,
    fetch: FetchFn | None = None,
    rate_limit_ms: int = 0,
    sleep: Callable[[float], None] | None = None,
    on_batch: Callable[[Sequence[Mapping[str, Any]]], None] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress: RequestProgress | None = None,
) -> PipelineOutcome:
    """执行一次同步抓取（不落库；流式模式下逐批回调 ``on_batch``）.

    Args:
        job: 同步任务声明。
        provider: 显式指定适配器；缺省按 ``job.provider`` 从注册表取。
        fetch: 注入的抓取函数（测试用假源）；缺省走 ``api_fetch.fetch_json``。
            缺省抓取器在单次运行内共享一个 HTTP 客户端（连接复用，ADR 0040 D3）。
        rate_limit_ms: 全局相邻请求的最小出发间隔（毫秒，0 = 不限速）。
        sleep: 注入的等待函数（测试用，缺省 ``time.sleep``）。
        on_batch: 流式回调：归一 + 过滤后的行攒满 ``batch_size`` 即调用（内存不攒全量）；
            回调异常会终止整轮并向外抛出。缺省为全量攒进 ``outcome.rows``（旧行为）。
        batch_size: 流式批大小（行）。
        progress: 请求级进度计数器（ADR 0037 D4）；缺省不统计。
    """
    active = provider or get_provider(job.provider)
    plans = active.build_requests(job)
    outcome = PipelineOutcome(plans=len(plans), passes=1)
    if progress is not None:
        progress.add_total(len(plans))
    groups = _group_plans(plans)
    limiter = _RateLimiter(rate_limit_ms, sleep)
    cancel = threading.Event()
    sink = _BatchSink(active, job, on_batch, batch_size, outcome)

    def absorb(result: _GroupResult) -> None:
        outcome.succeeded += result.succeeded
        outcome.failures.extend(result.failures)
        outcome.metadata.extend(result.metadata)
        for entrant, count in result.entrant_rows.items():
            outcome.entrant_rows[entrant] = outcome.entrant_rows.get(entrant, 0) + count
        sink.add(result.rows)

    def execute(default_fetch: FetchFn) -> None:
        workers = _resolve_workers(job)
        if workers <= 1 or len(groups) <= 1:
            for group in groups:
                if cancel.is_set():
                    break
                absorb(_run_group(group, job, fetch, limiter, cancel, progress, default_fetch))
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(_run_group, group, job, fetch, limiter, cancel, progress, default_fetch)
                    for group in groups
                ]
                try:
                    for future in as_completed(futures):
                        absorb(future.result())
                except BaseException:
                    # on_batch（sink.add 内）失败：停掉未开始的组，等运行中的组自然结束
                    cancel.set()
                    raise

    if fetch is None:
        # 缺省抓取器：整轮运行共用一个客户端（TLS 会话复用），退出即关闭
        with open_http_client() as client:
            execute(lambda config: fetch_json(config, client=client))
    else:
        execute(fetch_json)

    sink.flush()
    return outcome


def _resolve_workers(job: SyncJobSpec) -> int:
    """解析并发数：``request.workers``；LLM 类 provider 一律按 1（避免打爆配额）."""
    declared = max(1, int(getattr(job.request, "workers", 1) or 1))
    if job.provider == "llm_prompt" and declared > 1:
        logger.warning("任务声明 workers=%d，但 llm_prompt 不支持并发，按 1 执行", declared)
        return 1
    return declared


def _group_plans(plans: Sequence[RequestPlan]) -> list[list[RequestPlan]]:
    """按 (entrant, window_start, window_end) 分组，组序与展开顺序一致（页码升序）."""
    grouped: dict[tuple[str | None, str | None, str | None], list[RequestPlan]] = {}
    for plan in plans:
        grouped.setdefault((plan.entrant, plan.window_start, plan.window_end), []).append(plan)
    return list(grouped.values())


def _run_group(
    group: list[RequestPlan],
    job: SyncJobSpec,
    fetch: FetchFn | None,
    limiter: _RateLimiter,
    cancel: threading.Event,
    progress: RequestProgress | None = None,
    default_fetch: FetchFn = fetch_json,
) -> _GroupResult:
    """串行执行一个分组内的全部请求（空页停止；取消标记只在请求间检查）."""
    result = _GroupResult()
    for plan in group:
        if cancel.is_set():
            break
        limiter.wait()
        # ADR 0020：plan 级抓取器优先（LLM 请求走平台客户端）；显式注入的 fetch 最高优先
        plan_fetcher: FetchFn = fetch or plan.fetcher or default_fetch
        try:
            rows = plan_fetcher(plan.config)
        except Exception as exc:  # 单请求失败不中断整体（I3）
            logger.warning("数据源请求失败 [%s]: %s", plan.label, exc)
            result.failures.append(FetchFailure(label=plan.label, entrant=plan.entrant, page=plan.page, error=str(exc)))
            if progress is not None:
                progress.tick(plan.entrant)
            continue
        if progress is not None:
            progress.tick(plan.entrant)
        result.succeeded += 1
        if plan.metadata:
            result.metadata.append({"label": plan.label, **plan.metadata})
        if plan.page is not None and not rows:
            # 空页即停该组（ADR 0006 I3）：后续页码不再请求
            break
        if plan.entrant is not None:
            # 抓取行数按标的累计（归一 / 过滤之前）：单轮翻页的短页判定依据（ADR 0053 D3）
            result.entrant_rows[plan.entrant] = result.entrant_rows.get(plan.entrant, 0) + len(rows)
        result.rows.extend(
            apply_row_defaults(
                fill_entrant(to_records(rows), job.entrant_param, plan.entrant, inplace=True),
                job.row_defaults,
                variables=_row_variables(job, plan),
                inplace=True,
            )
        )
    return result


def _row_variables(job: SyncJobSpec, plan: RequestPlan) -> dict[str, Any]:
    """行级常量渲染变量：会话密钥等额外变量铺底 + today（runner 注入）+ 当前标的."""
    variables: dict[str, Any] = dict(job.extra_variables)
    if plan.entrant is not None:
        variables["entrant"] = plan.entrant
        if job.entrant_param:
            variables[job.entrant_param] = plan.entrant
    return variables


class _BatchSink:
    """批处理器：累积原始行，攒满即「归一 → 过滤 → 回调 / 并入 outcome.rows」.

    只在主线程使用（组任务只返回行，不做归一），无并发问题。
    """

    __slots__ = ("_active", "_aggregate", "_batch_size", "_buffer", "_job", "_on_batch", "_outcome")

    def __init__(
        self,
        active: SourceProvider,
        job: SyncJobSpec,
        on_batch: Callable[[Sequence[Mapping[str, Any]]], None] | None,
        batch_size: int,
        outcome: PipelineOutcome,
    ) -> None:
        self._active = active
        self._job = job
        self._on_batch = on_batch
        self._batch_size = max(1, batch_size) if on_batch is not None else 0
        self._outcome = outcome
        self._buffer: list[dict[str, Any]] = []
        self._aggregate = _NormalizeAggregate()
        outcome.normalize = self._aggregate

    def add(self, rows: Sequence[dict[str, Any]]) -> None:
        """累积一组行；攒满批即落（回调异常向外抛，调用方终止整轮）."""
        if not rows:
            return
        self._buffer.extend(rows)
        if self._batch_size and len(self._buffer) >= self._batch_size:
            self.flush()

    def flush(self) -> None:
        """清空缓冲：按批大小分片「归一 + 过滤 → 回调 / 并入 ``outcome.rows``」.

        分片保证单次回调（单事务批次）不超过 ``batch_size`` 行——单个大响应
        也不会撑爆事务（ADR 0034 D1）；全量模式（无回调）整批一次处理。
        """
        while self._buffer:
            # 注意拷贝：chunk 与 _buffer 不能是同一对象（del 会把 chunk 一并清空）
            chunk = self._buffer[: self._batch_size] if self._batch_size else list(self._buffer)
            del self._buffer[: len(chunk)]
            self._process(chunk)

    def _process(self, chunk: list[dict[str, Any]]) -> None:
        normalized = self._active.normalize(chunk, self._job)
        self._aggregate.dropped += normalized.dropped
        self._aggregate.add_failures(normalized.failures)
        kept, removed = apply_row_filter(normalized.rows, getattr(self._job.request, "row_filter", None), inplace=True)
        self._outcome.filtered += removed
        if self._on_batch is not None:
            if kept:
                self._on_batch(kept)
                self._outcome.flushed += len(kept)
        else:
            self._outcome.rows.extend(kept)


def to_records(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """确保每行是独立 dict（避免 provider 复用同一对象导致后续改写互相污染）."""
    return [dict(row) for row in rows]


def fill_entrant(
    rows: Sequence[Mapping[str, Any]],
    entrant_param: str | None,
    entrant: str | None,
    *,
    inplace: bool = False,
) -> list[dict[str, Any]]:
    """行内缺标的列时用请求维度补齐（响应体不带 symbol 的源，如新浪日线）.

    ``setdefault`` 语义：响应自带标的字段的一律保留，不被请求参数覆盖。
    ``inplace=True`` 时就地改写传入行（调用方须已拥有行对象，见 ADR 0043 D2），
    返回的仍是新列表；默认仍返回新 dict 列表，公共语义不变。
    """
    if not entrant_param or entrant is None:
        return cast("list[dict[str, Any]]", list(rows)) if inplace else [dict(row) for row in rows]
    filled: list[dict[str, Any]] = []
    if inplace:
        for row in rows:
            row.setdefault(entrant_param, entrant)  # type: ignore[attr-defined]
            filled.append(row)  # type: ignore[arg-type]
        return filled
    for row in rows:
        record = dict(row)
        record.setdefault(entrant_param, entrant)
        filled.append(record)
    return filled


def apply_row_defaults(
    rows: Sequence[Mapping[str, Any]],
    defaults: Mapping[str, Any],
    *,
    variables: Mapping[str, Any] | None = None,
    inplace: bool = False,
) -> list[dict[str, Any]]:
    """行级常量列（``setdefault`` 语义，响应自带同名值优先）.

    用于响应不回显来源维度的场景：多源写同一张表时补「来源 / 复权方式」等列。
    ``variables`` 给出时常量值先经模板渲染（``{today}`` / ``{entrant}`` 等，
    ADR 0034 D4——快照写当日行的日期列用）；非字符串值原样使用。
    ``inplace=True`` 就地 ``setdefault``（ADR 0043 D2），默认仍返回新 dict 列表。
    """
    if not defaults:
        return cast("list[dict[str, Any]]", list(rows)) if inplace else [dict(row) for row in rows]
    rendered = {
        key: (render_text(value, dict(variables)) if variables and isinstance(value, str) else value)
        for key, value in defaults.items()
    }
    filled: list[dict[str, Any]] = []
    if inplace:
        for row in rows:
            for key, value in rendered.items():
                row.setdefault(key, value)  # type: ignore[attr-defined]
            filled.append(row)  # type: ignore[arg-type]
        return filled
    for row in rows:
        record = dict(row)
        for key, value in rendered.items():
            record.setdefault(key, value)
        filled.append(record)
    return filled


def apply_row_filter(
    rows: Sequence[Mapping[str, Any]],
    row_filter: Mapping[str, Any] | None,
    *,
    inplace: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """按数值条件过滤行（ADR 0034 D4）：返回 ``(保留行, 剔除数)``.

    字段缺失 / 非数值（不可转 float）的行一律剔除（如停牌标的零值快照行）；
    ``row_filter`` 为 ``None`` 时原样返回（零剔除）。
    ``inplace=True`` 时保留行沿用入参对象（只挑引用、不复制）；默认仍复制。
    """
    copy = (lambda row: row) if inplace else dict  # type: ignore[arg-type]
    if not row_filter:
        return [copy(row) for row in rows], 0
    field = str(row_filter.get("field") or "")
    op = _FILTER_OPS.get(str(row_filter.get("op") or ""))
    threshold = row_filter.get("value")
    if not field or op is None or threshold is None:
        return [copy(row) for row in rows], 0
    kept: list[dict[str, Any]] = []
    removed = 0
    for row in rows:
        value = row.get(field)
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            removed += 1
            continue
        if op(number, float(threshold)):
            kept.append(copy(row))  # type: ignore[arg-type]
        else:
            removed += 1
    return kept, removed


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "FetchFailure",
    "PipelineOutcome",
    "RequestProgress",
    "apply_row_defaults",
    "apply_row_filter",
    "fill_entrant",
    "run_pipeline",
    "to_records",
]
