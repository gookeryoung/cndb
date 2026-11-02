"""落点分发：表落点走既有 upsert + 逐条写台账（ADR 0085 §2 / D4 / D13）.

本模块只做「候选 → 目标行 → 幂等落表 → 台账」，不新增写路径：

- 表：``datasource.services.write.upsert_rows``（``match_keys`` 幂等 + 轻量模式），
  空表时允许自动补字段（对齐 ADR 0019 的自动建表口径）；
- 文档落点（P1）复用 ``documents.services.content``，本期未启用。

台账 ``acquisition_item`` 是跨运行去重与来源追溯的唯一依据：同 ``(strategy, dedupe_key)``
至多一行，落点 id 记在 ``target_id``。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.acquisition.models import AcquisitionItem, AcquisitionStrategy
from cndb.plugins.acquisition.services.rules.dedupe import content_digest, dedupe_key
from cndb.plugins.datasource.services.auto_table import is_table_empty
from cndb.plugins.datasource.services.normalize import apply_field_mapping
from cndb.plugins.datasource.services.runner import field_mapping_from_payload
from cndb.plugins.datasource.services.write import upsert_rows

__all__ = ["TargetReport", "dispatch_table_target", "existing_keys", "table_targets"]

#: 台账 / 表行都不接收的候选内部键
_INTERNAL_KEYS = ("match_score", "channel", "raw")


@dataclass(slots=True)
class TargetReport:
    """一次落点的计数结果（并入 ``acquisition_run``）."""

    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    written: int = 0
    table_id: int | None = None
    errors: list[dict[str, str]] = field(default_factory=list)


def table_targets(strategy: AcquisitionStrategy) -> list[dict[str, Any]]:
    """策略声明里的表落点（本期只处理 ``kind == "table"``）."""
    return [dict(target) for target in list(strategy.targets or []) if str(target.get("kind")) == "table"]


def existing_keys(db: Session, strategy_id: int, keys: Sequence[str]) -> set[str]:
    """查台账中已存在的去重键（分批查询，避免超长 IN）."""
    from sqlalchemy import select

    found: set[str] = set()
    unique = list(dict.fromkeys(keys))
    for start in range(0, len(unique), 500):
        chunk = unique[start : start + 500]
        stmt = select(AcquisitionItem.dedupe_key).where(
            AcquisitionItem.strategy_id == strategy_id,
            AcquisitionItem.dedupe_key.in_(chunk),
        )
        found.update(db.execute(stmt).scalars())
    return found


def _load_ledger(
    db: Session,
    strategy_id: int,
    items: Sequence[Mapping[str, Any]],
    identity: Sequence[str] = (),
) -> dict[str, AcquisitionItem]:
    """按本批去重键取已有台账行（分批查询，避免超长 IN）."""
    from sqlalchemy import select

    keys = list(dict.fromkeys(dedupe_key(item, str(item.get("channel") or ""), identity) for item in items))
    found: dict[str, AcquisitionItem] = {}
    for start in range(0, len(keys), 500):
        chunk = keys[start : start + 500]
        stmt = select(AcquisitionItem).where(
            AcquisitionItem.strategy_id == strategy_id,
            AcquisitionItem.dedupe_key.in_(chunk),
        )
        for row in db.execute(stmt).scalars():
            found[row.dedupe_key] = row
    return found


def _scalar_row(item: Mapping[str, Any]) -> dict[str, Any]:
    """无字段映射时直接取标量键（嵌套对象 / 内部键 / 以下划线开头的临时键丢弃）."""
    return {
        str(key): value
        for key, value in item.items()
        if not str(key).startswith("_")
        and key not in _INTERNAL_KEYS
        and (isinstance(value, (str, int, float, bool)) or value is None)
    }


def _rows_from_items(
    items: Sequence[Mapping[str, Any]],
    mapping: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """候选 → 目标行；声明了 ``field_mapping`` 时按同一套归一逻辑换名 / 转类型."""
    if not mapping:
        return [_scalar_row(item) for item in items]
    transforms = field_mapping_from_payload(mapping)
    return apply_field_mapping(items, transforms).rows


def _record_item(
    db: Session,
    *,
    strategy_id: int,
    run_id: int | None,
    round_no: int,
    item: Mapping[str, Any],
    key: str,
    target_id: int | None,
    existing: dict[str, AcquisitionItem],
) -> None:
    """写一条台账（同键已存在则更新，保证唯一约束不冲突且留最新一次运行）."""
    payload = {
        "run_id": run_id,
        "round_no": round_no,
        "channel": str(item.get("channel") or "")[:64],
        "title": str(item.get("title") or "")[:500],
        "source_url": str(item.get("url") or item.get("source_url") or "")[:1000],
        "published_at": str(item.get("published_at") or "")[:64],
        "match_score": int(item.get("match_score") or 0),
        "target_kind": "table",
        "target_id": target_id,
        "payload_digest": content_digest(item.get("title"), item.get("summary") or item.get("content")),
    }
    row = existing.get(key)
    if row is None:
        db.add(AcquisitionItem(strategy_id=strategy_id, dedupe_key=key[:512], **payload))
        return
    for field_name, value in payload.items():
        setattr(row, field_name, value)
    db.add(row)


def dispatch_table_target(
    db: Session,
    *,
    strategy: AcquisitionStrategy,
    items: Sequence[Mapping[str, Any]],
    run_id: int | None,
    round_no: int,
    user: Any = None,
    identity: Sequence[str] = (),
) -> TargetReport:
    """把通过筛选的候选写入策略声明的表落点并记账."""
    from cndb.plugins.tables.models import DataTable

    report = TargetReport()
    targets = table_targets(strategy)
    if not targets:
        report.skipped = len(items)
        return report

    for target in targets:
        table_id = target.get("table_id")
        if table_id is None:
            report.errors.append({"target": "table", "error": "table 落点缺少 table_id"})
            continue
        table = db.get(DataTable, int(table_id))
        if table is None or table.workspace_id != strategy.workspace_id:
            report.errors.append({"target": f"table:{table_id}", "error": "目标表不存在或不属于当前工作区"})
            continue

        rows = _rows_from_items(items, target.get("field_mapping"))
        if not rows:
            report.skipped += len(items)
            continue
        match_keys = tuple(str(key) for key in (target.get("match_keys") or ()) if str(key).strip())
        try:
            outcome = upsert_rows(
                db.get_bind(),
                db,
                table,
                rows,
                match_keys=match_keys,
                user=user,
                auto_add_fields=not match_keys and is_table_empty(db, table),
                auto_match_keys=not match_keys,
                light=True,
            )
        except Exception as exc:  # 落点失败不影响台账之外的数据，按 partial 留痕
            db.rollback()
            report.errors.append({"target": f"table:{table_id}", "error": str(exc)[:300]})
            continue

        report.table_id = int(table_id)
        report.inserted += outcome.inserted
        report.updated += outcome.updated
        report.skipped += outcome.skipped
        report.written += outcome.changed

        fields = tuple(identity) or match_keys
        ledger = _load_ledger(db, strategy.id, items, fields)
        for item in items:
            key = dedupe_key(item, str(item.get("channel") or ""), fields)
            _record_item(
                db,
                strategy_id=strategy.id,
                run_id=run_id,
                round_no=round_no,
                item=item,
                key=key,
                target_id=int(table_id),
                existing=ledger,
            )
    db.commit()
    return report
