"""批量查找替换（需求 0149）.

用途：把某字段里的一段文本批量换成另一段（清洗导入数据、统一称谓、修复拼写），
先预览再落库。口径：

- 只作用于**当前筛选范围**（与列表同一份 WHERE：行级权限 + 软删 + 业务过滤）；
- 只处理有物理列的可编辑字段（lookup / formula / link 等虚拟字段 → 400）；
- 匹配模式：``contains``（默认，子串）/ ``exact``（整值相等）/ ``regex``（正则，非法正则 400）；
- ``dry_run=True`` 只统计与预览（最多 20 条前后值），不写库；``dry_run=False`` 走
  ``bulk_update_rows`` 逐行写（复用校验 / 归一化 / 行范围），并跳过校验失败的行；
- 批量链路**不记行历史**（ADR 0144 D4：写放大），改动仍进审计与事件流；
- 值替换后若与其它字段的条件必填冲突（需求 0146），该行校验失败被跳过并在报告中计数。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.core import records as rec

logger = logging.getLogger(__name__)

MATCH_MODES = ("contains", "exact", "regex")

#: 预览最多返回的变化条目数
PREVIEW_LIMIT = 20

#: 单次替换最多处理的匹配行数（超过要求收窄筛选）
REPLACE_MAX_ROWS = 20_000


def _replacement_fn(find: str, replace: str, match: str) -> Any:
    """按匹配模式构造"旧值 → 新值"的转换函数（不匹配返回 None）."""

    def _exact(value: str) -> str | None:
        return replace if value == find else None

    def _contains(value: str) -> str | None:
        return value.replace(find, replace) if find in value else None

    if match == "exact":
        return _exact
    if match == "regex":
        try:
            pattern = re.compile(find)
        except re.error as exc:
            raise ValueError(f"正则表达式非法: {exc}") from exc

        def _regex(value: str) -> str | None:
            return pattern.sub(replace, value) if pattern.search(value) else None

        return _regex
    return _contains


def bulk_replace(
    engine: Any,
    table: DataTable,
    *,
    field_name: str,
    find: str,
    replace: str = "",
    match: str = "contains",
    filters: list[dict[str, Any]] | None = None,
    filter_logic: str = "AND",
    dry_run: bool = True,
    db: Session | None = None,
    user: Any = None,
    max_rows: int = REPLACE_MAX_ROWS,
) -> dict[str, Any]:
    """在筛选范围内批量替换某字段的文本，返回报告（``dry_run`` 时不写库）.

    Returns:
        ``{"field", "match", "dry_run", "matched", "updated", "skipped", "preview"}``
    """
    from cndb.plugins.tables.field_types import default_registry

    if match not in MATCH_MODES:
        raise ValueError(f"不支持的匹配模式: {match}（可选 {' / '.join(MATCH_MODES)}）")
    if find == "":
        raise ValueError("要查找的内容不能为空")

    field = next((f for f in table.active_fields() if f.name == field_name), None)
    if field is None:
        raise ValueError(f"字段不存在: {field_name}")
    ft = default_registry.get(field.field_type)
    if ft is None or not ft.has_physical_column:
        raise ValueError(f"字段「{field_name}」没有物理列（lookup / formula / link 等），不支持批量替换")
    if field.field_type not in ("text", "email", "url", "phone"):
        raise ValueError(f"字段「{field_name}」不是文本类型（当前 {field.field_type}），不支持批量替换")

    transformer = _replacement_fn(find, replace, match)

    # 复用列表读路径拿候选行（行级权限 / 软删 / 业务过滤与界面一致）
    rows, total = rec.list_rows(
        engine,
        table,
        filters=filters or None,
        filter_logic=filter_logic,
        limit=0,  # 0 = 全量（由 max_rows 兜底）
        db=db,
        user=user,
    )
    if total > max_rows:
        raise ValueError(f"匹配范围有 {total} 行，超过单次替换上限 {max_rows} 行，请收窄筛选后重试")

    from cndb.plugins.tables.services.core.field_rules import validate_row_constraints

    updates: list[dict[str, Any]] = []
    preview: list[dict[str, Any]] = []
    candidates = 0
    skipped_by_rules = 0
    for row in rows:
        raw = row.get(field_name)
        if raw is None or isinstance(raw, (list, dict)):
            continue
        text = str(raw)
        new_value = transformer(text)
        if new_value is None or new_value == text:
            continue
        candidates += 1
        # 字段级规则（需求 0146）：替换后的值必须仍然合法，否则该行跳过（不整批失败）
        try:
            validate_row_constraints(table, {**row, field_name: new_value})
        except ValueError:
            skipped_by_rules += 1
            continue
        updates.append({"row_id": row.get("id"), "values": {field_name: new_value}})
        if len(preview) < PREVIEW_LIMIT:
            preview.append({"row_id": row.get("id"), "old": text, "new": new_value})

    report: dict[str, Any] = {
        "field": field_name,
        "match": match,
        "dry_run": bool(dry_run),
        "matched": candidates,
        "updated": 0,
        "skipped": skipped_by_rules,
        "preview": preview,
    }
    if dry_run or not candidates:
        return report

    updated = rec.bulk_update_rows(engine, table, updates, db=db, user=user, skip_invalid=True)
    report["updated"] = int(updated)
    report["skipped"] += len(updates) - int(updated)
    logger.info(
        "批量替换：表 %s 字段 %s 匹配 %d 行，更新 %d 行，跳过 %d 行",
        table.name,
        field_name,
        candidates,
        report["updated"],
        report["skipped"],
    )
    return report


__all__ = ["MATCH_MODES", "PREVIEW_LIMIT", "REPLACE_MAX_ROWS", "bulk_replace"]
