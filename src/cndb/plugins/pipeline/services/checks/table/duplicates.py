"""``table/duplicates`` —— 重复行检查（复用治理判重归一化口径）."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

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
from cndb.plugins.tables.services.governance.detect import normalize_match_value

SPEC = CheckSpec(
    uses="table/duplicates",
    title="重复行检查",
    category="table",
    inputs=(
        CheckInput("table", INPUT_STRING, description="数据表名（当前工作区）", required=True),
        CheckInput("fields", INPUT_STRING_LIST, description="判重字段名列表", required=True),
        CheckInput("ignore_case", "boolean", description="忽略大小写", default=False),
        CheckInput("ignore_whitespace", "boolean", description="忽略首尾空白", default=False),
    ),
    default_severity="warn",
    target_types=("table",),
)


def run(ctx: CheckContext, params: dict[str, Any]) -> Iterable[FindingDraft]:
    """按判重键分组，每组产出一条发现（含成员行 ID，不含量值）."""
    table = ctx.resolve_table(str(params["table"]))
    fields = resolve_fields(table, list(params["fields"]) or ["all"])
    if not fields:
        return []
    scan = ctx.scan_rows(table, fields)
    ignore_case = bool(params.get("ignore_case"))
    ignore_whitespace = bool(params.get("ignore_whitespace"))
    groups: dict[tuple[str, ...], list[int]] = {}
    for row in scan.rows:
        row_id = int(row[0])
        key = tuple(
            normalize_match_value(row[index + 1], ignore_case=ignore_case, ignore_whitespace=ignore_whitespace)
            for index in range(len(fields))
        )
        groups.setdefault(key, []).append(row_id)

    findings: list[FindingDraft] = []
    for row_ids in groups.values():
        if len(row_ids) < 2:
            continue
        findings.append(
            FindingDraft(
                message=f"判重字段「{'、'.join(f.name for f in fields)}」存在 {len(row_ids)} 行重复",
                target_type="table",
                target_id=table.id,
                locator={"row_ids": row_ids, "fields": [f.name for f in fields]},
                detail={"group_size": len(row_ids), "group_count": 1},
            )
        )
    if scan.truncated:
        findings.append(
            FindingDraft(
                message=f"扫描达到行数上限 {ctx.max_scan_rows}，查重结果可能不完整",
                target_type="table",
                target_id=table.id,
                locator={},
                detail={"truncated": True, "scan_limit": ctx.max_scan_rows},
                severity="info",
            )
        )
    return findings


register_check(SPEC, run)

__all__ = ["SPEC", "run"]
