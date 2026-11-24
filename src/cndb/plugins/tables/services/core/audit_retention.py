"""审计与事件流保留期清理（需求 0143 / 路线图 0141 P0-2）.

`tables_auditlog` 每次行写都追加一条（含行快照 `detail`），`core_event` 各域都在写，
两张表都没有上限 —— 时间一长库会缓慢膨胀，且行历史（ADR 0139 P1 之后还会加 revision
表）读起来越来越慢。本模块提供**按时间**的保留期清理：

- `AUDIT_RETENTION_DAYS`（默认 180，`0` 关闭）为唯一阈值，两张表同口径；
- 默认 `dry_run=True`，只报告不删除；`--apply` 才真正删；
- 按 `created_at < cutoff` 分批删（默认 1000 行/批），幂等可重入；
- 流水不参与工作区备份（ADR 0075），因此清理不影响备份往返；清理后旧记录不可恢复，
  所以只按时间不按条数，且默认值保守（180 天）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: 单批删除行数上限
AUDIT_PURGE_BATCH_SIZE = 1000


def _retention_days(days: int | None) -> int:
    """解析生效保留天数：显式参数优先，缺省取配置."""
    if days is not None:
        return int(days)
    from cndb.core.config import settings

    return int(getattr(settings, "AUDIT_RETENTION_DAYS", 180))


def _purge_table(
    db: Session,
    model: Any,
    cutoff: datetime,
    *,
    batch_size: int,
    dry_run: bool,
) -> int:
    """按 cutoff 分批删除单表过期行，返回删除（dry-run 时为"预计删除"）行数."""
    if dry_run:
        # dry-run 用一次 COUNT 给出准确总量，不逐批取 id（大表上白扫一遍）
        with db.bind.connect() as conn:  # type: ignore[union-attr]
            return int(
                conn.execute(select(func.count()).select_from(model).where(model.created_at < cutoff)).scalar() or 0
            )

    total = 0
    while True:
        with db.bind.connect() as conn:  # type: ignore[union-attr]
            ids = [
                int(r[0])
                for r in conn.execute(
                    select(model.id).where(model.created_at < cutoff).order_by(model.id).limit(batch_size)
                ).all()
            ]
        if not ids:
            break
        total += len(ids)
        db.query(model).filter(model.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
    return total


def purge_old_audit(
    db: Session,
    *,
    days: int | None = None,
    dry_run: bool = True,
    batch_size: int = AUDIT_PURGE_BATCH_SIZE,
) -> dict[str, Any]:
    """按保留期清理审计日志与统一事件流，返回可序列化报告.

    Args:
        days: 保留天数；`None` 取配置，`<= 0` 关闭（不清理任何行）。
        dry_run: 只报告不删除（默认）。
        batch_size: 单批行数上限。
    """
    from cndb.core.events import CoreEvent
    from cndb.plugins.tables.models import AuditLog

    effective_days = _retention_days(days)
    report: dict[str, Any] = {
        "dry_run": dry_run,
        "days": effective_days,
        "cutoff": None,
        "audit_deleted": 0,
        "events_deleted": 0,
        "tables": [],
    }
    if effective_days <= 0:
        return report

    cutoff = datetime.now(UTC) - timedelta(days=effective_days)
    report["cutoff"] = cutoff.isoformat(sep=" ", timespec="seconds")

    # 先统计逐表明细（审计按表分组，便于运维定位大户）
    with db.bind.connect() as conn:  # type: ignore[union-attr]
        per_table = conn.execute(
            select(AuditLog.table_id, func.count(AuditLog.id))
            .where(AuditLog.created_at < cutoff)
            .group_by(AuditLog.table_id)
        ).all()
    report["tables"] = [{"table_id": int(table_id), "audit_rows": int(count)} for table_id, count in per_table]

    audit_deleted = _purge_table(db, AuditLog, cutoff, batch_size=batch_size, dry_run=dry_run)
    events_deleted = _purge_table(db, CoreEvent, cutoff, batch_size=batch_size, dry_run=dry_run)
    report["audit_deleted"] = audit_deleted
    report["events_deleted"] = events_deleted

    if not dry_run and (audit_deleted or events_deleted):
        logger.info(
            "审计保留期清理完成：审计 %d 行、事件 %d 行（保留 %d 天）",
            audit_deleted,
            events_deleted,
            effective_days,
        )
    return report


__all__ = ["AUDIT_PURGE_BATCH_SIZE", "purge_old_audit"]
