"""行回收站保留期清理（ADR 0139 C5 / D4 / D5）.

口径：
- 只处理**已软删**且 `_trashed_at` 早于保留期截止时间的行；`_trashed_at IS NULL`
  的历史已删行（本能力上线前产生）**不自动清理**，只在 `dry_run` 报告里列出，
  因为「时间未知就推定最老」意味着上线即批量物理删除存量数据（不可逆）。
- `days <= 0` 表示关闭（`TRASH_RETENTION_DAYS=0`），直接返回 0。
- 按表分批（默认 500 行/批）物理删除，复用 `records.purge_rows`：清 link 关系、
  重算消费方 lookup 冗余列、逐行写审计，与回收站「彻底删除」完全同一口径。
- 幂等可重入：中途失败不影响已清理的表，重跑继续。

入口：`cndb tables purge-trash [--days N] [--dry-run] [--workspace W]`（运维 cron）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core.ddl import get_reflected_table

logger = logging.getLogger(__name__)

#: 单批清理行数上限：太大单事务过长，太小徒增往返
PURGE_BATCH_SIZE = 500


def _retention_days(days: int | None) -> int:
    """解析生效保留天数：显式参数优先，缺省取配置 ``TRASH_RETENTION_DAYS``."""
    if days is not None:
        return int(days)
    from cndb.core.config import settings

    return int(getattr(settings, "TRASH_RETENTION_DAYS", 30))


def _table_workspace_name(db: Session, table: DataTable) -> str:
    from cndb.plugins.workspaces.models import Workspace

    ws = db.get(Workspace, table.workspace_id)
    return str(ws.name) if ws is not None else ""


def purge_expired_rows(
    db: Session,
    *,
    days: int | None = None,
    dry_run: bool = False,
    workspace_id: int | None = None,
    table_id: int | None = None,
    batch_size: int = PURGE_BATCH_SIZE,
    user: Any = None,
) -> dict[str, Any]:
    """按保留期清理已软删行，返回可序列化报告.

    Args:
        days: 保留天数；`None` 取配置，`<= 0` 关闭（不清理任何行）。
        dry_run: 只报告不删除。
        workspace_id / table_id: 可选收窄范围（运维排障用）。
        batch_size: 单批行数上限。
        user: 操作人（写审计用；CLI 场景可为 None）。

    Returns:
        ``{"dry_run", "days", "cutoff", "tables", "purged", "unknown_time"}``，
        其中 ``tables`` 为逐表明细，``unknown_time`` 为 `_trashed_at` 为空、
        **不会**被自动清理的行数（需人工确认）。
    """
    effective_days = _retention_days(days)
    report: dict[str, Any] = {
        "dry_run": dry_run,
        "days": effective_days,
        "cutoff": None,
        "tables": [],
        "purged": 0,
        "unknown_time": 0,
    }
    if effective_days <= 0:
        return report

    engine: Any = db.get_bind()
    cutoff = datetime.now(UTC) - timedelta(days=effective_days)
    report["cutoff"] = cutoff.isoformat(sep=" ", timespec="seconds")

    query = db.query(DataTable).filter(DataTable.trashed_at.is_(None))
    if workspace_id is not None:
        query = query.filter(DataTable.workspace_id == int(workspace_id))
    if table_id is not None:
        query = query.filter(DataTable.id == int(table_id))
    tables = query.order_by(DataTable.id).all()

    for table in tables:
        try:
            sa_table = get_reflected_table(engine, table.db_table_name)
        except RuntimeError:  # pragma: no cover - 物理表缺失（历史残留）
            logger.warning("回收站清理跳过缺失物理表 %s", table.db_table_name)
            continue
        if not hasattr(sa_table.c, "_trashed_at"):
            continue

        def _ids(where: list[Any], limit: int | None = None, _sa: Any = sa_table) -> list[int]:
            stmt = select(_sa.c.id).where(*where).order_by(_sa.c.id)
            if limit is not None:
                stmt = stmt.limit(limit)
            with engine.connect() as conn:
                return [int(r[0]) for r in conn.execute(stmt).all()]

        expired_where = [
            sa_table.c._trashed.is_(True),
            sa_table.c._trashed_at.is_not(None),
            sa_table.c._trashed_at < cutoff,
        ]
        unknown_where = [sa_table.c._trashed.is_(True), sa_table.c._trashed_at.is_(None)]

        expired_ids = _ids(expired_where)
        with engine.connect() as conn:
            unknown_count = int(conn.execute(select(func.count(sa_table.c.id)).where(*unknown_where)).scalar() or 0)
        report["unknown_time"] += unknown_count
        if not expired_ids and not unknown_count:
            continue

        entry: dict[str, Any] = {
            "table_id": int(table.id),
            "table_name": str(table.name),
            "workspace_id": int(table.workspace_id),
            "workspace_name": _table_workspace_name(db, table),
            "expired": len(expired_ids),
            "unknown_time": unknown_count,
            "purged": 0,
        }
        if not dry_run:
            for start in range(0, len(expired_ids), max(int(batch_size), 1)):
                batch = expired_ids[start : start + max(int(batch_size), 1)]
                entry["purged"] += rec.purge_rows(engine, table, batch, db=db, user=user)
            report["purged"] += entry["purged"]
            _bump_storage_snapshot(int(table.workspace_id))
        report["tables"].append(entry)

    return report


def _bump_storage_snapshot(workspace_id: int) -> None:
    """清理后让该工作区的存储用量快照尽快重算（ADR 0024 的脏集合入口）."""
    try:
        from cndb.plugins.workspaces.services.storage_snapshot import mark_dirty

        mark_dirty(workspace_id)
    except Exception:  # pragma: no cover - 快照模块不可用时不影响清理
        logger.debug("标记存储快照脏集合失败", exc_info=True)


__all__ = ["PURGE_BATCH_SIZE", "purge_expired_rows"]
