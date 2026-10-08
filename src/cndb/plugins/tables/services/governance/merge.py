"""重复合并 —— 字段级融合 + link 引用迁移 + 回收站.

逐组执行，单组事务原子（组内失败整组回滚，任务级继续下一组）：
1. 重读组内行，校验成员齐全且判重键值未漂移（漂移组跳过并记入报告）；
2. 按 SurvivorshipRule（non_empty_first/latest/oldest/manual）融合非判重字段；
3. 其余行置 _trashed（复用 records.trash_row 语义，可从回收站恢复）；
4. 遍历全工作区入向 link 字段，把指向被合并行的引用迁移到保留行；
5. 每组写一条 action=merge 审计（含配置快照）。

latest / oldest 以行 id 为时间代理（行 id 单调递增，物理行无时间戳列）。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core.audit import log_action
from cndb.plugins.tables.services.core.ddl import get_reflected_table
from cndb.plugins.tables.services.core.links import (
    LINK_FIELD_TYPE,
    is_link_field,
    link_table_exists,
)
from cndb.plugins.tables.services.governance.detect import normalize_match_value
from cndb.plugins.tables.services.governance.tasks import GovernanceTaskError

logger = logging.getLogger(__name__)

# 融合策略
SURVIVORSHIP_RULES = ("non_empty_first", "latest", "oldest", "manual")

AUDIT_ACTION_MERGE = "merge"


def execute_merge_task(db_session: Any, task: Any) -> None:
    """执行合并任务（任务已处于 running 状态），逐组处理并写报告与进度."""
    table = db_session.get(DataTable, task.table_id)
    if table is None:  # pragma: no cover - tasks.execute 已校验
        raise RuntimeError(f"数据表 {task.table_id} 不存在")
    config = task.config or {}
    groups_cfg = config.get("groups") or []
    if not groups_cfg:
        raise GovernanceTaskError("合并配置缺少 groups")

    engine = db_session.get_bind()
    match_fields = [str(n) for n in config.get("match_fields") or []]
    ignore_case = bool(config.get("ignore_case"))
    ignore_whitespace = bool(config.get("ignore_whitespace"))

    task.total_groups = len(groups_cfg)
    db_session.commit()

    details: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for idx, group_cfg in enumerate(groups_cfg):
        try:
            details.append(
                _merge_group(
                    db_session,
                    engine,
                    table,
                    group_cfg,
                    match_fields=match_fields,
                    ignore_case=ignore_case,
                    ignore_whitespace=ignore_whitespace,
                )
            )
        except GovernanceTaskError as exc:
            logger.info("GovernanceTask %s 第 %d 组跳过: %s", task.id, idx, exc)
            skipped.append({"group_index": idx, "reason": str(exc)})
        task.done_groups = idx + 1
        task.progress = min(95, 5 + int(90 * (idx + 1) / len(groups_cfg)))
        db_session.commit()

    task.report = json.dumps(
        {"mode": "execute", "merged_count": len(details), "details": details, "skipped": skipped},
        ensure_ascii=False,
        default=str,
    )
    db_session.commit()


def _merge_group(
    db_session: Any,
    engine: Any,
    table: DataTable,
    group_cfg: dict[str, Any],
    *,
    match_fields: list[str],
    ignore_case: bool,
    ignore_whitespace: bool,
) -> dict[str, Any]:
    """合并单组；校验失败抛 GovernanceTaskError（调用方记为跳过）."""
    members = [int(i) for i in dict.fromkeys(group_cfg.get("member_row_ids") or [])]
    survivor_id = int(group_cfg.get("survivor_row_id") or 0)
    if len(members) < 2:
        raise GovernanceTaskError("组成员至少 2 行")
    if survivor_id not in members:
        raise GovernanceTaskError("survivor_row_id 必须在 member_row_ids 中")

    sa_table = get_reflected_table(engine, table.db_table_name, missing_message=f"物理表 {table.db_table_name} 不存在")
    with engine.connect() as conn:
        rows = conn.execute(select(sa_table).where(sa_table.c.id.in_(members), sa_table.c._trashed.is_(False))).all()
    if len(rows) != len(members):
        raise GovernanceTaskError("组成员存在缺失或已删除行，跳过合并")

    # 键漂移校验：所有成员判重键归一化值必须一致
    match_cols = _match_column_map(table, match_fields)
    key_sets = {
        tuple(
            normalize_match_value(row._mapping[col], ignore_case=ignore_case, ignore_whitespace=ignore_whitespace)
            for col in match_cols.values()
        )
        for row in rows
    }
    if len(key_sets) != 1:
        raise GovernanceTaskError("判重键值已漂移，跳过该组")

    row_map = {int(row.id): row._mapping for row in rows}
    survivor_row = row_map[survivor_id]
    updates = _fuse_fields(table, row_map, members, survivor_row, group_cfg, match_fields)

    merged_ids = [m for m in members if m != survivor_id]
    member_set = set(members)
    with engine.begin() as conn:
        if updates:
            conn.execute(sa_table.update().where(sa_table.c.id == survivor_id).values(**updates))
        conn.execute(
            sa_table.update().where(sa_table.c.id.in_(merged_ids)).values(_trashed=True, _trashed_at=datetime.now(UTC))
        )
        for field, link_table in _inbound_link_tables(db_session, engine, table):
            # 组内自引用（源表即本表）不迁移：成员行本身进回收站，引用无意义
            self_ref = field.table_id == table.id
            for mid in merged_ids:
                where = [link_table.c.target_row_id == mid]
                if self_ref:
                    where.append(link_table.c.row_id.not_in(member_set))
                conn.execute(link_table.update().where(*where).values(target_row_id=survivor_id))

    try:
        log_action(
            db_session,
            table,
            AUDIT_ACTION_MERGE,
            target_id=survivor_id,
            detail={
                "survivor_row_id": survivor_id,
                "merged_row_ids": merged_ids,
                "updated_fields": {k: updates[k] for k in updates},
                "group": group_cfg,
            },
        )
    except Exception as exc:  # pragma: no cover - 审计尽力而为
        logger.debug("merge audit 失败: %s", exc)
    return {
        "survivor_row_id": survivor_id,
        "merged_row_ids": merged_ids,
        "updated_fields": {k: updates[k] for k in updates},
    }


def _match_column_map(table: DataTable, match_fields: list[str]) -> dict[str, str]:
    """判重字段名 -> 物理列名."""
    field_map = {f.name: f for f in table.active_fields()}
    result: dict[str, str] = {}
    for name in match_fields:
        f = field_map.get(name)
        if f is None or is_link_field(f):
            raise GovernanceTaskError(f"判重字段无效: {name}")
        result[name] = f.db_column_name
    return result


def _fuse_fields(
    table: DataTable,
    row_map: dict[int, Any],
    members: list[int],
    survivor_row: Any,
    group_cfg: dict[str, Any],
    match_fields: list[str],
) -> dict[str, Any]:
    """按策略融合非判重字段，返回 {物理列名: 新值}（仅与保留行现值不同的字段）."""
    policies = group_cfg.get("field_policies") or {}
    manual_values = group_cfg.get("manual_values") or {}
    default_rule = str(group_cfg.get("survivorship") or "non_empty_first")
    if default_rule not in SURVIVORSHIP_RULES:
        raise GovernanceTaskError(f"未知融合策略: {default_rule}")

    updates: dict[str, Any] = {}
    for f in table.active_fields():
        if f.name in match_fields or is_link_field(f):
            continue
        ft = default_registry.get(f.field_type)
        if ft is None or not ft.has_physical_column:
            continue
        rule = str(policies.get(f.name) or default_rule)
        if rule not in SURVIVORSHIP_RULES:
            raise GovernanceTaskError(f"字段 {f.name} 未知融合策略: {rule}")
        new_value = _rule_value(rule, f, row_map, members, manual_values)
        if new_value is not None and new_value != survivor_row[f.db_column_name]:
            updates[f.db_column_name] = new_value
    return updates


def _rule_value(
    rule: str,
    field: DataField,
    row_map: dict[int, Any],
    members: list[int],
    manual_values: dict[str, Any],
) -> Any:
    """按策略取字段融合值；无法确定时返回 None（保留行维持现值）.

    row_map 的键为物理列名，manual_values / 手动取值按键为字段名.
    """
    if rule == "manual":
        return manual_values.get(field.name)

    if rule == "non_empty_first":
        for mid in members:
            v = row_map[mid].get(field.db_column_name)
            if v is not None and not (isinstance(v, str) and v.strip() == ""):
                return v
        return None

    target_id = max(members) if rule == "latest" else min(members)
    return row_map[target_id].get(field.db_column_name)


def _inbound_link_tables(db_session: Any, engine: Any, table: DataTable) -> list[tuple[DataField, Any]]:
    """全工作区指向本表的 link 字段及其关联物理表."""
    ref_fields = (
        db_session.query(DataField)
        .filter(DataField.field_type == LINK_FIELD_TYPE, DataField.trashed == False)  # noqa: E712
        .all()
    )
    result: list[tuple[DataField, Any]] = []
    for f in ref_fields:
        if not f.config or f.config.get("target_table_id") != table.id:
            continue
        if not link_table_exists(engine, f.link_table_name):
            continue
        result.append((f, get_reflected_table(engine, f.link_table_name, missing_message="关联表不存在")))
    return result


__all__ = ["AUDIT_ACTION_MERGE", "SURVIVORSHIP_RULES", "execute_merge_task"]
