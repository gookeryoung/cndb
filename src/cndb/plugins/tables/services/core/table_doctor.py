"""数据表体检（`cndb tables doctor`，需求 0142 / 路线图 0141 P0-1）.

只读诊断四类「没有出口」的历史脏数据；`fix=True` 时做幂等修复且**不删业务行**：

- ``orphan_links``：关联表里源行或目标行不存在 / 已软删的关系（手工删库、旧版清理
  失败会留下；此前没有任何巡检入口）。
- ``stale_lookup``：消费方 ``_lk_*`` 冗余列与当前源值不一致（ADR 0131 口径）——会
  直接让按 lookup 的过滤 / 排序 / COUNT 与可见行不符。
- ``orphan_sort_indexes``：``ix_{表}_sort_*`` 索引已不被任何视图的 sortings 需要
  （视图改排序后旧索引没有淘汰机制，ADR 0046 D4）。
- ``trash``：回收站体积（已软删行 / 时间未知行 / 按保留期可清理行）。

行清理不在这里做：那是 `cndb tables purge-trash` 的职责（ADR 0139 D4）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from cndb.plugins.tables.models import DataField, DataTable, DataView
from cndb.plugins.tables.services.core.ddl import get_reflected_table

logger = logging.getLogger(__name__)

#: 每类问题附带的样例上限（报告要能一眼看懂，不刷屏）
SAMPLE_LIMIT = 10


# ── 范围与辅助 ────────────────────────────────────────


def _scoped_tables(db: Session, workspace_id: int | None, table_id: int | None) -> list[DataTable]:
    query = db.query(DataTable).filter(DataTable.trashed_at.is_(None))
    if workspace_id is not None:
        query = query.filter(DataTable.workspace_id == int(workspace_id))
    if table_id is not None:
        query = query.filter(DataTable.id == int(table_id))
    return query.order_by(DataTable.id).all()


def _target_table_name(db: Session, field: DataField) -> str | None:
    """解析关联 / lookup 目标表的物理表名（配置缺失或目标表已删返回 None）."""
    target_id = (field.config or {}).get("target_table_id")
    if not isinstance(target_id, int):
        return None
    target = db.get(DataTable, target_id)
    return str(target.db_table_name) if target is not None else None


def _valid_ids(engine: Any, db_table_name: str, ids: list[int]) -> set[int]:
    """物理表中存在且未软删的行 id（表缺失按空集处理）."""
    if not ids:
        return set()
    try:
        sa_table = get_reflected_table(engine, db_table_name)
    except RuntimeError:  # pragma: no cover - 物理表缺失（历史残留）
        return set()
    stmt = select(sa_table.c.id).where(sa_table.c.id.in_(ids))
    if hasattr(sa_table.c, "_trashed"):
        stmt = stmt.where(sa_table.c._trashed.is_(False))
    with engine.connect() as conn:
        return {int(r[0]) for r in conn.execute(stmt).all()}


def _link_sa_table(engine: Any, field: DataField) -> Any | None:
    try:
        from sqlalchemy import MetaData, Table

        return Table(field.link_table_name, MetaData(), autoload_with=engine)
    except Exception:  # pragma: no cover - 关联表结构异常
        return None


# ── C2：孤儿 link 关系 ────────────────────────────────


def check_orphan_links(db: Session, engine: Any, table: DataTable, *, fix: bool = False) -> dict[str, Any] | None:
    """检查本表各关联字段的关系行是否仍指向有效源行 / 目标行."""
    total = 0
    samples: list[dict[str, Any]] = []
    touched_consumer_fields: list[DataField] = []

    for field in [f for f in table.active_fields() if f.field_type == "link"]:
        link_table = _link_sa_table(engine, field)
        if link_table is None:
            continue
        with engine.connect() as conn:
            pairs = [
                (int(r[0]), int(r[1]))
                for r in conn.execute(select(link_table.c.row_id, link_table.c.target_row_id)).all()
            ]
        if not pairs:
            continue

        valid_sources = _valid_ids(engine, table.db_table_name, sorted({p[0] for p in pairs}))
        target_table_name = _target_table_name(db, field)
        valid_targets = (
            _valid_ids(engine, target_table_name, sorted({p[1] for p in pairs})) if target_table_name else set()
        )

        bad = [
            (row_id, target_id)
            for row_id, target_id in pairs
            if row_id not in valid_sources or target_id not in valid_targets
        ]
        if not bad:
            continue

        total += len(bad)
        samples.extend(
            {"field": field.name, "row_id": row_id, "target_row_id": target_id}
            for row_id, target_id in bad[: max(SAMPLE_LIMIT - len(samples), 0)]
        )

        if fix:
            with engine.begin() as conn:
                for row_id, target_id in bad:
                    conn.execute(
                        link_table.delete().where(
                            (link_table.c.row_id == row_id) & (link_table.c.target_row_id == target_id)
                        )
                    )
                # 消费方 `_lk_*` 依赖本关系，关系删掉后必须重算（ADR 0131 / 0139 C6）
                from cndb.plugins.tables.services.core.lookup_sync import sync_lookup_columns

                rows_to_resync = sorted({row_id for row_id, _t in bad if row_id in valid_sources})
                if rows_to_resync:
                    sync_lookup_columns(engine, table, rows_to_resync, db=db, conn=conn)
            logger.info("表 %s 关联字段 %s 清理孤儿关系 %d 条", table.name, field.name, len(bad))
            del touched_consumer_fields

    if not total:
        return None
    return {
        "table_id": int(table.id),
        "table_name": table.name,
        "count": total,
        "samples": samples,
        "fixed": bool(fix),
    }


# ── C3：失效 lookup 冗余列 ───────────────────────────


def _comparable(value: Any) -> Any:
    """把 BLOB 列读回的 bytes 与 TEXT 归一可比（数值 / 文本原样返回）."""
    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError:  # pragma: no cover - 二进制脏值
            return repr(bytes(value))
    return value


def check_stale_lookup(db: Session, engine: Any, table: DataTable, *, fix: bool = False) -> dict[str, Any] | None:
    """比对消费方 `_lk_*` 与按当前源值编码的结果，报告（或修复）不一致的行.

    只读体检不写库：用 `_resolve_lookup_values` + `encode_lookup_values` 在内存里算出
    期望值再与落库值比对；`fix=True` 时才调用 `sync_lookup_columns` 真正回写。
    """
    from cndb.plugins.tables.services.core.lookup_columns import lookup_column_names
    from cndb.plugins.tables.services.core.lookup_sync import (
        encode_lookup_values,
        lookup_columns_present,
        sync_lookup_columns,
    )
    from cndb.plugins.tables.services.core.lookups import _resolve_lookup_values

    lookup_fields = [f for f in table.active_fields() if f.field_type == "lookup"]
    if not lookup_fields:
        return None
    try:
        sa_table = get_reflected_table(engine, table.db_table_name)
    except RuntimeError:  # pragma: no cover
        return None
    if not lookup_columns_present(sa_table, lookup_fields):
        return None  # 旧库尚未补列：不算问题

    with engine.connect() as conn:
        ids = [int(r[0]) for r in conn.execute(select(sa_table.c.id)).all()]
        if not ids:
            return None
        actual = {
            int(row[0]): row[1:]
            for row in conn.execute(
                select(
                    sa_table.c.id,
                    *[
                        sa_table.c[name]
                        for field in lookup_fields
                        for name in lookup_column_names(field)
                        if hasattr(sa_table.c, name)
                    ],
                )
            ).all()
        }
        columns = [name for field in lookup_fields for name in lookup_column_names(field) if hasattr(sa_table.c, name)]
        expected: dict[int, list[Any]] = {row_id: [] for row_id in ids}
        for field in lookup_fields:
            config = field.config or {}
            link_field = next((f for f in table.active_fields() if f.id == config.get("via_link_field_id")), None)
            multiple = bool((link_field.config or {}).get("multiple", True)) if link_field is not None else True
            values_by_row = _resolve_lookup_values(engine, db, table, config, ids, conn=conn)
            names = [name for name in lookup_column_names(field) if name in columns]
            for row_id in ids:
                encoded = encode_lookup_values(multiple, values_by_row.get(row_id))
                for name, value in zip(lookup_column_names(field), encoded, strict=True):
                    if name in names:
                        expected[row_id].append(value)

    stale = [
        row_id
        for row_id in ids
        if [_comparable(v) for v in actual.get(row_id, ())] != [_comparable(v) for v in expected.get(row_id, [])]
    ]
    if not stale:
        return None

    if fix:
        with engine.begin() as conn:
            sync_lookup_columns(engine, table, stale, db=db, conn=conn, fields=lookup_fields)
        logger.info("表 %s 重算失效 lookup 冗余列 %d 行", table.name, len(stale))

    return {
        "table_id": int(table.id),
        "table_name": table.name,
        "count": len(stale),
        "samples": sorted(stale)[:SAMPLE_LIMIT],
        "fixed": bool(fix),
    }


# ── C4：孤儿排序索引 ─────────────────────────────────


def _needed_index_signatures(db: Session, table: DataTable) -> set[str]:
    """当前所有视图 sortings 需要的索引名字签名（与 `ddl._sort_signature` 同构）."""
    from cndb.plugins.tables.field_types import default_registry
    from cndb.plugins.tables.services.core.ddl import _sort_signature

    fields = {f.name: f for f in table.active_fields()}
    needed: set[str] = set()
    for view in db.query(DataView).filter(DataView.table_id == table.id).all():
        columns: list[tuple[str, str]] = []
        for item in view.sortings or []:
            if not isinstance(item, dict):
                continue
            name = item.get("field_name") or item.get("field")
            field = fields.get(str(name)) if name else None
            if field is None:
                continue
            ft = default_registry.get(field.field_type)
            if ft is None or not ft.has_physical_column:
                continue
            direction = "desc" if str(item.get("direction", "asc")).lower() == "desc" else "asc"
            columns.append((str(field.db_column_name), direction))
        if columns:
            needed.add(_sort_signature(columns))
    return needed


def check_orphan_sort_indexes(
    db: Session, engine: Any, table: DataTable, *, fix: bool = False
) -> dict[str, Any] | None:
    """报告（或 DROP）不再被任何视图需要的 `ix_*_sort_*` 索引."""
    from sqlalchemy import text

    from cndb.plugins.tables.services.core.ddl import _sort_index_base

    base = _sort_index_base(str(table.db_table_name))
    indexes = [
        str(idx.get("name") or "")
        for idx in inspect(engine).get_indexes(str(table.db_table_name))
        if str(idx.get("name") or "").startswith(base)
    ]
    if not indexes:
        return None
    needed = _needed_index_signatures(db, table)
    orphan = sorted(name for name in indexes if not any(name.endswith(sig) for sig in needed))
    if not orphan:
        return None
    if fix:
        with engine.begin() as conn:
            for name in orphan:
                conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
        logger.info("表 %s 清理孤儿排序索引 %d 个", table.name, len(orphan))
    return {
        "table_id": int(table.id),
        "table_name": table.name,
        "count": len(orphan),
        "samples": orphan[:SAMPLE_LIMIT],
        "fixed": bool(fix),
    }


# ── C5：回收站体积 ───────────────────────────────────


def check_trash(engine: Any, table: DataTable, days: int) -> dict[str, Any] | None:
    """统计已软删 / 时间未知 / 按保留期可清理的行数（只读）."""
    from sqlalchemy import func

    try:
        sa_table = get_reflected_table(engine, table.db_table_name)
    except RuntimeError:  # pragma: no cover
        return None
    if not hasattr(sa_table.c, "_trashed_at"):
        return None
    cutoff = datetime.now(UTC) - timedelta(days=max(days, 1))
    with engine.connect() as conn:
        trashed = int(
            conn.execute(select(func.count(sa_table.c.id)).where(sa_table.c._trashed.is_(True))).scalar() or 0
        )
        if not trashed:
            return None
        unknown = int(
            conn.execute(
                select(func.count(sa_table.c.id)).where(sa_table.c._trashed.is_(True), sa_table.c._trashed_at.is_(None))
            ).scalar()
            or 0
        )
        expired = int(
            conn.execute(
                select(func.count(sa_table.c.id)).where(
                    sa_table.c._trashed.is_(True),
                    sa_table.c._trashed_at.is_not(None),
                    sa_table.c._trashed_at < cutoff,
                )
            ).scalar()
            or 0
        )
    return {
        "table_id": int(table.id),
        "table_name": table.name,
        "trashed": trashed,
        "unknown_time": unknown,
        "expired": expired,
        "retention_days": max(days, 0),
    }


# ── 入口 ─────────────────────────────────────────────


def diagnose(
    db: Session,
    *,
    workspace_id: int | None = None,
    table_id: int | None = None,
    fix: bool = False,
    days: int | None = None,
) -> dict[str, Any]:
    """对（默认全部活动）表做体检，返回可序列化报告.

    Args:
        workspace_id / table_id: 收窄范围。
        fix: 幂等修复（删孤儿 link 关系并重算受影响冗余列、重算失效 lookup 冗余列、
            DROP 孤儿排序索引）；**不删业务行**。
        days: 回收站保留天数（缺省取配置 ``TRASH_RETENTION_DAYS``）。
    """
    from cndb.core.config import settings
    from cndb.plugins.tables.services.core import records as rec

    retention_days = int(days if days is not None else getattr(settings, "TRASH_RETENTION_DAYS", 30))
    engine: Any = db.get_bind()
    tables = _scoped_tables(db, workspace_id, table_id)
    report: dict[str, Any] = {
        "fix": fix,
        "tables_scanned": len(tables),
        "orphan_links": [],
        "stale_lookup": [],
        "orphan_sort_indexes": [],
        "trash": [],
        "issues": 0,
    }

    for table in tables:
        fixed_any = False
        per_table = (
            ("orphan_links", check_orphan_links(db, engine, table, fix=fix)),
            ("stale_lookup", check_stale_lookup(db, engine, table, fix=fix)),
            ("orphan_sort_indexes", check_orphan_sort_indexes(db, engine, table, fix=fix)),
        )
        for key, entry in per_table:
            if entry:
                report[key].append(entry)
                fixed_any = fixed_any or bool(entry.get("fixed"))
        trash_entry = check_trash(engine, table, retention_days)
        if trash_entry:
            report["trash"].append(trash_entry)
        if fixed_any:
            rec._invalidate_search_cache(table)

    report["issues"] = sum(
        sum(int(item.get("count", 0)) for item in report[key])
        for key in ("orphan_links", "stale_lookup", "orphan_sort_indexes")
    )
    return report


__all__ = [
    "SAMPLE_LIMIT",
    "check_orphan_links",
    "check_orphan_sort_indexes",
    "check_stale_lookup",
    "check_trash",
    "diagnose",
]
