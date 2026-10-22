"""工作区搜索 AI 动作（ADR 0020 P3）：搜索意图改写.

失败口径：调用方（搜索路由）捕获异常并**回退原查询**，保证未配置 Key / 上游故障时
搜索仍可用 —— 因此本动作不向用户抛错，只返回改写结果或由路由兜底。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from cndb.plugins.llm.services.actions import ActionSpec, register

MAX_REWRITTEN_QUERY = 200

REWRITE_SYSTEM_PROMPT = (
    "你是搜索查询改写助手。把用户的口语问题改写成适合站内搜索的简短关键词组合"
    "（保留专有名词，去掉语气词与冗余）。"
    '输出 JSON：{"query": "改写后的关键词"}。不要输出解释。'
)


class RewriteQueryOutput(BaseModel):
    """搜索查询改写结果."""

    query: str = Field(min_length=1, max_length=MAX_REWRITTEN_QUERY)


REWRITE_QUERY = register(
    ActionSpec(
        name="search.rewrite_query",
        label="AI 搜索改写",
        scope="search",
        output_schema=RewriteQueryOutput,
        system_prompt=REWRITE_SYSTEM_PROMPT,
        temperature=0.1,
        max_tokens=300,
        json_mode=True,
        max_input_chars=500,
    )
)


__all__ = ["MAX_REWRITTEN_QUERY", "REWRITE_QUERY", "RewriteQueryOutput"]
