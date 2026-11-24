"""大表 DDL 影响预估（需求 0150 / ADR 0150）.

问题：字段改类型 / 改必填 / 加索引在百万行表上可能是几十秒到几分钟的整列重写，
界面上没有任何提示，用户点「保存」后只能干等（失败还靠 ADR 0038 的原子回退收拾）。

做法：**抽样实测 + 动作系数** 给出"量级正确"的预估（不假装精确到秒）：

1. 取该表行数（`COUNT`）；
2. 抽 ``sample`` 行（默认 200，上限 1000）计时：读一行 + 按目标字段类型做一次值转换；
3. 估算 = ``sample_ms / sampled_rows × row_count × 动作系数``：

   - ``change_type``：3.0（读 + 转换 + 整列重写 + 索引重建）
   - ``add_field``：1.2（扫一遍判空 / 补默认值）
   - ``add_index``：2.0（扫描 + 建索引）

估算只用于**提示与阈值拦截**，不作为承诺；抽样样本量随表大小收敛，且返回
``sampled_rows`` / ``sample_ms`` 让调用方判断可信度。默认阈值 0（关闭拦截）。
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core.ddl import get_reflected_table

logger = logging.getLogger(__name__)

#: 支持预估的动作
ACTIONS = ("change_type", "add_field", "add_index")

#: 动作系数：把"每行读+转换"成本放大成该动作的整表成本
ACTION_FACTORS = {
    "change_type": 3.0,
    "add_field": 1.2,
    "add_index": 2.0,
}

#: 抽样行数默认值 / 上限
DEFAULT_SAMPLE = 200
MAX_SAMPLE = 1000


def _row_count(engine: Any, table: DataTable) -> int:
    from cndb.plugins.tables.services.core.records import count_rows

    total = count_rows(engine, table)
    if total is None:  # pragma: no cover - 无 lookup 字段时不会是 None
        try:
            sa_table = get_reflected_table(engine, table.db_table_name)
            with engine.connect() as conn:
                return int(conn.execute(select(func.count(sa_table.c.id))).scalar() or 0)
        except RuntimeError:
            return 0
    return int(total)


def _null_count(engine: Any, table: DataTable, field: DataField) -> int | None:
    """该字段的空值行数（改必填 / 唯一约束时的"待补值"行数）；无物理列返回 None."""
    ft = default_registry.get(field.field_type)
    if ft is None or not ft.has_physical_column:
        return None
    try:
        sa_table = get_reflected_table(engine, table.db_table_name)
    except RuntimeError:  # pragma: no cover
        return None
    column = sa_table.c.get(field.db_column_name)
    if column is None:
        return None
    stmt = select(func.count(sa_table.c.id)).where(column.is_(None))
    if hasattr(sa_table.c, "_trashed"):
        stmt = stmt.where(sa_table.c._trashed.is_(False))
    with engine.connect() as conn:
        return int(conn.execute(stmt).scalar() or 0)


def estimate_ddl_impact(
    db: Session,
    table: DataTable,
    *,
    action: str,
    field: DataField | None = None,
    target_type: str | None = None,
    sample: int = DEFAULT_SAMPLE,
) -> dict[str, Any]:
    """预估一次 DDL 动作的影响（只读；不写库、不改元数据）.

    Args:
        action: ``change_type`` / ``add_field`` / ``add_index``。
        field: 必填动作涉及的目标字段（``change_type`` 时必传）。
        target_type: ``change_type`` / ``add_field`` 的目标字段类型（必传）。
        sample: 抽样行数（上限 ``MAX_SAMPLE``）。
    """
    if action not in ACTIONS:
        raise ValueError(f"不支持的动作: {action}（可选 {' / '.join(ACTIONS)}）")
    if action == "change_type" and field is None:
        raise ValueError("change_type 需要指定字段")
    if action in ("change_type", "add_field"):
        if not target_type:
            raise ValueError(f"{action} 需要指定目标字段类型")
        if default_registry.get(target_type) is None:
            raise ValueError(f"未知字段类型: {target_type}")

    engine: Any = db.get_bind()
    rows = _row_count(engine, table)
    sample_size = max(1, min(sample, MAX_SAMPLE))

    # 抽样实测：读一行 + 按目标类型做一次转换
    sample_ms = 0.0
    sampled = 0
    if rows:
        try:
            sa_table = get_reflected_table(engine, table.db_table_name)
            column = None
            if field is not None and field.field_type:
                column = sa_table.c.get(field.db_column_name)
            stmt = select(sa_table.c.id, column) if column is not None else select(sa_table.c.id)
            if hasattr(sa_table.c, "_trashed"):
                stmt = stmt.where(sa_table.c._trashed.is_(False))
            stmt = stmt.limit(sample_size)
            target_ft = default_registry.get(target_type) if target_type else None
            started = time.perf_counter()
            with engine.connect() as conn:
                for raw in conn.execute(stmt).all():
                    sampled += 1
                    if target_ft is not None and column is not None:
                        value = raw[1]
                        # 转换失败在真 DDL 里会中断 / 走默认值，这里只计时不判错
                        with contextlib.suppress(ValueError, TypeError):
                            target_ft.validate_value(value, {})
            sample_ms = (time.perf_counter() - started) * 1000
        except RuntimeError:  # pragma: no cover - 物理表缺失
            sampled = 0
            sample_ms = 0.0

    per_row_ms = (sample_ms / sampled) if sampled else 0.0
    factor = ACTION_FACTORS[action]
    estimated_ms = round(per_row_ms * rows * factor)

    from cndb.core.config import settings

    threshold = int(getattr(settings, "DDL_IMPACT_FORCE_THRESHOLD_ROWS", 0))
    return {
        "action": action,
        "table_id": int(table.id),
        "table_name": table.name,
        "field": field.name if field is not None else None,
        "target_type": target_type,
        "row_count": rows,
        "field_null_count": _null_count(engine, table, field) if field is not None else None,
        "sampled_rows": sampled,
        "sample_size": sample_size,
        "sample_ms": round(sample_ms, 2),
        "factor": factor,
        "estimated_ms": estimated_ms,
        "threshold_rows": threshold,
        "force_required": bool(threshold > 0 and rows > threshold),
    }


__all__ = ["ACTIONS", "ACTION_FACTORS", "DEFAULT_SAMPLE", "MAX_SAMPLE", "estimate_ddl_impact"]
