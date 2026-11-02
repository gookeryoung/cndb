"""语义辅助薄适配层：只做「构造输入 → 网关调用 → 输出校验 → 降级」（ADR 0085 §5 / L1-L9）.

本期（P1）实现 ``acquisition.keyword_refine``（扩展词第二次判断）。
调用约束：

- 只经 ``llm.services.gateway.invoke``（L1），凭据只用个人连接（L2）；
- 输入上限 4000 字、候选 ≤40 词（L9 / L4）；
- 输出结构化校验，候选集外词由 ``rules.expand`` 丢弃（L6）；
- 任何 ``LlmError`` 均降级为「用确定性候选」，**不让采集失败**（L5）。

P3 补齐其余四个动作（同一边界，见 ADR 0085 §5 / D9）：

- ``acquisition.rule_draft``（A）：自然语言 → 规则草案，**只回草案不落策略**，渠道 / 表 / 文件夹按白名单收窄；
- ``acquisition.item_summary``（C）：文档落点写正文前的摘要 / 标签 / 分类，**只作为 ``create_document`` 入参**；
- ``acquisition.run_report``（D）：运行收尾文案，失败降级为空串（结构化统计仍在 ``run``）；
- ``acquisition.failure_diagnose``（E）：只读诊断，失败降级为规则化文案（按「抓取 → 去重 → 筛选」三段定位）。
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

__all__ = [
    "ACTION_FAILURE_DIAGNOSE",
    "ACTION_ITEM_SUMMARY",
    "ACTION_KEYWORD_REFINE",
    "ACTION_RULE_DRAFT",
    "ACTION_RUN_REPORT",
    "DEFAULT_MAX_SUMMARIES",
    "ItemSummary",
    "KeywordDecision",
    "KeywordDecisions",
    "RuleDraft",
    "diagnose_run",
    "draft_rules",
    "refine_keywords",
    "sanitize_rule_draft",
    "summarize_item",
    "write_run_report",
]

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


# ── P3：其余四个语义辅助动作 ──────────────────────

ACTION_RULE_DRAFT = "acquisition.rule_draft"
ACTION_ITEM_SUMMARY = "acquisition.item_summary"
ACTION_RUN_REPORT = "acquisition.run_report"
ACTION_FAILURE_DIAGNOSE = "acquisition.failure_diagnose"

#: 自然语言需求的送模上限（L9：只送需求文本 + 字段名，不送行数据）
MAX_DESCRIPTION_CHARS = 4000
#: 单条候选送模上限（L9）
MAX_ITEM_CHARS = 3000
#: 运行报告 / 诊断文案的输出上限
MAX_REPORT_CHARS = 800
MAX_DIAGNOSE_CHARS = 600
#: 文档落点单次运行内最多摘要多少条（防模型成本失控）
DEFAULT_MAX_SUMMARIES = 20
MAX_SUMMARY_TAGS = 8

_RULE_DRAFT_PROMPT = """你是采集规则翻译器，把用户的自然语言需求翻译成结构化的采集规则草案。

可用字段：
- scope.channels：只能从给定的候选渠道里挑，最多 8 个；
- scope.query：检索式，可含 {today}、{topic} 占位符；
- scope.max_results_per_channel：10-200；
- filter_rule：must_have_keywords / optional_keywords / exclude_keywords（字符串数组）、
  authors / institutions / categories / document_types（字符串数组）、
  date_from / date_to（YYYY-MM-DD）、min_citations（整数）、require_fulltext（布尔）、
  query_boolean（AND / OR / NOT / 括号的布尔式，可含引号短语）；
- targets：只能从给定的表 id / 文件夹 id 里挑，table 用 {"kind":"table","table_id":N,"match_keys":[...]}，
  document 用 {"kind":"document","parent_id":N 或 null}；
- iteration：max_rounds（1-5）、expand.review（auto / llm / manual）、budget.max_requests（≤1000）。

