"""扩展检索式构造与两次判断的应用（ADR 0085 §2 / D5 / D14）.

三段链路：

1. :func:`build` 把最终关键词拼成 ``(base) AND (kw1 OR kw2 …)``（≤5 词，与上轮相同则回退 base）；
2. :func:`apply_llm_decisions` 应用模型的**第二次判断**：keep / drop / rename / weight，
   **候选集之外的新增词一律丢弃**（进 ``rejected``，留痕可审计）；
3. :func:`apply_user_edit` 应用用户调整：新词 ``source="user"``，删词记 ``dropped``。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "KEYWORD_SOURCE_LLM",
    "KEYWORD_SOURCE_TF",
    "KEYWORD_SOURCE_USER",
    "apply_llm_decisions",
    "apply_user_edit",
    "build",
]

KEYWORD_SOURCE_TF = "tf"
KEYWORD_SOURCE_LLM = "llm"
KEYWORD_SOURCE_USER = "user"

#: 单条检索式最多拼入的扩展词数（防止检索式过长被源站拒绝）
MAX_TERMS = 5


def _wrap(term: str) -> str:
    """含空格 / 连字符的短语加引号，其余原样."""
    text = str(term).strip()
    return f'"{text}"' if (" " in text or "-" in text) else text


def build(
    base_query: str,
    keywords: Sequence[Mapping[str, Any]],
    used: set[str] | Sequence[str] = (),
    previous: str = "",
    *,
    max_terms: int = MAX_TERMS,
) -> str:
    """构造扩展检索式；无可扩展词 / 与上轮相同则回退基础检索式."""
    base = str(base_query or "").strip()
    if not base:
        return ""
    used_set = {str(term).strip().lower() for term in used}
    base_lower = base.lower()

    picked: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        term = str(keyword.get("term") or "").strip()
        if not term:
            continue
        lowered = term.lower()
        if len(lowered) < 2 or lowered in seen or lowered in used_set or lowered in base_lower:
            continue
        seen.add(lowered)
        picked.append(term)
        if len(picked) >= max(1, max_terms):
            break

    if not picked:
        return base
    expanded = f"({_wrap(base)}) AND ({' OR '.join(_wrap(term) for term in picked)})"
    return base if expanded == previous.strip() else expanded


def apply_llm_decisions(
    candidates: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """应用模型判定，返回 ``(final_keywords, rejected)``.

    - ``candidates`` 之外出现的 ``term`` → ``rejected``（模型不得凭空造词）；
    - ``action="drop"`` 剔除该词（记 ``dropped=True`` 便于轮次留痕）；
    - ``rename`` 只能指向候选集内的词或基础词之外的同义变体，重名时保留首个；
    - ``weight`` 只影响排序，不改变集合。
    """
    by_term = {str(item.get("term") or "").strip().lower(): dict(item) for item in candidates}
    decided: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []

    for decision in decisions:
        raw_term = str(decision.get("term") or "").strip()
        lowered = raw_term.lower()
        candidate = by_term.get(lowered)
        if candidate is None:
            rejected.append({"term": raw_term, "reason": "候选集之外的词"})
            continue
        action = str(decision.get("action") or "keep").strip().lower()
        entry = {
            "term": str(decision.get("rename") or candidate.get("term") or raw_term).strip(),
            "count": int(candidate.get("count") or 0),
            "df": int(candidate.get("df") or 0),
            "source": KEYWORD_SOURCE_LLM,
            "reason": str(decision.get("reason") or "")[:60],
            "dropped": action == "drop",
            "original_term": candidate.get("term") if decision.get("rename") else None,
        }
        weight = decision.get("weight")
        if isinstance(weight, (int, float)):
            entry["weight"] = round(float(weight), 3)
        decided[lowered] = entry

    final: list[dict[str, Any]] = []
    for candidate in candidates:
        lowered = str(candidate.get("term") or "").strip().lower()
        entry = decided.get(lowered)
        if entry is None:
            final.append(
                {
                    "term": candidate.get("term"),
                    "count": int(candidate.get("count") or 0),
                    "df": int(candidate.get("df") or 0),
                    "source": KEYWORD_SOURCE_TF,
                    "dropped": False,
                }
            )
            continue
        final.append(entry)

    final.sort(key=lambda item: (-float(item.get("weight") or 0), -int(item.get("count") or 0), str(item["term"])))
    return final, rejected


def apply_user_edit(
    keywords: Sequence[Mapping[str, Any]],
    terms: Sequence[str],
) -> list[dict[str, Any]]:
    """应用用户调整：以 ``terms`` 为最终词集，保留已有统计，新词标 ``source="user"``."""
    wanted = [str(term).strip() for term in terms if str(term).strip()]
    if not wanted:
        return [dict(item) for item in keywords]
    existing = {str(item.get("term") or "").strip().lower(): dict(item) for item in keywords}
    final: list[dict[str, Any]] = []
    for term in wanted:
        lowered = term.lower()
        entry = existing.get(lowered)
        if entry is None:
            entry = {"term": term, "count": 0, "df": 0, "source": KEYWORD_SOURCE_USER}
        else:
            entry["source"] = KEYWORD_SOURCE_USER
        entry["dropped"] = False
        final.append(entry)
    for lowered, entry in existing.items():
        if lowered not in {term.lower() for term in wanted}:
            entry["dropped"] = True
            final.append(entry)
    return final
