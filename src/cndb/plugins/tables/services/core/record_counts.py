"""动态物理表行数统计 —— 多表一次 UNION ALL（ADR 0046 D5）.

工作区详情与数据表目录都需要多张表的行数：逐表 ``COUNT(*)`` 在大工作区会退化成
N 次全表扫描（4M 行表约 0.35s/次）。这里合并为一条 UNION ALL 语句一次取回。

超过 100 张表时跳过（超长 SQL 收益递减），调用方回退到逐表 / 缓存路径。
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.orm import Session

    from cndb.plugins.tables.models import DataTable

logger = logging.getLogger(__name__)

#: UNION ALL 统计的表数上限（超出直接跳过，由调用方逐表或缓存兜底）
BATCH_COUNT_MAX_TABLES = 100

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def batch_record_counts(db: Session, tables: Iterable[DataTable]) -> dict[int, int | None]:
    """一次 UNION ALL 取回多张动态表的行数.

    Args:
        db: 元数据库会话（与动态表同库）.
        tables: 目标 DataTable 列表（逻辑删除的调用方自行过滤）.

    Returns:
        {table_id: 行数}；表名非法 / 超过上限 / SQL 失败时返回空 dict（调用方回退）.
    """
    targets = [t for t in tables if _IDENTIFIER_RE.fullmatch(t.db_table_name or "")]
    if not targets or len(targets) > BATCH_COUNT_MAX_TABLES:
        return {}
    parts: list[str] = []
    params: dict[str, int] = {}
    for idx, tbl in enumerate(targets):
        parts.append(f"SELECT :t{idx} AS tid, COUNT(*) AS cnt FROM {tbl.db_table_name}")  # nosec B608 - 表名白名单校验
        params[f"t{idx}"] = tbl.id
    try:
        rows = db.execute(text(" UNION ALL ".join(parts)), params).all()
    except Exception:
        logger.warning("批量行数统计失败，回退逐表 COUNT", exc_info=True)
        return {}
    return {int(tid): int(cnt) for tid, cnt in rows}


__all__ = ["BATCH_COUNT_MAX_TABLES", "batch_record_counts"]