硬性要求：
1. 不得编造渠道、表 id、文件夹 id；候选里没有就不填。
2. 不得输出任何 API Key、账号、邮箱、URL 凭据。
3. 需求描述里没提到的筛选维度不要臆造；宁可留空。
4. notes 用不超过 120 字说明「哪些是你猜的、需要用户确认」。
5. 只返回 JSON，不要 Markdown 代码围栏。"""

_ITEM_SUMMARY_PROMPT = """你是资料摘要员。阅读单条采集候选的标题与正文摘要，输出 JSON：
{"summary": "不超过 200 字的中文摘要", "tags": ["3-8 个 2-8 字主题标签"], "category": "不超过 16 字的分类"}。
只依据给定文本，不得编造事实、URL、数字或结论；文本不足以摘要时 summary 用空串、tags 用空数组。"""

_RUN_REPORT_PROMPT = """你是采集运行报告撰写员。根据给定的结构化统计与每轮检索式，写一段不超过 500 字的中文报告：
说明这轮采到了什么、命中率如何、扩展词是否有效、有没有该调整的地方。
只能引用给定数字，不得编造；不要标题、不要 Markdown 代码围栏。"""

_DIAGNOSE_PROMPT = """你是采集失败诊断员。根据给定的渠道错误、抓取 / 去重 / 筛选计数与检索式，用不超过 400 字说明：
最可能的原因是什么、证据是哪几个数字、建议用户改哪一处（渠道 / 检索式 / 筛选条件）。
只引用给定数据，不得编造；不要标题、不要 Markdown 代码围栏。"""


class RuleDraft(BaseModel):
    """规则草案（模型输出；字典段在服务端按白名单二次收窄）."""

    scope: dict[str, Any] = Field(default_factory=dict)
    filter_rule: dict[str, Any] = Field(default_factory=dict)
    targets: list[dict[str, Any]] = Field(default_factory=list)
    iteration: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=200)


class ItemSummary(BaseModel):
    """单条候选摘要（文档落点写正文前用）."""

    summary: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list)
    category: str = Field(default="", max_length=32)


ACTION_RULE_DRAFT_SPEC = register(
    ActionSpec(
        name=ACTION_RULE_DRAFT,
        label="采集规则草案生成",
        scope="acquisition",
        output_schema=RuleDraft,
        system_prompt=_RULE_DRAFT_PROMPT,
        temperature=0.2,
        max_tokens=1600,
        json_mode=True,
        max_input_chars=MAX_DESCRIPTION_CHARS,
    )
)

ACTION_ITEM_SUMMARY_SPEC = register(
    ActionSpec(
        name=ACTION_ITEM_SUMMARY,
        label="采集条目摘要",
        scope="acquisition",
        output_schema=ItemSummary,
        system_prompt=_ITEM_SUMMARY_PROMPT,
        temperature=0.2,
        max_tokens=600,
        json_mode=True,
        max_input_chars=MAX_ITEM_CHARS,
    )
)

ACTION_RUN_REPORT_SPEC = register(
    ActionSpec(
        name=ACTION_RUN_REPORT,
        label="采集运行报告",
        scope="acquisition",
        temperature=0.3,
        max_tokens=900,
        max_input_chars=6000,
    )
)

ACTION_FAILURE_DIAGNOSE_SPEC = register(
    ActionSpec(
        name=ACTION_FAILURE_DIAGNOSE,
        label="采集失败诊断",
        scope="acquisition",
        temperature=0.1,
        max_tokens=700,
        max_input_chars=6000,
    )
)


def _clamp_int(value: Any, *, low: int, high: int) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(low, min(high, number))


def _str_list(value: Any, *, limit: int, max_len: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for entry in value:
        text = str(entry).strip()[:max_len]
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def sanitize_rule_draft(
    raw: Mapping[str, Any],
    *,
    allowed_channels: Sequence[str],
    allowed_table_ids: Sequence[int],
    allowed_folder_ids: Sequence[int],
) -> dict[str, Any]:
    """把模型草案按白名单收窄（L6）：渠道 / 表 / 文件夹越界一律丢弃，数字夹到合法区间."""
    scope_raw = dict(raw.get("scope") or {})
    allowed = set(allowed_channels)
    channels = [item for item in _str_list(scope_raw.get("channels"), limit=8, max_len=200) if item in allowed]
    scope: dict[str, Any] = {"channels": channels}
    query = str(scope_raw.get("query") or "").strip()[:500]
    if query:
        scope["query"] = query
    max_items = _clamp_int(scope_raw.get("max_results_per_channel"), low=10, high=200)
    if max_items is not None:
        scope["max_results_per_channel"] = max_items

    filter_raw = dict(raw.get("filter_rule") or {})
    filter_rule: dict[str, Any] = {}
    for key, limit, max_len in (
        ("must_have_keywords", 20, 40),
        ("optional_keywords", 20, 40),
        ("exclude_keywords", 20, 40),
        ("authors", 20, 60),
        ("institutions", 20, 60),
        ("categories", 20, 60),
        ("document_types", 10, 40),
    ):
        values = _str_list(filter_raw.get(key), limit=limit, max_len=max_len)
        if values:
            filter_rule[key] = values
    for key in ("date_from", "date_to"):
        text = str(filter_raw.get(key) or "").strip()[:10]
        if text:
            filter_rule[key] = text
    min_citations = _clamp_int(filter_raw.get("min_citations"), low=0, high=1_000_000)
    if min_citations is not None:
        filter_rule["min_citations"] = min_citations
    if filter_raw.get("require_fulltext") is True:
        filter_rule["require_fulltext"] = True
    boolean = str(filter_raw.get("query_boolean") or "").strip()[:500]
    if boolean:
        filter_rule["query_boolean"] = boolean

    table_ids = set(allowed_table_ids)
    folder_ids = set(allowed_folder_ids)
    targets: list[dict[str, Any]] = []
    for entry in list(raw.get("targets") or [])[:10]:
        if not isinstance(entry, Mapping):
            continue
        kind = str(entry.get("kind") or "")
        if kind == "table":
            table_id = _clamp_int(entry.get("table_id"), low=1, high=10**9)
            if table_id is None or table_id not in table_ids:
                continue
            keys = _str_list(entry.get("match_keys"), limit=5, max_len=64)
            targets.append({"kind": "table", "table_id": table_id, "match_keys": keys})
        elif kind == "document":
            folder_id = _clamp_int(entry.get("parent_id"), low=1, high=10**9)
            if folder_id is not None and folder_id not in folder_ids:
                continue
            targets.append({"kind": "document", "parent_id": folder_id})

    iteration_raw = dict(raw.get("iteration") or {})
    iteration: dict[str, Any] = {}
    rounds = _clamp_int(iteration_raw.get("max_rounds"), low=1, high=5)
    if rounds is not None:
        iteration["max_rounds"] = rounds
    expand = iteration_raw.get("expand")
    if isinstance(expand, Mapping):
        review = str(expand.get("review") or "").strip()
        if review in ("auto", "llm", "manual"):
            iteration["expand"] = {"review": review}
    budget = iteration_raw.get("budget")
    if isinstance(budget, Mapping):
        requests = _clamp_int(budget.get("max_requests"), low=1, high=1000)
        if requests is not None:
            iteration["budget"] = {"max_requests": requests}

    return {
        "scope": scope,
        "filter_rule": filter_rule,
        "targets": targets,
        "iteration": iteration,
        "notes": str(raw.get("notes") or "")[:200],
    }


def draft_rules(
    db: Session,
    user: Any,
    *,
    description: str,
    allowed_channels: Sequence[str],
    allowed_table_ids: Sequence[int],
    allowed_folder_ids: Sequence[int],
    context_lines: Sequence[str] = (),
    workspace_id: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """自然语言需求 → 规则草案（**只返回草案，不落策略**，A 动作）.

    失败 / 未配置 → 返回空草案骨架（``meta.degraded`` 说明原因），前端提示手填。
    """
    empty: dict[str, Any] = {
        "scope": {"channels": list[str]()},
        "filter_rule": {},
        "targets": [],
        "iteration": {},
        "notes": "",
    }
    if user is None:
        return empty, {"degraded": "no_user"}
    text = str(description or "").strip()
    if not text:
        return empty, {"degraded": "empty_description"}

    body = {
        "requirement": text[:MAX_DESCRIPTION_CHARS],
        "candidate_channels": [str(item)[:200] for item in allowed_channels][:40],
        "candidate_tables": [str(item)[:200] for item in context_lines][:40],
        "task": "把需求翻译成采集规则草案；渠道 / 表 / 文件夹只能从候选里挑",
    }
    ctx = LlmContext(workspace_id=workspace_id, target_type="acquisition_rule_draft")
    try:
        result = invoke(
            db, user, ACTION_RULE_DRAFT_SPEC, user_content=json.dumps(body, ensure_ascii=False), context=ctx
        )
    except LlmError as exc:
        return empty, {"degraded": type(exc).__name__, "error": str(exc)[:200]}

    raw = result.parsed.model_dump() if hasattr(result.parsed, "model_dump") else dict(result.parsed or {})
    draft = sanitize_rule_draft(
        raw,
        allowed_channels=allowed_channels,
        allowed_table_ids=allowed_table_ids,
        allowed_folder_ids=allowed_folder_ids,
    )
    return draft, {
        "model": result.model,
        "run_id": result.run_id,
        "tokens": result.usage.get("total_tokens", 0),
        "degraded": "",
    }


def _item_text(item: Mapping[str, Any]) -> dict[str, str]:
    """单条候选的送模文本（标题 + 摘要 / 正文，≤3000 字，L9）."""
    title = str(item.get("title") or item.get("name") or "")[:300]
    body = str(item.get("summary") or item.get("content") or item.get("description") or "")[
        : MAX_ITEM_CHARS - len(title)
    ]
    return {"title": title, "content": body}


def summarize_item(
    db: Session,
    user: Any,
    *,
    item: Mapping[str, Any],
    workspace_id: int | None = None,
    strategy_id: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """单条候选 → 摘要 / 标签 / 分类；失败降级为原文摘要 + 空标签（C 动作）."""
    fallback: dict[str, Any] = {
        "summary": str(item.get("summary") or "")[:500],
        "tags": list[str](),
        "category": "",
    }
    if user is None:
        return fallback, {"degraded": "no_user"}
    payload = _item_text(item)
    if not payload["title"] and not payload["content"]:
        return fallback, {"degraded": "empty_item"}

    ctx = LlmContext(workspace_id=workspace_id, target_type="acquisition_strategy", target_id=strategy_id)
    try:
        result = invoke(
            db, user, ACTION_ITEM_SUMMARY_SPEC, user_content=json.dumps(payload, ensure_ascii=False), context=ctx
        )
    except LlmError as exc:
        return fallback, {"degraded": type(exc).__name__, "error": str(exc)[:200]}

    parsed = result.parsed
    tags = _str_list(list(parsed.tags), limit=MAX_SUMMARY_TAGS, max_len=16)
    return (
        {
            "summary": str(parsed.summary or "")[:500] or fallback["summary"],
            "tags": tags,
            "category": str(parsed.category or "")[:32],
        },
        {"model": result.model, "run_id": result.run_id, "tokens": result.usage.get("total_tokens", 0)},
    )


def _run_stats(run: Any) -> dict[str, Any]:
    """运行统计（送模只用数字，不带原始数据，L9）."""
    return {
        "status": str(getattr(run, "status", "")),
        "rounds": int(getattr(run, "round_count", 0) or 0),
        "fetched": int(getattr(run, "fetched", 0) or 0),
        "inserted": int(getattr(run, "inserted", 0) or 0),
        "updated": int(getattr(run, "updated", 0) or 0),
        "skipped": int(getattr(run, "skipped", 0) or 0),
        "docs_created": int(getattr(run, "docs_created", 0) or 0),
        "docs_updated": int(getattr(run, "docs_updated", 0) or 0),
        "budget_used": dict(getattr(run, "budget_used", {}) or {}),
        "errors": list((getattr(run, "detail", {}) or {}).get("channels") or [])[:8],
    }


def write_run_report(
    db: Session,
    user: Any,
    *,
    run: Any,
    rounds: Sequence[Mapping[str, Any]] = (),
    workspace_id: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """运行收尾报告（D 动作）：失败降级为空串，结构化统计已在上层保留."""
    if user is None:
        return "", {"degraded": "no_user"}
    body = {
        "stats": _run_stats(run),
        "rounds": [
            {
                "round_no": int(row.get("round_no") or 0),
                "query": str(row.get("query") or "")[:200],
                "new_items": int(row.get("new_items") or 0),
                "stop_reason": str(row.get("stop_reason") or ""),
                "keywords": [str(item.get("term") or "")[:40] for item in list(row.get("top_keywords") or [])][:8],
            }
            for row in list(rounds)[:5]
        ],
    }
    ctx = LlmContext(workspace_id=workspace_id, target_type="acquisition_run", target_id=getattr(run, "id", None))
    try:
        result = invoke(
            db, user, ACTION_RUN_REPORT_SPEC, user_content=json.dumps(body, ensure_ascii=False), context=ctx
        )
    except LlmError as exc:
        return "", {"degraded": type(exc).__name__, "error": str(exc)[:200]}
    return result.content.strip()[:MAX_REPORT_CHARS], {
        "model": result.model,
        "run_id": result.run_id,
        "tokens": result.usage.get("total_tokens", 0),
    }


def _rule_based_diagnosis(run: Any, rounds: Sequence[Mapping[str, Any]]) -> str:
    """确定性诊断（模型不可用时的兜底文案）：按「抓取 → 去重 → 筛选」三段定位."""
    fetched = int(getattr(run, "fetched", 0) or 0)
    inserted = int(getattr(run, "inserted", 0) or 0) + int(getattr(run, "updated", 0) or 0)
    errors = list((getattr(run, "detail", {}) or {}).get("channels") or [])
    if fetched == 0:
        if errors:
            names = "、".join(str(item.get("channel") or "?") for item in errors[:3])
            return f"本轮没有抓到任何数据，渠道 {names} 报错。请先检查渠道地址 / 鉴权，或改用其它渠道后预览确认。"
        return "本轮没有抓到任何数据，且渠道未报错：多为检索式过窄或时间窗内无新内容。建议放宽检索式或扩大时间窗。"
    if inserted == 0:
        first: dict[str, Any] = dict(rounds[0]) if rounds else {}
        stats: dict[str, Any] = dict(first.get("stats") or {})
        after_dedup = int(stats.get("after_dedup") or 0)
        after_filter = int(stats.get("after_filter") or 0)
        if after_dedup == 0:
            return (
                "抓到了数据但全部被判定为已采过（跨运行台账去重）。属正常收敛；如需重新导入，请调整检索式或清理台账。"
            )
        if after_filter == 0:
            return (
                f"抓取 {fetched} 条、去重后 {after_dedup} 条，但筛选后为 0：筛选条件过严。"
                "建议把「必须包含」改成「可选包含」，或删除冷门排除词后重新预览。"
            )
        return f"抓取 {fetched} 条，筛选后 {after_filter} 条，但落点写入 0：请检查目标表字段映射与文档文件夹是否存在。"
    return f"本次运行写入 {inserted} 条，未见异常。若结果偏少，可提高 max_rounds 或放宽筛选条件。"


def diagnose_run(
    db: Session,
    user: Any,
    *,
    run: Any,
    rounds: Sequence[Mapping[str, Any]] = (),
    workspace_id: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """失败诊断（E 动作，只读）；模型不可用 → 规则化诊断文案."""
    fallback = _rule_based_diagnosis(run, rounds)
    if user is None:
        return fallback, {"degraded": "no_user"}
    body = {
        "stats": _run_stats(run),
        "error_message": str(getattr(run, "error_message", "") or "")[:400],
        "rounds": [
            {
                "round_no": int(row.get("round_no") or 0),
                "query": str(row.get("query") or "")[:200],
                "stats": dict(row.get("stats") or {}),
                "stop_reason": str(row.get("stop_reason") or ""),
            }
            for row in list(rounds)[:5]
        ],
        "task": "判断为什么这轮没结果 / 结果太少，并给出最该改的一处",
    }
    ctx = LlmContext(workspace_id=workspace_id, target_type="acquisition_run", target_id=getattr(run, "id", None))
    try:
        result = invoke(
            db, user, ACTION_FAILURE_DIAGNOSE_SPEC, user_content=json.dumps(body, ensure_ascii=False), context=ctx
        )
    except LlmError as exc:
        return fallback, {"degraded": type(exc).__name__, "error": str(exc)[:200]}
    return result.content.strip()[:MAX_DIAGNOSE_CHARS], {
        "model": result.model,
        "run_id": result.run_id,
        "tokens": result.usage.get("total_tokens", 0),
    }
