"""抓取管线 —— Provider 展开请求 → 抓取 → 解析 → 归一，单点失败不拖垮整体.

与领域无关：本模块不出现 symbol / city / stock 等词，标的一律叫 ``entrant``。

失败口径（ADR 0006 I3）：
- 单个请求失败记入 ``failures`` 并继续后续请求；
- 分页遇到空页即停止该组（entrant × 窗口）的后续请求，避免无谓翻页；
- 全部请求失败 → ``status="failed"``；部分失败 → ``partial``；否则 ``success``。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from cndb.plugins.datasource.providers.base import FetchFn, NormalizeLike, SourceProvider, SyncJobSpec
from cndb.plugins.datasource.providers.registry import get_provider
from cndb.plugins.tables.services.importing.api_fetch import fetch_json

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FetchFailure:
    """单次请求失败明细（进 datasource_sync_run.detail）."""

    label: str
    entrant: str | None = None
    page: int | None = None
    error: str = ""


@dataclass(slots=True)
class PipelineOutcome:
    """一次管线运行的结果（尚未落库）."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    plans: int = 0
    succeeded: int = 0
    failures: list[FetchFailure] = field(default_factory=list)
    normalize: NormalizeLike | None = None

    @property
    def failed(self) -> int:
        return len(self.failures)

    @property
    def status(self) -> str:
        """``success`` / ``partial`` / ``failed``."""
        if self.plans and self.succeeded == 0:
            return "failed"
        if self.failures:
            return "partial"
        return "success"


def run_pipeline(
    job: SyncJobSpec,
    *,
    provider: SourceProvider | None = None,
    fetch: FetchFn | None = None,
) -> PipelineOutcome:
    """执行一次同步抓取（不落库）.

    Args:
        job: 同步任务声明。
        provider: 显式指定适配器；缺省按 ``job.provider`` 从注册表取。
        fetch: 注入的抓取函数（测试用假源）；缺省走 ``api_fetch.fetch_json``。
    """
    active = provider or get_provider(job.provider)
    fetcher: FetchFn = fetch or fetch_json
    plans = active.build_requests(job)

    outcome = PipelineOutcome(plans=len(plans))
    raw_rows: list[dict[str, Any]] = []
    stop_pages: dict[tuple[str | None, str | None, str | None], int] = {}

    for plan in plans:
        group = (plan.entrant, plan.window_start, plan.window_end)
        stopped_at = stop_pages.get(group)
        if stopped_at is not None and plan.page is not None and plan.page > stopped_at:
            continue
        try:
            rows = fetcher(plan.config)
        except Exception as exc:  # 单请求失败不中断整体（I3）
            logger.warning("数据源请求失败 [%s]: %s", plan.label, exc)
            outcome.failures.append(
                FetchFailure(label=plan.label, entrant=plan.entrant, page=plan.page, error=str(exc))
            )
            continue
        outcome.succeeded += 1
        if plan.page is not None and not rows:
            stop_pages[group] = plan.page
        raw_rows.extend(to_records(rows))

    outcome.normalize = active.normalize(raw_rows, job)
    outcome.rows = list(outcome.normalize.rows)
    return outcome


def to_records(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """确保每行是独立 dict（避免 provider 复用同一对象导致后续改写互相污染）."""
    return [dict(row) for row in rows]


__all__ = ["FetchFailure", "PipelineOutcome", "run_pipeline", "to_records"]
