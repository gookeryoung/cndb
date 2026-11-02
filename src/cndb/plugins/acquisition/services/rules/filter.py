"""筛选规则：三段式关键词 + 硬条件 + 匹配分（ADR 0085 §2，口径对齐 endo ``FilterRule``）.

规则语义（全部为「空则忽略」的可选约束）：

    (布尔表达式命中 或 全部 must_have 命中)
    AND 排除词零命中
    AND (optional 命中任一 或 optional 为空)
    AND (作者 / 机构 / 分类 / 类型 命中任一 或为空)
    AND 日期落在 [date_from, date_to]
    AND 引用数 >= min_citations
    AND (require_fulltext 时必须有全文链接)

通过者按 0–100 分排序（关键词命中、标题命中、引用数、全文、摘要加分），
分数进 ``match_score`` 供落点与前端展示。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from cndb.plugins.acquisition.services.rules.expr import (
    RuleError,
    evaluate_boolean,
    extract_terms,
    parse_boolean_query,
)

__all__ = ["FilterRule", "apply_filters", "candidate_text"]

_SCORE_CAP = 100


def _as_tuple(value: Any) -> tuple[str, ...]:
    """把 JSON 里的字符串 / 数组统一成去空白的字符串元组."""
    if value is None:
        return ()
    if isinstance(value, str):
        items: Sequence[Any] = [value]
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        raise RuleError(f"筛选项必须是字符串或字符串数组: {value!r}")
    return tuple(text for text in (str(item).strip() for item in items) if text)


def _as_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RuleError(f"数值项非法: {value!r}") from exc


def _as_date(value: Any) -> dt.date | None:
    """解析 ISO 日期 / 日期时间的前 10 位；空值返回 ``None``."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def candidate_text(item: Mapping[str, Any]) -> str:
    """用于关键词 / 布尔式匹配的文本.

    文档类候选取「标题 + 摘要 + 正文」；表类候选（归一后的行，没有 title）取全部字符串列，
    保证同一套筛选规则对两种落点都可用。
    """
    parts = [
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
        str(item.get("content") or ""),
    ]
    text = " ".join(part for part in parts if part)
    if text.strip():
        return text
    columns = [
        str(int(value) if isinstance(value, bool) else value)
        for key, value in item.items()
        if isinstance(value, str) and not str(key).startswith("_")
    ]
    return " ".join(columns)


def _join_values(value: Any) -> str:
    """作者 / 机构 / 分类字段可能是字符串数组或 ``[{"name": ...}]``."""
    if not value:
        return ""
    if isinstance(value, str):
        return value.lower()
    parts: list[str] = []
    for entry in value:
        if isinstance(entry, Mapping):
            parts.append(str(entry.get("name") or entry.get("display_name") or ""))
        else:
            parts.append(str(entry))
    return " ".join(parts).lower()


