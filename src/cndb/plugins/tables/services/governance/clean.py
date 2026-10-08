"""已存表清洗 —— 复用导入侧清洗动作，in-place 分批更新.

两遍扫描：
1. 统计遍：对需要统计口径的列（fill_null 的 mean/median、drop_outliers 的 IQR）
   分批收集数值，实时计算阈值；
2. 变换遍：按 id 分批 SELECT，经 cleaning_core 纯函数变换后仅 UPDATE 值变化的行。

preview=True 时只统计与抽样（前 3 条 before/after），不写库；
preview=False 时写回并写一条 action=clean 审计（含动作配置快照）。
预览与执行走同一变换路径，保证受影响统计一致（AC-3）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select

from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.cleaning_core import (
    apply_coerce,
    apply_drop_outliers,
    apply_fill_null,
    apply_trim,
)
from cndb.plugins.tables.services.core.audit import log_action
from cndb.plugins.tables.services.core.ddl import get_reflected_table
from cndb.plugins.tables.services.core.links import is_link_field
from cndb.plugins.tables.services.governance.tasks import GovernanceTaskError

logger = logging.getLogger(__name__)

# 支持的清洗动作（复用导入侧，不新增）
SUPPORTED_ACTIONS = ("trim_whitespace", "fill_null", "coerce_type", "drop_outliers")

AUDIT_ACTION_CLEAN = "clean"

# 分批扫描批大小
BATCH_SIZE = 1000

# 预览样例条数
SAMPLE_LIMIT = 3


def execute_clean_task(db_session: Any, task: Any) -> None:
    """执行清洗任务（任务已处于 running 状态），写报告与进度."""
    table = db_session.get(DataTable, task.table_id)
    if table is None:  # pragma: no cover - tasks.execute 已校验
        raise RuntimeError(f"数据表 {task.table_id} 不存在")
    config = task.config or {}
    actions = config.get("actions") or []
    if not actions:
        raise GovernanceTaskError("清洗配置缺少 actions")
    preview = bool(config.get("preview", True))

    engine = db_session.get_bind()
    involved_fields = _validate_actions(table, actions)

    task.progress = 10
    db_session.commit()

    # 统计遍：按动作需求实时计算 mean / median / IQR
    profiles = _build_profiles(engine, table, involved_fields, actions)

    # 变换遍：分批扫描 → 变换 → 收集变化
    sa_table = get_reflected_table(engine, table.db_table_name, missing_message=f"物理表 {table.db_table_name} 不存在")
    select_cols = [sa_table.c.id, *[sa_table.c[f.db_column_name] for f in involved_fields]]
    name_to_field = {f.name: f for f in involved_fields}

    affected: dict[tuple[str, str, str | None], int] = {}
    samples: list[dict[str, Any]] = []
    updated_rows = 0
    last_id = 0
    batches = 0
    while True:
        query = (
            select(*select_cols)
            .where(sa_table.c.id > last_id, sa_table.c._trashed.is_(False))
            .order_by(sa_table.c.id)
            .limit(BATCH_SIZE)
        )
        with engine.connect() as conn:
            rows = conn.execute(query).all()
        if not rows:
            break
        batches += 1
        task.total_groups = batches
        db_session.commit()

        # 字段名键控的行副本（cleaning_core 以字段名为键）
        originals = []
        cleaned = []
        for r in rows:
            last_id = int(r[0])
            row = {"id": last_id}
            for f in involved_fields:
                row[f.name] = r._mapping[f.db_column_name]
            originals.append(dict(row))
            cleaned.append(row)

        for action in actions:
            act = action["action"]
            column = action["column"]
            strategy = action.get("strategy")
            profile = profiles.get((act, column), {})
            if act == "trim_whitespace":
                cleaned, n = apply_trim(cleaned, column)
            elif act == "fill_null":
                cleaned, n = apply_fill_null(cleaned, column, strategy, profile)
            elif act == "coerce_type":
                cleaned, n = apply_coerce(cleaned, column, strategy, action.get("on_fail", "nullify"))
            elif act == "drop_outliers":
                cleaned, n = apply_drop_outliers(cleaned, column, profile)
            else:  # pragma: no cover - _validate_actions 已拦截
                continue
            key = (act, column, strategy)
            affected[key] = affected.get(key, 0) + n

        # 逐行对比，仅收集变化
        changed: list[tuple[int, dict[str, Any]]] = []
        for orig, new in zip(originals, cleaned, strict=True):
            keys = [k for k in orig if k != "id" and orig[k] != new[k]]
            if not keys:
                continue
            before = {k: orig[k] for k in keys}
            after = {k: new[k] for k in keys}
            changed.append((orig["id"], after))
            if len(samples) < SAMPLE_LIMIT:
                samples.append({"row_id": orig["id"], "before": before, "after": after})

        if not preview and changed:
            with engine.begin() as conn:
                for row_id, diff in changed:
                    values = {name_to_field[k].db_column_name: v for k, v in diff.items()}
                    conn.execute(sa_table.update().where(sa_table.c.id == row_id).values(**values))
            updated_rows += len(changed)

        task.done_groups = batches
        task.progress = min(95, 10 + int(80 * batches / max(batches, 1)))
        db_session.commit()
        if len(rows) < BATCH_SIZE:
            break

    affected_list = [
        {"action": act, "column": column, "strategy": strategy, "affected_rows": n}
        for (act, column, strategy), n in affected.items()
    ]
    if preview:
        task.report = json.dumps(
            {"mode": "preview", "affected": affected_list, "samples": samples}, ensure_ascii=False, default=str
        )
    else:
        try:
            log_action(
                db_session,
                table,
                AUDIT_ACTION_CLEAN,
                detail={"actions": actions, "affected": affected_list, "updated_rows": updated_rows},
            )
        except Exception as exc:  # pragma: no cover - 审计尽力而为
            logger.debug("clean audit 失败: %s", exc)
        task.report = json.dumps(
            {"mode": "execute", "affected": affected_list, "updated_rows": updated_rows},
            ensure_ascii=False,
            default=str,
        )
    db_session.commit()


def _validate_actions(table: DataTable, actions: list[dict[str, Any]]) -> list[Any]:
    """校验动作配置，返回涉及字段的去重列表（保持出现顺序）."""
    physical = {
        f.name: f
        for f in table.active_fields()
        if not is_link_field(f) and (ft := default_registry.get(f.field_type)) is not None and ft.has_physical_column
    }
    involved: list[Any] = []
    seen: set[str] = set()
    for action in actions:
        act = str(action.get("action") or "")
        if act not in SUPPORTED_ACTIONS:
            raise GovernanceTaskError(f"不支持的清洗 action: {act}")
        column = str(action.get("column") or "")
        f = physical.get(column)
        if f is None:
            raise GovernanceTaskError(f"清洗字段不存在或无物理列: {column}")
        if column not in seen:
            seen.add(column)
            involved.append(f)
    return involved


def _build_profiles(
    engine: Any, table: DataTable, involved_fields: list[Any], actions: list[dict[str, Any]]
) -> dict[tuple[str, str], dict[str, Any]]:
    """按动作需求计算统计口径，返回 {(action, column): profile}."""
    profiles: dict[tuple[str, str], dict[str, Any]] = {}
    for action in actions:
        act = action["action"]
        column = action["column"]
        strategy = action.get("strategy")
        if act == "fill_null":
            if strategy == "mean":
                profiles[(act, column)] = {"mean": _column_stat(engine, table, involved_fields, column, "mean")}
            elif strategy == "median":
                profiles[(act, column)] = {"median": _column_stat(engine, table, involved_fields, column, "median")}
            elif strategy == "default":
                profiles[(act, column)] = {"fill_value": action.get("fill_value")}
        elif act == "drop_outliers":
            values = _column_values(engine, table, involved_fields, column)
            outlier_values = _iqr_outliers(values)
            profiles[(act, column)] = {"outliers": [{"value": v, "type": "numeric"} for v in outlier_values]}
    return profiles


def _column_values(engine: Any, table: DataTable, involved_fields: list[Any], column: str) -> list[float]:
    """分批收集某列的数值（非数值值跳过）."""
    f = next(f for f in involved_fields if f.name == column)
    sa_table = get_reflected_table(engine, table.db_table_name, missing_message="物理表不存在")
    values: list[float] = []
    last_id = 0
    while True:
        query = (
            select(sa_table.c.id, sa_table.c[f.db_column_name])
            .where(sa_table.c.id > last_id, sa_table.c._trashed.is_(False))
            .order_by(sa_table.c.id)
            .limit(BATCH_SIZE)
        )
        with engine.connect() as conn:
            rows = conn.execute(query).all()
        if not rows:
            break
        for r in rows:
            last_id = int(r[0])
            v = r[1]
            if isinstance(v, bool):  # pragma: no cover - 防御
                continue
            if isinstance(v, (int, float)):
                values.append(float(v))
        if len(rows) < BATCH_SIZE:
            break
    return values


def _column_stat(engine: Any, table: DataTable, involved_fields: list[Any], column: str, kind: str) -> float | None:
    """计算列统计值（mean / median），无数值返回 None."""
    import statistics

    values = _column_values(engine, table, involved_fields, column)
    if not values:
        return None
    return statistics.mean(values) if kind == "mean" else statistics.median(values)


def _iqr_outliers(values: list[float]) -> list[float]:
    """IQR 法异常值：低于 Q1-1.5*IQR 或高于 Q3+1.5*IQR."""
    import statistics

    if len(values) < 4:
        return []
    q1, _q2, q3 = statistics.quantiles(values, n=4, method="inclusive")
    iqr = q3 - q1
    low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return [v for v in values if v < low or v > high]


__all__ = ["AUDIT_ACTION_CLEAN", "SUPPORTED_ACTIONS", "execute_clean_task"]
