"""工作区统计缓存 —— 数据表目录页 / 工作区头部的行数与计数（ADR 0046 D5）.

工作区详情每次进入都要取 table_count / member_count / view_count / total_rows。
``total_rows`` 需要对每张动态物理表 COUNT（4M 行的表约 0.35s），而这个数字在
页面切换之间几乎不变 —— 短 TTL 缓存 + 写路径事件失效即可（单机进程内缓存）。

缓存只存**与用户无关**的聚合（角色 / 权限位仍按请求实时计算），因此键里不带 user_id。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, DataView
from cndb.plugins.workspaces.models import WorkspaceMember

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: 工作区统计缓存 TTL（秒）：行数变化由 record./table./datasource. 事件即时失效，TTL 兜底
WS_STATS_TTL_SECONDS = 30.0

#: 缓存键前缀（事件 / 写路径按 ``cache_key(prefix, workspace_id)`` 前缀清理）
WS_STATS_CACHE_PREFIX = "workspace-stats"


def workspace_stats_key(workspace_id: int) -> str:
    from cndb.core.cache import cache_key

    return cache_key(WS_STATS_CACHE_PREFIX, workspace_id)


def compute_workspace_stats(db: Session, workspace_id: int) -> dict[str, int]:
    """计算工作区统计（table_count / member_count / view_count / total_rows）."""
    from cndb.plugins.tables.services.core.record_counts import batch_record_counts

    table_count = (
        db.query(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed_at.is_(None),
        )
        .count()
    )
    member_count = (
        db.query(WorkspaceMember)
        .join(User, User.id == WorkspaceMember.user_id)
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .count()
    )
    view_count = (
        db.query(DataView)
        .join(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed_at.is_(None),
        )
        .count()
    )
    tables = (
        db.query(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed_at.is_(None),
        )
        .all()
    )
    counts = batch_record_counts(db, tables)
    total_rows = 0
    if not counts and tables:
        # UNION ALL 整体失败（如存在只有元数据没有物理表的幻影表）→
        # 回退逐表 COUNT，异常表 suppress 跳过，与旧行为一致
        from sqlalchemy import MetaData, Table, func, select

        metadata = MetaData()
        for tbl in tables:
            try:
                sa_table = Table(tbl.db_table_name, metadata, autoload_with=db.bind)
                total_rows += int(db.execute(select(func.count(sa_table.c.id))).scalar() or 0)
            except Exception:
                logger.warning("工作区统计逐表 COUNT 失败，跳过 table=%s", tbl.db_table_name, exc_info=True)
    for tbl in tables:
        cnt = counts.get(tbl.id)
        if cnt is not None:
            total_rows += int(cnt)
    return {
        "table_count": int(table_count),
        "member_count": int(member_count),
        "view_count": int(view_count),
        "total_rows": total_rows,
    }


def get_workspace_stats(db: Session, workspace_id: int) -> dict[str, int]:
    """读缓存的工作区统计（未命中时计算并写缓存，TTL 见 WS_STATS_TTL_SECONDS）."""
    from cndb.core.cache import list_cache

    key = workspace_stats_key(workspace_id)
    cached = list_cache.get(key)
    if cached is not None:
        return cached
    stats = compute_workspace_stats(db, workspace_id)
    list_cache.set(key, stats, WS_STATS_TTL_SECONDS)
    return stats


def invalidate_workspace_stats(workspace_id: int) -> int:
    """失效某工作区的统计缓存（建表 / 删表 / 行变更 / 成员变更后调用，best-effort）."""
    try:
        from cndb.core.cache import list_cache

        return list_cache.clear(workspace_stats_key(workspace_id))
    except Exception:  # pragma: no cover - 缓存失效失败不影响写入
        logger.debug("工作区统计缓存失效失败 workspace=%s", workspace_id, exc_info=True)
        return 0


__all__ = [
    "WS_STATS_CACHE_PREFIX",
    "WS_STATS_TTL_SECONDS",
    "compute_workspace_stats",
    "get_workspace_stats",
    "invalidate_workspace_stats",
    "workspace_stats_key",
]
