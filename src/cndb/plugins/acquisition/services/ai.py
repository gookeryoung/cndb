"""语义辅助薄适配层：只做「构造输入 → 网关调用 → 输出校验 → 降级」（ADR 0085 §5 / L1-L9）.

本期（P1）实现 ``acquisition.keyword_refine``（扩展词第二次判断）。
调用约束：

- 只经 ``llm.services.gateway.invoke``（L1），凭据只用个人连接（L2）；
- 输入上限 4000 字、候选 ≤40 词（L9 / L4）；
- 输出结构化校验，候选集外词由 ``rules.expand`` 丢弃（L6）；
- 任何 ``LlmError`` 均降级为「用确定性候选」，**不让采集失败**（L5）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cndb.plugins.acquisition.services.rules.expand import (
    KEYWORD_SOURCE_LLM,
    KEYWORD_SOURCE_TF,
    apply_llm_decisions,
)
from cndb.plugins.llm.services.actions import ActionSpec, register
from cndb.plugins.llm.services.errors import LlmError
from cndb.plugins.llm.services.gateway import LlmContext, invoke

__all__ = ["ACTION_KEYWORD_REFINE", "KeywordDecision", "KeywordDecisions", "refine_keywords"]

ACTION_KEYWORD_REFINE = "acquisition.keyword_refine"

#: 候选词上限（送模数量）
MAX_CANDIDATES = 40
#: 单次输入字符上限
MAX_INPUT_CHARS = 4000

_SYSTEM_PROMPT = """你是检索式评审员，只做一件事：对给定的候选扩展词逐条判断去留。

规则：
1. 只能对输入列表中的词做 keep / drop，或给出同义 rename；不得新增不在列表里的词。
2. 泛词、机构名、期刊名、无领域含义的形容词一律 drop；能显著收窄主题的词保留。
3. rename 仅在原词是噪声变体（大小写 / 连字符 / 空格差异）时使用，否则留空。
4. reason 不超过 60 字，说明判断依据（命中哪些语义特征）。
5. 只返回 JSON，不要 Markdown 代码围栏、不要解释段落。"""


class KeywordDecision(BaseModel):
    """单条判定."""

    term: str = Field(default="", max_length=64)
    action: Literal["keep", "drop"] = "keep"
    rename: str | None = Field(default=None, max_length=64)
    weight: float | None = Field(default=None, ge=0, le=10)
    reason: str = Field(default="", max_length=60)


class KeywordDecisions(BaseModel):
    """模型输出（结构化校验的唯一契约）."""

    decisions: list[KeywordDecision] = Field(default_factory=list)
    note: str = Field(default="", max_length=200)


ACTION = register(
    ActionSpec(
        name=ACTION_KEYWORD_REFINE,
        label="采集扩展词复核",
        scope="acquisition",
        output_schema=KeywordDecisions,
        system_prompt=_SYSTEM_PROMPT,
        temperature=0.1,
        max_tokens=1200,
        json_mode=True,
        max_input_chars=MAX_INPUT_CHARS,
    )
)


def _payload(candidates: Sequence[Mapping[str, Any]], base_query: str, used: Sequence[str]) -> str:
    """构造送模输入：候选 + 上下文，控制在字符上限内（L9）."""
    rows = [
        {"term": str(item.get("term") or ""), "count": int(item.get("count") or 0), "df": int(item.get("df") or 0)}
        for item in candidates[:MAX_CANDIDATES]
    ]
    body = {
        "base_query": base_query[:200],
        "already_used": [str(term)[:40] for term in used][:30],
        "candidates": rows,
        "task": "逐条判断候选扩展词是否值得加入下一轮检索式",
    }
    text = json.dumps(body, ensure_ascii=False)
    return text[:MAX_INPUT_CHARS]


def refine_keywords(
    db: Session,
    user: Any,
    *,
    candidates: Sequence[Mapping[str, Any]],
    base_query: str,
    used: Sequence[str] = (),
    workspace_id: int | None = None,
    strategy_id: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """模型第二次判断；返回 ``(final_keywords, rejected, meta)``.

    未配置连接 / 无用户 / 任一 ``LlmError`` → 原样返回确定性候选（``meta.degraded`` 说明原因）。
    """
    fallback = [
        {
            "term": str(item.get("term") or ""),
            "count": int(item.get("count") or 0),
            "df": int(item.get("df") or 0),
            "source": KEYWORD_SOURCE_TF,
            "dropped": False,
        }
        for item in candidates
    ]
    if user is None:
        return fallback, [], {"degraded": "no_user"}
    if not candidates:
        return fallback, [], {"degraded": "no_candidates"}

    context = LlmContext(workspace_id=workspace_id, target_type="acquisition_strategy", target_id=strategy_id)
    try:
        result = invoke(db, user, ACTION, user_content=_payload(candidates, base_query, used), context=context)
    except LlmError as exc:
        return fallback, [], {"degraded": type(exc).__name__, "error": str(exc)[:200]}

    parsed = result.parsed
    decisions = [
        {
            "term": item.term,
            "action": item.action,
            "rename": item.rename,
            "weight": item.weight,
            "reason": item.reason,
        }
        for item in parsed.decisions
    ]
    final, rejected = apply_llm_decisions(candidates, decisions)
    return (
        final,
        rejected,
        {
            "model": result.model,
            "run_id": result.run_id,
            "tokens": result.usage.get("total_tokens", 0),
            "decisions": len(decisions),
            "source": KEYWORD_SOURCE_LLM,
        },
    )
