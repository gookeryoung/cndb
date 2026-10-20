"""落表 —— 把归一后的行按 ``match_keys`` 幂等写入目标数据表.

复用 tables 的 ``Importer``（analyze → execute），因此校验、未知列策略、
行级写范围与审计口径与既有导入链路完全一致；本模块只负责把结果压成
``datasource_sync_run`` 需要的计数字段。

幂等由应用层「先查后写」保证（ADR 0006 已确认不引入复合唯一索引）：
同一 ``match_keys`` 组合重复运行只会更新既有行，不会新增重复行。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WriteOutcome:
    """一次落库的计数结果（对应 datasource_sync_run 的 fetched / inserted / updated / skipped）."""

    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed_rows: int = 0

    @property
    def changed(self) -> int:
        return self.inserted + self.updated


def upsert_rows(
    engine: Any,
    db: Any,
    table: Any,
    rows: Sequence[dict[str, Any]],
    *,
    match_keys: Sequence[str] = (),
    user: Any = None,
) -> WriteOutcome:
    """按 ``match_keys`` 幂等落表.

    Args:
        engine: SQLAlchemy Engine（动态表写入用）。
        db: SQLAlchemy Session（字段元数据与 link 关联表用）。
        table: 目标 ``DataTable``。
        rows: 已归一的行（列名 = 目标字段名）。
        match_keys: 幂等键（目标字段名）；为空退化为纯追加。
        user: 触发同步的用户，用于行级写范围判定；定时任务传 ``None``。
    """
    if not rows:
        return WriteOutcome()

    from cndb.plugins.tables.services.importing.importer import Importer

    keys = [key for key in match_keys if key]
    importer = Importer(engine, db, table, user=user)
    # content 占位为空串：行已解析好，走 rows 入口（与 import_api 的 JSON 数组导入同口径）
    analysis = importer.analyze("", rows=list(rows), match_keys=keys or None)
    result = importer.execute(analysis=analysis, match_keys=keys or None)
    report = result.report or {}

    outcome = WriteOutcome(
        fetched=len(rows),
        inserted=int(report.get("actually_created", 0) or 0),
        updated=int(report.get("actually_updated", 0) or 0),
        skipped=int(report.get("error_count", 0) or 0),
        failed_rows=len(result.failed_results),
    )
    logger.info(
        "数据源落表完成: fetched=%d inserted=%d updated=%d skipped=%d",
        outcome.fetched,
        outcome.inserted,
        outcome.updated,
        outcome.skipped,
    )
    return outcome


__all__ = ["WriteOutcome", "upsert_rows"]
