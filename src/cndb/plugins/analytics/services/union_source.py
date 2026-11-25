"""分析复合数据源（ADR 0159 P0）：多链接汇总（union all）.

口径（与 ADR 0159 一致）：

- **逐输入同权**：每个输入都过 ``resolve_link``（失效 404 / 无读权 403）+ 行级 + 字段隐藏，
  任一失败即整体失败（L1 / L2，fail-closed，不返回部分结果）；
- **显式列映射**：``columns[].map`` 声明「输出列 ← 各输入字段」，未声明的输入列丢弃；
- **严格类型**：输出列声明类型必须与来源字段类型同族（数值族互认），否则 400；
- **有界**：输入 2–5 个；各输入行数累计不超过 ``ANALYTICS_MAX_SCAN_ROWS``（共享预算）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status

from cndb.plugins.analytics.services.compute import scan_limit

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from cndb.plugins.accounts.models import User
    from cndb.plugins.analytics.schemas import AnalyticsSource

#: union 输入数量上下限（ADR 0159 C6 / L5）
UNION_MIN_INPUTS = 2
UNION_MAX_INPUTS = 5

#: 数值族（互认）；其余按「同族」严格比较
NUMERIC_FAMILY = frozenset({"number", "integer", "decimal", "currency", "percent"})
TEXT_FAMILY = frozenset({"text", "email", "url", "phone", "select", "multiselect"})
DATE_FAMILY = frozenset({"date", "datetime"})
BOOL_FAMILY = frozenset({"boolean", "bool"})


def _family(field_type: str) -> str:
    """字段类型 → 兼容族（未知类型按自身成族，只允许完全同名）."""
    lowered = (field_type or "").strip().lower()
    if lowered in NUMERIC_FAMILY:
        return "number"
    if lowered in TEXT_FAMILY:
        return "text"
    if lowered in DATE_FAMILY:
        return "date"
    if lowered in BOOL_FAMILY:
        return "boolean"
    return lowered or "text"


def _is_compatible(output_type: str, source_type: str) -> bool:
    """输出列声明类型与来源字段类型是否兼容（同族即兼容，数值族互认）."""
    return _family(output_type) == _family(source_type)


def validate_union_source(db: Session, user: User, workspace_id: int, source: AnalyticsSource) -> list[str]:
    """校验 union 数据源，返回**合成后的字段清单**（输出列顺序）.

    保存期与执行期共用：保存期尽早失败（不让用户存一个必然跑不通的模板），
    执行期只做兜底（链接可能在保存后失效）。

    Raises:
        HTTPException: 结构非法 400；链接失效 404；无读权 403。
    """
    from cndb.plugins.workspaces.services.links import link_fields, resolve_link

    inputs = source.inputs or []
    columns = source.columns or []
    if not UNION_MIN_INPUTS <= len(inputs) <= UNION_MAX_INPUTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"汇总数据源需要 {UNION_MIN_INPUTS}–{UNION_MAX_INPUTS} 个输入（当前 {len(inputs)} 个）",
        )
    if not columns:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="汇总数据源至少需要一个输出列")
    names = [column.name for column in columns]
    if len(set(names)) != len(names):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="汇总输出列名不能重复")

    input_ids = [str(item.link_id) for item in inputs]
    if len(set(input_ids)) != len(input_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="汇总输入不能重复")

    # 逐个输入解析（失效 / 无读权原样透出，L2 fail-closed）
    resolved: dict[str, dict[str, str]] = {}
    for item in inputs:
        resolved_link = resolve_link(db, user, workspace_id=workspace_id, link_id=item.link_id)
        fields = link_fields(db, user, resolved_link)
        resolved[str(item.link_id)] = {field["name"]: str(field["field_type"]) for field in fields}

    for column in columns:
        declared = {str(key) for key in (column.map or {})}
        unknown = sorted(declared - set(input_ids))
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"输出列「{column.name}」映射了不属于该汇总的输入: {', '.join(unknown)}",
            )
        for link_id, field_name in (column.map or {}).items():
            field_type = resolved[str(link_id)].get(field_name)
            if field_type is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"输出列「{column.name}」引用了不可用字段（不存在或被隐藏）: {field_name}",
                )
            if not _is_compatible(column.type, field_type):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"输出列「{column.name}」类型不兼容：声明 {column.type}，来源字段 {field_name} 为 {field_type}"
                    ),
                )
    return names


def union_rows(
    db: Session,
    user: User,
    workspace_id: int,
    source: AnalyticsSource,
) -> tuple[list[dict[str, Any]], list[str], int, bool]:
    """取并拼接各输入（union all），返回 (rows, field_names, total, truncated).

    拼接规则：按 ``columns[].map`` 投影；某输入未映射该列 → 该行此列为 ``None``；
    ``id`` 用全局递增序号（合成行，不来自任何源）。扫描额度为**共享预算**（D8）。
    """
    from cndb.plugins.workspaces.services.links import link_rows, resolve_link

    field_names = validate_union_source(db, user, workspace_id, source)
    columns = source.columns or []
    inputs = source.inputs or []

    budget = scan_limit()
    rows: list[dict[str, Any]] = []
    truncated = False
    next_id = 1
    for item in inputs:
        resolved = resolve_link(db, user, workspace_id=workspace_id, link_id=item.link_id)
        # 已校验过；此处只取数（limit=剩余预算，先扣再取，避免 5 个输入各自取满）
        remaining = budget - len(rows)
        if remaining <= 0:
            truncated = True
            break
        payload = link_rows(db, user, resolved, limit=remaining)
        source_rows = payload.get("rows") or []
        if int(payload.get("total") or 0) > len(source_rows):
            truncated = True
        for row in source_rows:
            mapped: dict[str, Any] = {}
            for column in columns:
                field_name = (column.map or {}).get(str(item.link_id))
                mapped[column.name] = None if field_name is None else row.get(field_name)
            mapped["id"] = next_id
            next_id += 1
            rows.append(mapped)
    return rows, field_names, len(rows), truncated


__all__ = [
    "NUMERIC_FAMILY",
    "UNION_MAX_INPUTS",
    "UNION_MIN_INPUTS",
    "union_rows",
    "validate_union_source",
]
