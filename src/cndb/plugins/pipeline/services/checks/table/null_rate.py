"""``table/null-rate`` —— 字段空值率检查.

用 SQL 聚合统计（不逐行扫描），空值率超过阈值即产出 warn 级发现；
发现物只带字段名与比率，不带任何单元格内容（D7）。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select

from cndb.plugins.pipeline.services.checks.base import (
    INPUT_NUMBER,
    INPUT_STRING,
    INPUT_STRING_LIST,
    CheckContext,
    CheckInput,
    CheckSpec,
    FindingDraft,
    resolve_fields,
)
from cndb.plugins.pipeline.services.checks.registry import register_check

SPEC = CheckSpec(
    uses="table/null-rate",
    title="字段空值率检查",
    category="table",
    inputs=(
        CheckInput("table", INPUT_STRING, description="数据表名（当前工作区）", required=True),
        CheckInput("fields", INPUT_STRING_LIST, description="检查字段名列表，all 表示全部", default=("all",)),
        CheckInput("max_rate", INPUT_NUMBER, description="允许的最大空值率（0–1）", default=0.05),
    ),
    default_severity="warn",
    target_types=("table", "field"),
)


def run(ctx: CheckContext, params: dict[str, Any]) -> Iterable[FindingDraft]:
    """执行空值率检查（表为空时不产出发现）."""
    table = ctx.resolve_table(str(params["table"]))
    fields = resolve_fields(table, list(params.get("fields") or ["all"]))
    max_rate = float(params.get("max_rate", 0.05))
    sa_table = ctx.reflect(table)
    findings: list[FindingDraft] = []
    with ctx.engine.connect() as conn:
        total = int(
            conn.execute(select(func.count()).select_from(sa_table).where(sa_table.c._trashed.is_(False))).scalar() or 0
        )
        if total == 0:
            return findings
        for field in fields:
            column = sa_table.c[field.db_column_name]
            null_count = int(
                conn.execute(
                    select(func.count()).select_from(sa_table).where(sa_table.c._trashed.is_(False), column.is_(None))
                ).scalar()
                or 0
            )
            rate = null_count / total
            if rate > max_rate:
                findings.append(
                    FindingDraft(
                        message=f"字段「{field.name}」空值率 {rate:.1%} 超过阈值 {max_rate:.1%}",
                        target_type="table",
                        target_id=table.id,
                        locator={"field_name": field.name},
                        detail={"rate": round(rate, 4), "limit": max_rate, "null_count": null_count, "total": total},
                    )
                )
    return findings


register_check(SPEC, run)

__all__ = ["SPEC", "run"]
