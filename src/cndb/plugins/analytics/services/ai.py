"""数据分析 / 搜索 AI 动作（ADR 0020 P3）.

- ``analytics.suggest_template``：自然语言 → 分析模板配置建议（路由再用
  ``templates.normalize_config`` 校验，不落库）；
- ``analytics.explain``：对统计 / 分组汇总结果生成文字解读（只读）；
- ``search.rewrite_query``：搜索意图改写（失败由调用方回退原查询）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

from cndb.plugins.llm.services.actions import ActionSpec, register

# 解读输入行数上限（只传汇总结果，不传整表）
MAX_EXPLAIN_ROWS = 50
# 搜索改写后查询长度上限
MAX_REWRITTEN_QUERY = 200

SUGGEST_TEMPLATE_SYSTEM_PROMPT = (
    "你是数据分析助手。根据字段画像与用户的自然语言问题，生成一份可执行的分析模板配置。"
    '输出 JSON：{"name": "模板名（≤40 字）", "description": "一句话说明", '
    '"config": {"formulas": [{"key": "英文键", "label": "展示名", "expr": "公式"}], '
    '"chart": {"type": "line/bar/pie/scatter", "x": "字段", "y": "字段", '
    '"series": "字段或 null", "aggregation": "sum/avg/count/min/max"}, '
    '"summary": {"group_by": "字段或 null", "metrics": [{"field": "字段或公式键", '
    '"agg": "sum/avg/count/min/max", "label": "展示名"}], '
    '"sort_by": "字段或指标", "sort_order": "desc", "top_n": 10}, '
    '"fields": ["字段"], "limit": 1000}, "warnings": ["需要用户确认的假设"]}。'
    "只能使用给定字段；公式中的字段引用写作 [字段名]（如 [close] - [open]），只允许四则运算与白名单窗口函数"
    "（prev/lag/lead/diff/pct_change/cumsum/rank/ma/rolling_sum/rolling_std）；"
    "聚合只允许 sum/avg/count/min/max；无法满足的部分放进 warnings，不要编造字段。"
)

EXPLAIN_SYSTEM_PROMPT = (
    "你是数据分析解读助手。根据给定的汇总结果，用中文写 2-4 句结论：指出最重要的趋势 / "
    "差异 / 异常，并说明解读时需要注意的口径限制。"
    '输出 JSON：{"insight": "结论文本（≤400 字）", "caveats": ["口径提醒"]}。'
    "只依据给定数据，不要编造未提供的数字。"
)


class TemplateSuggestionOutput(BaseModel):
    """分析模板建议（config 由路由用 ``normalize_config`` 二次校验）."""

    name: str = Field(default="AI 生成的分析", max_length=200)
    description: str = Field(default="", max_length=500)
    config: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list, max_length=5)


class ExplainOutput(BaseModel):
    """分析结论解读."""

    insight: str = Field(default="", max_length=800)
    caveats: list[str] = Field(default_factory=list, max_length=5)


SUGGEST_TEMPLATE = register(
    ActionSpec(
        name="analytics.suggest_template",
        label="AI 生成分析模板",
        scope="analytics",
        output_schema=TemplateSuggestionOutput,
        system_prompt=SUGGEST_TEMPLATE_SYSTEM_PROMPT,
        temperature=0.2,
        max_tokens=2000,
        json_mode=True,
        max_input_chars=16000,
    )
)

EXPLAIN = register(
    ActionSpec(
        name="analytics.explain",
        label="AI 结论解读",
        scope="analytics",
        output_schema=ExplainOutput,
        system_prompt=EXPLAIN_SYSTEM_PROMPT,
        temperature=0.3,
        max_tokens=1200,
        json_mode=True,
        max_input_chars=12000,
    )
)

# 公式 / 聚合白名单（与公式引擎保持一致；提示词与路由校验共用）
ALLOWED_AGGREGATIONS = ("sum", "avg", "count", "min", "max")
ALLOWED_WINDOW_FUNCTIONS = (
    "prev",
    "lag",
    "lead",
    "diff",
    "pct_change",
    "cumsum",
    "rank",
    "ma",
    "rolling_sum",
    "rolling_std",
)


def build_template_content(
    question: str,
    table_name: str,
    profiles: Sequence[Mapping[str, Any]],
) -> str:
    """构造 ``analytics.suggest_template`` 的用户消息（字段画像，不含整表数据）."""
    compact = [
        {
            "name": item.get("name"),
            "type": item.get("field_type") or item.get("type"),
            "role": item.get("role"),
            "cardinality": item.get("cardinality"),
            "non_null_rate": item.get("non_null_rate"),
            "sample_values": (item.get("sample_values") or [])[:5],
        }
        for item in profiles
    ]
    return "\n".join(
        [
            f"数据表：{table_name}",
            f"用户问题：{question.strip()}",
            f"允许的聚合：{', '.join(ALLOWED_AGGREGATIONS)}",
            f"允许的窗口函数：{', '.join(ALLOWED_WINDOW_FUNCTIONS)}",
            "字段画像（JSON）：",
            json.dumps(compact, ensure_ascii=False),
        ]
    )


def build_explain_content(
    summary_rows: Sequence[Mapping[str, Any]],
    *,
    chart_type: str | None = None,
    template_name: str | None = None,
) -> str:
    """构造 ``analytics.explain`` 的用户消息（汇总行 ≤ ``MAX_EXPLAIN_ROWS``）."""
    lines = []
    if template_name:
        lines.append(f"分析模板：{template_name}")
    if chart_type:
        lines.append(f"图表类型：{chart_type}")
    lines.append("汇总结果（JSON）：")
    lines.append(json.dumps(list(summary_rows)[:MAX_EXPLAIN_ROWS], ensure_ascii=False, default=str))
    return "\n".join(lines)


__all__ = [
    "ALLOWED_AGGREGATIONS",
    "ALLOWED_WINDOW_FUNCTIONS",
    "EXPLAIN",
    "MAX_EXPLAIN_ROWS",
    "SUGGEST_TEMPLATE",
    "ExplainOutput",
    "TemplateSuggestionOutput",
    "build_explain_content",
    "build_template_content",
]
