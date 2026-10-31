"""``table/stale`` —— 时间字段新鲜度检查（ADR 0076 C4）.

取时间字段的最大值（最新一条），与当前时刻比较；超过 ``max_age_days`` 即产出
发现。空表 / 全空列不产出发现；未来时间不算过期。发现物不带具体时间值（D7），
只含过期天数与阈值。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select

from cndb.plugins.pipeline.services.checks.base import (
    INPUT_INTEGER,
    INPUT_STRING,
    CheckContext,
    CheckInput,
    CheckSpec,
    FindingDraft,
    resolve_fields,
)
from cndb.plugins.pipeline.services.checks.registry import register_check
from cndb.plugins.pipeline.services.errors import CheckError
from cndb.plugins.tables.field_types import default_registry

#: 支持新鲜度检查的时间字段类型
STALE_FIELD_TYPES = {"date", "datetime", "timestamp"}

SPEC = CheckSpec(
    uses="table/stale",
    title="时间字段新鲜度检查",
    category="table",
    inputs=(
        CheckInput("table", INPUT_STRING, description="数据表名（当前工作区）", required=True),
        CheckInput("field", INPUT_STRING, description="时间字段名（date / datetime / timestamp）", required=True),
        CheckInput("max_age_days", INPUT_INTEGER, description="允许的最大距今天数", default=30),
    ),
    default_severity="warn",
    target_types=("table", "field"),
)


def run(ctx: CheckContext, params: dict[str, Any]) -> Iterable[FindingDraft]:
    """执行新鲜度检查（最新值距今超过阈值即告警）."""
    table = ctx.resolve_table(str(params["table"]))
    field = resolve_fields(table, [str(params["field"])], field_types=STALE_FIELD_TYPES)[0]
    max_age_days = int(params.get("max_age_days", 30))
    if max_age_days < 0:
        raise CheckError("table/stale 的 max_age_days 不能为负数")
    sa_table = ctx.reflect(table)
    with ctx.engine.connect() as conn:
        latest = conn.execute(
            select(func.max(sa_table.c[field.db_column_name]).label("latest")).where(sa_table.c._trashed.is_(False))
        ).scalar()
    if latest is None:
        return []
    age_days = _age_in_days(field, latest)
    if age_days is None or age_days <= max_age_days:
        return []
    return [
        FindingDraft(
            message=f"字段「{field.name}」最新数据距今 {age_days} 天，超过阈值 {max_age_days} 天",
            target_type="table",
            target_id=table.id,
            locator={"field_name": field.name},
            detail={"age_days": age_days, "max_age_days": max_age_days},
        )
    ]


def _age_in_days(field: Any, latest: Any) -> int | None:
    """把最新时间值与当前时刻的差值换算为天数（未来时间返回 None）."""
    now = datetime.now(UTC)
    if field.field_type == "timestamp":
        seconds = int(latest)
        age = (int(now.timestamp()) - seconds) // 86400
        return age if age > 0 else None
    value = _coerce_temporal(field, latest)
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        age = (now - aware).days
    else:
        age = (now.date() - value).days
    return age if age > 0 else None


def _coerce_temporal(field: Any, value: Any) -> date | datetime | None:
    """物理列可能以字符串返回（SQLite 反射），统一按字段类型归一."""
    ft = default_registry.get(field.field_type)
    if ft is None:  # pragma: no cover - resolve_fields 已确保类型存在
        return None
    try:
        parsed = ft.validate_value(value, field.config or {})
    except ValueError:  # pragma: no cover - 历史脏数据兜底
        return None
    if isinstance(parsed, (date, datetime)):
        return parsed
    return None


register_check(SPEC, run)

__all__ = ["SPEC", "STALE_FIELD_TYPES", "run"]
