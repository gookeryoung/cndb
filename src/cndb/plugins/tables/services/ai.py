"""数据表 / 导入 AI 动作（ADR 0020 P2）.

本模块只负责：动作声明（输出 schema / 提示词）、模型输入构造与上下文裁剪。
模型调用 / 留痕 / 错误分类走平台 ``cndb.plugins.llm.services.gateway``。

写回口径（ADR 0020 D14）：
- ``table.fill_field`` **只生成建议值**，不写库；前端确认后逐行调用既有记录更新接口
  （直编落库 / 无直编资格自动 202 修改申请）；
- ``import.mapping_suggestion`` **只生成映射建议**，不修改 ``ImportTask``。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field, field_validator

from cndb.plugins.llm.services.actions import ActionSpec, register

# 表格批量填充单次上限（行 / 每行上下文字段数 / 单元格字符数）
MAX_FILL_ROWS = 20
FILL_CONTEXT_FIELDS = 6
MAX_CELL_CHARS = 200
# 导入映射建议单次上限
MAX_HEADERS = 50
MAX_SAMPLE_ROWS = 20
MAX_SAMPLE_COLS = 50


class FieldFillValue(BaseModel):
    """单行建议值（``row_id`` 由路由按可读行集合校验后过滤）."""

    row_id: int
    value: str | int | float | bool | None = None


class FieldFillOutput(BaseModel):
    """``table.fill_field`` 输出."""

    values: list[FieldFillValue] = Field(default_factory=list, max_length=MAX_FILL_ROWS)

    @field_validator("values")
    @classmethod
    def _dedupe(cls, values: list[FieldFillValue]) -> list[FieldFillValue]:
        seen: set[int] = set()
        unique: list[FieldFillValue] = []
        for item in values:
            if item.row_id in seen:
                continue
            seen.add(item.row_id)
            unique.append(item)
        return unique[:MAX_FILL_ROWS]


class MappingItem(BaseModel):
    """一条列映射建议."""

    source: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=255)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=200)


class MappingSuggestionOutput(BaseModel):
    """``import.mapping_suggestion`` 输出（路由会再按真实表字段过滤）."""

    mappings: list[MappingItem] = Field(default_factory=list)
    unmapped: list[str] = Field(default_factory=list)


FILL_FIELD_SYSTEM_PROMPT = (
    "你是数据整理助手。根据每行已有的字段值，为指定目标字段生成建议值。"
    '输出 JSON：{"values": [{"row_id": 行号, "value": "建议值"}]}。'
    "只依据给定行内容，不要编造；无法确定时 value 用 null。"
    "不要输出解释、Markdown 或多余字段；不要修改行号。"
)

MAPPING_SUGGESTION_SYSTEM_PROMPT = (
    "你是数据导入助手。把源表头映射到目标表字段。"
    '输出 JSON：{"mappings": [{"source": 源表头, "target": 目标字段, '
    '"confidence": 0~1 的小数, "reason": "简短理由"}], "unmapped": [无法映射的源表头]}。'
    "只能使用给出的目标字段名；语义不确定时降低 confidence；不要编造目标字段。"
)

FILL_FIELD = register(
    ActionSpec(
        name="table.fill_field",
        label="AI 填充字段",
        scope="table",
        output_schema=FieldFillOutput,
        system_prompt=FILL_FIELD_SYSTEM_PROMPT,
        temperature=0.2,
        max_tokens=2048,
        json_mode=True,
        max_input_chars=24000,
    )
)

MAPPING_SUGGESTION = register(
    ActionSpec(
        name="import.mapping_suggestion",
        label="AI 建议列映射",
        scope="import",
        output_schema=MappingSuggestionOutput,
        system_prompt=MAPPING_SUGGESTION_SYSTEM_PROMPT,
        temperature=0.1,
        max_tokens=1800,
        json_mode=True,
        max_input_chars=20000,
    )
)


def _cell_text(value: Any, *, limit: int = MAX_CELL_CHARS) -> str:
    """单元格 → 文本（列表 / 对象走 JSON，超长截断）."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple, dict)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    return text[:limit]


def build_fill_content(
    table_name: str,
    target_field_name: str,
    target_field_type: str,
    context_fields: Sequence[str],
    rows: Sequence[tuple[int, Mapping[str, Any]]],
    instruction: str | None = None,
) -> str:
    """构造 ``table.fill_field`` 的用户消息.

    Args:
        table_name: 表名（模型理解业务语义用）。
        target_field_name: 目标字段名。
        target_field_type: 目标字段类型（text / number / select …）。
        context_fields: 参与上下文的行字段（已剔除隐藏字段与目标字段）。
        rows: ``(row_id, 行数据)``；行数据已按字段隐藏裁剪。
        instruction: 用户补充说明（可选）。
    """
    lines = [
        f"数据表：{table_name}",
        f"目标字段：{target_field_name}（类型 {target_field_type}）",
    ]
    if instruction:
        lines.append(f"要求：{instruction.strip()[:500]}")
    lines.append("规则：每行必须返回一条 values；value 类型与目标字段一致；无法确定用 null。")
    lines.append("数据行：")
    for row_id, row in rows:
        payload = {name: _cell_text(row.get(name)) for name in context_fields}
        lines.append(json.dumps({"row_id": row_id, **payload}, ensure_ascii=False))
    return "\n".join(lines)


def build_mapping_content(
    headers: Sequence[str],
    sample_rows: Sequence[Sequence[Any]],
    target_fields: Sequence[tuple[str, str]],
    existing_mapping: Mapping[str, str | None] | None = None,
) -> str:
    """构造 ``import.mapping_suggestion`` 的用户消息.

    Args:
        headers: 源文件表头（≤ ``MAX_HEADERS``）。
        sample_rows: 抽样数据行（≤ ``MAX_SAMPLE_ROWS`` 行）。
        target_fields: ``(字段名, 类型)`` 列表（已剔除隐藏字段）。
        existing_mapping: 用户已手工配置的映射（源表头 → 目标字段 / None）。
    """
    lines = [
        "目标表字段（字段名 / 类型）：",
        "、".join(f"{name}({field_type})" for name, field_type in target_fields),
        "源表头：" + "、".join(headers),
    ]
    if existing_mapping:
        known = {source: target for source, target in existing_mapping.items() if target}
        if known:
            lines.append("已确认的映射：" + json.dumps(known, ensure_ascii=False))
    lines.append("抽样数据（每行与前表头一一对应）：")
    for row in sample_rows:
        values = [_cell_text(value) for value in row[: len(headers)]]
        lines.append(json.dumps(values, ensure_ascii=False))
    return "\n".join(lines)


__all__ = [
    "FILL_CONTEXT_FIELDS",
    "FILL_FIELD",
    "MAPPING_SUGGESTION",
    "MAX_CELL_CHARS",
    "MAX_FILL_ROWS",
    "MAX_HEADERS",
    "MAX_SAMPLE_COLS",
    "MAX_SAMPLE_ROWS",
    "FieldFillOutput",
    "FieldFillValue",
    "MappingItem",
    "MappingSuggestionOutput",
    "build_fill_content",
    "build_mapping_content",
]
