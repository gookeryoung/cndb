"""重复检测 —— 精确匹配分页扫描.

按 id 分页扫描物理表（不持有全行），判重键归一化在 Python 层完成
（casefold + strip，可选项控制），跨 SQLite / PostgreSQL 语义一致。
产出报告 JSON 写入 task.report，分组只保存键值与行 id。
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from sqlalchemy import select

from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core.ddl import get_reflected_table
from cndb.plugins.tables.services.core.links import is_link_field
from cndb.plugins.tables.services.governance.tasks import GovernanceTaskError

# 分页扫描批大小
BATCH_SIZE = 5000

# 归一化选项键
OPTION_IGNORE_CASE = "ignore_case"
OPTION_IGNORE_WHITESPACE = "ignore_whitespace"


class DuplicateDetector(Protocol):
    """检测器协议（预留模糊匹配等扩展实现）."""

    def detect(
        self,
        engine: Any,
        table: DataTable,
        match_fields: list[str],
        *,
        ignore_case: bool = False,
        ignore_whitespace: bool = False,
        on_progress: Any = None,
    ) -> dict[str, Any]: ...


def normalize_match_value(
    value: Any,
    *,
    ignore_case: bool = False,
    ignore_whitespace: bool = False,
) -> str:
    """把字段值归一化为判重键字符串：None 视为空串."""
    s = "" if value is None else str(value)
    if ignore_whitespace:
        s = s.strip()
    if ignore_case:
        s = s.casefold()
    return s


class ExactMatcher:
    """精确匹配检测器：归一化键全等分组."""

    batch_size = BATCH_SIZE

    def detect(
        self,
        engine: Any,
        table: DataTable,
        match_fields: list[str],
        *,
        ignore_case: bool = False,
        ignore_whitespace: bool = False,
        on_progress: Any = None,
    ) -> dict[str, Any]:
        """分页扫描全表，返回检测报告 dict.

        报告结构：
            {"total_rows", "duplicate_row_count", "group_count",
             "groups": [{"member_row_ids": [...], "match_key_values": {...}}]}

        Raises:
            GovernanceTaskError: 判重字段不存在、已进回收站或无物理列.
        """
        cols = _resolve_match_columns(table, match_fields)
        sa_table = get_reflected_table(
            engine,
            table.db_table_name,
            missing_message=f"物理表 {table.db_table_name} 不存在",
        )
        select_cols = [sa_table.c.id, *[sa_table.c[f.db_column_name] for f in cols]]

        groups: dict[tuple[str, ...], list[int]] = {}
        total_rows = 0
        last_id = 0
        while True:
            query = (
                select(*select_cols)
                .where(sa_table.c.id > last_id, sa_table.c._trashed.is_(False))
                .order_by(sa_table.c.id)
                .limit(self.batch_size)
            )
            with engine.connect() as conn:
                rows = conn.execute(query).all()
            if not rows:
                break
            for row in rows:
                last_id = int(row[0])
                total_rows += 1
                key = tuple(
                    normalize_match_value(row[i + 1], ignore_case=ignore_case, ignore_whitespace=ignore_whitespace)
                    for i in range(len(cols))
                )
                groups.setdefault(key, []).append(last_id)
            if on_progress is not None:
                on_progress(total_rows)
            if len(rows) < self.batch_size:
                break

        dup_groups = [
            {"member_row_ids": row_ids, "match_key_values": dict(zip(match_fields, key, strict=True))}
            for key, row_ids in groups.items()
            if len(row_ids) > 1
        ]
        dup_groups.sort(key=lambda g: g["member_row_ids"][0])
        return {
            "total_rows": total_rows,
            "duplicate_row_count": sum(len(g["member_row_ids"]) for g in dup_groups),
            "group_count": len(dup_groups),
            "groups": dup_groups,
        }


def _resolve_match_columns(table: DataTable, match_fields: list[str]) -> list[DataField]:
    """把判重字段名解析为 DataField 列表，校验存在且有物理列."""
    field_map = {f.name: f for f in table.active_fields()}
    cols: list[DataField] = []
    for name in match_fields:
        f = field_map.get(name)
        if f is None:
            raise GovernanceTaskError(f"判重字段不存在: {name}")
        ft = default_registry.get(f.field_type)
        if is_link_field(f) or ft is None or not ft.has_physical_column:
            raise GovernanceTaskError(f"字段 {name} 不支持作为判重字段（无物理列）")
        cols.append(f)
    return cols


def execute_detect_task(db_session: Any, task: Any) -> None:
    """执行检测任务（任务已处于 running 状态），写报告与分组进度."""
    table = db_session.get(DataTable, task.table_id)
    if table is None:  # pragma: no cover - tasks.execute 已校验
        raise RuntimeError(f"数据表 {task.table_id} 不存在")
    config = task.config or {}
    match_fields = [str(n) for n in config.get("match_fields") or []]
    if not match_fields:
        raise GovernanceTaskError("检测配置缺少 match_fields")

    engine = db_session.get_bind()

    def on_progress(total_rows: int) -> None:
        task.progress = min(95, 5 + int(total_rows / 100))
        db_session.commit()

    matcher: DuplicateDetector = ExactMatcher()
    report = matcher.detect(
        engine,
        table,
        match_fields,
        ignore_case=bool(config.get(OPTION_IGNORE_CASE)),
        ignore_whitespace=bool(config.get(OPTION_IGNORE_WHITESPACE)),
        on_progress=on_progress,
    )
    task.total_groups = report["group_count"]
    task.done_groups = report["group_count"]
    task.report = json.dumps(report, ensure_ascii=False, default=str)
    db_session.commit()


__all__ = [
    "BATCH_SIZE",
    "DuplicateDetector",
    "ExactMatcher",
    "execute_detect_task",
    "normalize_match_value",
]