@dataclass(frozen=True, slots=True)
class FilterRule:
    """筛选规则（全部可选；空规则 = 不过滤，全部通过并给基础分）."""

    must_have_keywords: tuple[str, ...] = ()
    optional_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    institutions: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    document_types: tuple[str, ...] = ()
    date_from: str = ""
    date_to: str = ""
    min_citations: int = 0
    require_fulltext: bool = False
    query_boolean: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> FilterRule:
        """JSON → 规则；未知键忽略（便于规则演进不阻塞历史配置）."""
        payload = dict(data or {})
        return cls(
            must_have_keywords=_as_tuple(payload.get("must_have_keywords")),
            optional_keywords=_as_tuple(payload.get("optional_keywords")),
            exclude_keywords=_as_tuple(payload.get("exclude_keywords")),
            authors=_as_tuple(payload.get("authors")),
            institutions=_as_tuple(payload.get("institutions")),
            categories=_as_tuple(payload.get("categories")),
            document_types=_as_tuple(payload.get("document_types")),
            date_from=str(payload.get("date_from") or "").strip(),
            date_to=str(payload.get("date_to") or "").strip(),
            min_citations=_as_int(payload.get("min_citations")),
            require_fulltext=bool(payload.get("require_fulltext")),
            query_boolean=str(payload.get("query_boolean") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "must_have_keywords": list(self.must_have_keywords),
            "optional_keywords": list(self.optional_keywords),
            "exclude_keywords": list(self.exclude_keywords),
            "authors": list(self.authors),
            "institutions": list(self.institutions),
            "categories": list(self.categories),
            "document_types": list(self.document_types),
            "date_from": self.date_from,
            "date_to": self.date_to,
            "min_citations": self.min_citations,
            "require_fulltext": self.require_fulltext,
            "query_boolean": self.query_boolean,
        }

    def validate(self) -> None:
        """保存期预校验：布尔式必须能解析（错误文案直接回前端）."""
        parse_boolean_query(self.query_boolean)
        _as_date(self.date_from)
        _as_date(self.date_to)


@dataclass(slots=True)
class FilterOutcome:
    """一次筛选的结果（通过项 + 统计，便于轮次留痕）."""

    items: list[dict[str, Any]] = field(default_factory=list)
    rejected: int = 0

    @property
    def passed(self) -> int:
        return len(self.items)


def _score(
    item: Mapping[str, Any],
    rule: FilterRule,
    bool_ast: Any,
    optional_hits: int,
) -> int:
    """通过硬条件后的匹配分（0–100）."""
    title = str(item.get("title") or "").lower()
    score = 50
    score += len(rule.must_have_keywords) * 5
    score += optional_hits * 8
    score += sum(5 for keyword in rule.must_have_keywords if keyword.lower() in title)
    if bool_ast is not None:
        score += sum(3 for term in extract_terms(bool_ast) if term.lower() in title)
    citations = _as_int(item.get("citation_count"), 0)
    score += min(citations / 10, 15)
    if item.get("fulltext_url"):
        score += 5
    if item.get("summary"):
        score += 3
    return int(min(score, _SCORE_CAP))


def apply_filters(
    items: Sequence[Mapping[str, Any]],
    rule: FilterRule | None,
) -> FilterOutcome:
    """对候选条目应用筛选规则，返回带 ``match_score`` 的通过项（按分降序）."""
    if rule is None:
        return FilterOutcome(items=[dict(item) for item in items])

    bool_ast = parse_boolean_query(rule.query_boolean)
    outcome = FilterOutcome()
    passed: list[dict[str, Any]] = []

    for item in items:
        text = candidate_text(item)
        lowered = text.lower()

        # 1. 布尔式优先；无布尔式时 must_have 为硬条件，有布尔式时降为加分项
        if bool_ast is not None:
            if not evaluate_boolean(bool_ast, text):
                outcome.rejected += 1
                continue
        elif any(keyword.lower() not in lowered for keyword in rule.must_have_keywords):
            outcome.rejected += 1
            continue

        # 2. 排除词
        if any(keyword.lower() in lowered for keyword in rule.exclude_keywords):
            outcome.rejected += 1
            continue

        # 3. 可选词（为空则忽略）
        optional_hits = sum(1 for keyword in rule.optional_keywords if keyword.lower() in lowered)
        if rule.optional_keywords and optional_hits == 0 and bool_ast is None:
            outcome.rejected += 1
            continue

        # 4. 作者 / 机构
        if rule.authors and not any(author.lower() in _join_values(item.get("authors")) for author in rule.authors):
            outcome.rejected += 1
            continue
        if rule.institutions and not any(
            inst.lower() in _join_values(item.get("affiliations")) for inst in rule.institutions
        ):
            outcome.rejected += 1
            continue

        # 5. 日期范围（解析不出来的日期不拦，避免因源站格式差异整批丢弃）
        published = _as_date(item.get("published_at"))
        if published is not None:
            lower = _as_date(rule.date_from)
            upper = _as_date(rule.date_to)
            if lower is not None and published < lower:
                outcome.rejected += 1
                continue
            if upper is not None and published > upper:
                outcome.rejected += 1
                continue

        # 6. 分类 / 类型
        if rule.categories and not any(cat.lower() in _join_values(item.get("categories")) for cat in rule.categories):
            outcome.rejected += 1
            continue
        if rule.document_types:
            doc_type = str(item.get("document_type") or "").lower()
            if not any(candidate.lower() in doc_type for candidate in rule.document_types):
                outcome.rejected += 1
                continue

        # 7. 引用数 / 全文
        if rule.min_citations > 0 and _as_int(item.get("citation_count"), 0) < rule.min_citations:
            outcome.rejected += 1
            continue
        if rule.require_fulltext and not item.get("fulltext_url"):
            outcome.rejected += 1
            continue

        scored = dict(item)
        scored["match_score"] = _score(item, rule, bool_ast, optional_hits)
        passed.append(scored)

    passed.sort(key=lambda entry: (-int(entry.get("match_score") or 0), str(entry.get("title") or "")))
    outcome.items = passed
    return outcome
