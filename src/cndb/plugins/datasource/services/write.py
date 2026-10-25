"""落表 —— 把归一后的行按 ``match_keys`` 幂等写入目标数据表.

复用 tables 的 ``Importer``（analyze → execute），因此校验、未知列策略、
行级写范围与审计口径与既有导入链路完全一致；本模块只负责把结果压成
``datasource_sync_run`` 需要的计数字段。

幂等由应用层「先查后写」保证（ADR 0006 已确认不引入复合唯一索引）：
同一 ``match_keys`` 组合重复运行只会更新既有行，不会新增重复行。

ADR 0034 D6 扩展：为目标表按 ``match_keys`` 建**非唯一**复合索引（幂等
``CREATE INDEX IF NOT EXISTS``）——千万行级大表上「先查后写」的批量 OR
查询没有索引会退化为全表扫描。非唯一不改变应用层幂等口径（0006 否决的
是唯一约束，普通索引只加速查找）。

多 job 分列写同一行时使用 ``partial=True``：只更新本次 job 实际提供的列，
未提供的列保持原值，避免不同周期/复权任务互相把对方的 JSON 列清空。

ADR 0019 扩展（仅 ``llm_prompt`` 链路会打开）：

- ``auto_add_fields``：目标空表时自动补字段（``unknown_cols_strategy="add_text_field"``）；
- ``auto_match_keys``：任务没配幂等键时从行数据推断，推断成功则按推断键做 upsert。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WriteOutcome:
    """一次落库的计数结果（对应 datasource_sync_run 的 fetched / inserted / updated / skipped）."""

    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed_rows: int = 0
    # 本次自动新增的字段名（ADR 0019；非空表 / 非 llm_prompt 时为空）
    auto_fields: list[str] = field(default_factory=list)
    # 本次实际使用的幂等键（含自动推断结果，供 runner 回填 job.match_keys）
    match_keys: list[str] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return self.inserted + self.updated


def upsert_rows(
    engine: Any,
    db: Any,
    table: Any,
    rows: Sequence[dict[str, Any]],
    *,
    match_keys: Sequence[str] = (),
    user: Any = None,
    auto_add_fields: bool = False,
    auto_match_keys: bool = False,
) -> WriteOutcome:
    """按 ``match_keys`` 幂等落表.

    Args:
        engine: SQLAlchemy Engine（动态表写入用）。
        db: SQLAlchemy Session（字段元数据与 link 关联表用）。
        table: 目标 ``DataTable``。
        rows: 已归一的行（列名 = 目标字段名）。
        match_keys: 幂等键（目标字段名）；为空退化为纯追加。
        user: 触发同步的用户，用于行级写范围判定；定时任务传 ``None``。
        auto_add_fields: 目标表为空时自动补字段（ADR 0019；仅 llm_prompt 打开）。
        auto_match_keys: ``match_keys`` 为空时自动推断幂等键（ADR 0019）。
    """
    if not rows:
        return WriteOutcome()

    from cndb.plugins.datasource.services.auto_table import candidate_names, infer_match_keys
    from cndb.plugins.tables.services.importing.importer import Importer

    keys = [key for key in match_keys if key]
    ensure_match_keys_index(db, table, keys)
    importer = Importer(engine, db, table, user=user, partial=True)
    # content 占位为空串：行已解析好，走 rows 入口（与 import_api 的 JSON 数组导入同口径）
    analysis = importer.analyze("", rows=list(rows), match_keys=keys or None)

    # ── ADR 0019：自动幂等键 —— upsert 分类依赖 match_keys，推断出键后需重新 analyze ──
    if auto_match_keys and not keys:
        field_names = [item.name for item in table.active_fields()]
        inferred = infer_match_keys(rows, candidate_names(rows, field_names))
        if inferred:
            keys = inferred
            analysis = importer.analyze("", rows=list(rows), match_keys=keys)

    # 自动补字段必须走 execute 的 add_text_field 策略：由 Importer 建 DataField + DDL
    existing_names = {item.name for item in table.active_fields()}
    result = importer.execute(
        analysis=analysis,
        match_keys=keys or None,
        unknown_cols_strategy="add_text_field" if auto_add_fields else "drop",
    )
    auto_fields: list[str] = []
    if auto_add_fields:
        auto_fields = [item.name for item in table.active_fields() if item.name not in existing_names]

    report = result.report or {}
    outcome = WriteOutcome(
        fetched=len(rows),
        inserted=int(report.get("actually_created", 0) or 0),
        updated=int(report.get("actually_updated", 0) or 0),
        skipped=int(report.get("error_count", 0) or 0),
        failed_rows=len(result.failed_results),
        auto_fields=auto_fields,
        match_keys=list(keys),
    )
    logger.info(
        "数据源落表完成: fetched=%d inserted=%d updated=%d skipped=%d auto_fields=%s match_keys=%s",
        outcome.fetched,
        outcome.inserted,
        outcome.updated,
        outcome.skipped,
        outcome.auto_fields,
        outcome.match_keys,
    )
    return outcome


def ensure_match_keys_index(db: Any, table: Any, match_keys: Sequence[str]) -> None:
    """为目标表按 ``match_keys`` 建非唯一复合索引（幂等，ADR 0034 D6）.

    列序 = 幂等键声明顺序，列名取各 ``DataField.db_column_name``；
    缺字段的键跳过（auto 推断键尚未建列等场景），全部缺失则不建。
    """
    if not match_keys:
        return
    columns: list[str] = []
    fields = {item.name: item for item in table.active_fields()}
    for key in match_keys:
        item = fields.get(key)
        if item is not None:
            columns.append(f'"{item.db_column_name}"')
    if not columns:
        return
    index_name = f"ix_{table.db_table_name}_match"
    statement = text(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table.db_table_name}" ({", ".join(columns)})')
    db.execute(statement)
    db.commit()


__all__ = ["WriteOutcome", "ensure_match_keys_index", "upsert_rows"]
