"""``table/value-range`` —— 数值 / 日期区间检查（ADR 0076 C4）.

按目标字段的类型语义把上下限解析为对应 Python 类型（数值列用 float，日期列用
``date`` / ``datetime``，时间戳列用整数秒），再用 SQL 计数统计越界行数。
发现物只带字段名、行数与阈值，不带任何单元格内容（D7）。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select

from cndb.plugins.pipeline.services.checks.base import (
    INPUT_STRING,
    INPUT_STRING_LIST,
    CheckContext,
    CheckInput,
    CheckSpec,
    FindingDraft,
    resolve_fields,
)
from cndb.plugins.pipeline.services.checks.registry import register_check
from cndb.plugins.pipeline.services.errors import CheckError

#: 参与区间检查的字段类型（按 ``default_registry`` 的类型命名）
NUMERIC_FIELD_TYPES = {"number", "float", "percentage"}
DATE_FIELD_TYPES = {"date", "datetime", "timestamp"}
RANGE_FIELD_TYPES = NUMERIC_FIELD_TYPES | DATE_FIELD_TYPES

SPEC = CheckSpec(
    uses="table/value-range",
    title="字段取值区间检查",
    category="table",
    inputs=(
        CheckInput("table", INPUT_STRING, description="数据表名（当前工作区）", required=True),
        CheckInput("fields", INPUT_STRING_LIST, description="检查字段名列表，all 表示全部", default=("all",)),
        CheckInput("min", INPUT_STRING, description="允许的最小值（含）：数值或 ISO 日期 / 时间"),
        CheckInput("max", INPUT_STRING, description="允许的最大值（含）：数值或 ISO 日期 / 时间"),
    ),
    default_severity="warn",
    target_types=("table", "field"),
)


def run(ctx: CheckContext, params: dict[str, Any]) -> Iterable[FindingDraft]:
    """执行区间检查；至少提供 ``min`` / ``max`` 之一."""
    table = ctx.resolve_table(str(params["table"]))
    raw_min = params.get("min")
    raw_max = params.get("max")
    if raw_min is None and raw_max is None:
        raise CheckError("table/value-range 至少需要 min / max 之一")
    fields = resolve_fields(table, list(params.get("fields") or ["all"]), field_types=RANGE_FIELD_TYPES)
    if not fields:
        return []
    sa_table = ctx.reflect(table)
    findings: list[FindingDraft] = []
    with ctx.engine.connect() as conn:
        for field in fields:
            lower = _parse_bound(field, raw_min, label="min") if raw_min is not None else None
            upper = _parse_bound(field, raw_max, label="max") if raw_max is not None else None
            if lower is not None and upper is not None and lower > upper:
                raise CheckError(f"字段「{field.name}」的 min 大于 max")
            column = sa_table.c[field.db_column_name]
            base = select(func.count()).select_from(sa_table).where(sa_table.c._trashed.is_(False))
            if lower is not None:
                count = int(conn.execute(base.where(column < lower)).scalar() or 0)
                if count:
                    findings.append(
                        FindingDraft(
                            message=f"字段「{field.name}」有 {count} 行小于下限 {_display(field, raw_min)}",
                            target_type="table",
                            target_id=table.id,
                            locator={"field_name": field.name},
                            detail={"count": count, "bound": "min", "limit": _display(field, raw_min)},
                        )
                    )
            if upper is not None:
                count = int(conn.execute(base.where(column > upper)).scalar() or 0)
                if count:
                    findings.append(
                        FindingDraft(
                            message=f"字段「{field.name}」有 {count} 行大于上限 {_display(field, raw_max)}",
                            target_type="table",
                            target_id=table.id,
                            locator={"field_name": field.name},
                            detail={"count": count, "bound": "max", "limit": _display(field, raw_max)},
                        )
                    )
    return findings


def _parse_bound(field: Any, raw: Any, *, label: str) -> Any:
    """按字段类型把阈值文本解析为可比较的 Python 值."""
    text = str(raw).strip()
    if not text:
        raise CheckError(f"table/value-range 的 {label} 不能为空")
    if field.field_type in NUMERIC_FIELD_TYPES:
        try:
            return float(text)
        except ValueError as exc:
            raise CheckError(f"字段「{field.name}」的 {label} 不是数值：{text}") from exc
    if field.field_type == "date":
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise CheckError(f"字段「{field.name}」的 {label} 不是 ISO 日期：{text}") from exc
    if field.field_type == "datetime":
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError as exc:
            raise CheckError(f"字段「{field.name}」的 {label} 不是 ISO 日期时间：{text}") from exc
    if field.field_type == "timestamp":
        try:
            return int(text)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CheckError(f"字段「{field.name}」的 {label} 不是整数秒或 ISO 时间：{text}") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    raise CheckError(f"字段「{field.name}」不支持区间检查")  # pragma: no cover - resolve_fields 已过滤


def _display(field: Any, raw: Any) -> str:
    """阈值的人类可读形式（日期 / 时间统一为 ISO 文本）."""
    if field.field_type in NUMERIC_FIELD_TYPES:
        return str(raw)
    if field.field_type == "timestamp":
        return str(raw)
    return str(raw).strip()


register_check(SPEC, run)

__all__ = ["DATE_FIELD_TYPES", "NUMERIC_FIELD_TYPES", "RANGE_FIELD_TYPES", "SPEC", "run"]
