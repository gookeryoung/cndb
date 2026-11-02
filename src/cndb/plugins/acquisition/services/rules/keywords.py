"""扩展词候选抽取（ADR 0085 §2，迭代三段的第一段）.

确定性算法（I4）：词频 + 文档频次 + 停用词 + 最小词长，输出稳定有序的候选集；
模型只能在候选集内做第二次判断（:mod:`expand`），不得新增词。

分词口径（无第三方依赖）：

- 拉丁词：连续字母开头、长度 ≥ ``min_len`` 的 token（保留 ``+`` / ``-`` / ``#``，如 ``solid-state``）；
- 中文：连续汉字串切成**二元组**（``固态电解质`` → ``固态`` / ``态电`` / ``电解`` / ``解质``），
  与检索式里的多字词做子串匹配，够用且不引入分词依赖。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = ["DEFAULT_STOP_WORDS", "extract_keywords", "tokenize"]

_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#\-]{1,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")

DEFAULT_STOP_WORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "are",
        "was",
        "were",
        "have",
        "has",
        "been",
        "based",
        "using",
        "via",
        "into",
        "study",
        "paper",
        "article",
        "review",
        "results",
        "analysis",
        "research",
        "摘要",
        "研究",
        "本文",
        "我们",
        "可以",
        "以及",
        "通过",
        "进行",
        "基于",
        "结果",
        "分析",
    }
)


def tokenize(text: str, *, min_len: int = 3) -> list[str]:
    """把标题 / 摘要切成候选词（拉丁词 + 中文二元组），小写化."""
    lowered = str(text or "").lower()
    tokens = [word for word in _LATIN_RE.findall(lowered) if len(word) >= min_len]
    for run in _CJK_RE.findall(lowered):
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _text_of(item: Mapping[str, Any]) -> str:
    """取可分析的文本：文档类取标题 + 摘要；表类候选（归一后的行）取全部字符串列."""
    parts = [str(item.get("title") or ""), str(item.get("summary") or item.get("content") or "")]
    text = " ".join(part for part in parts if part)
    if text.strip():
        return text
    return " ".join(
        str(value) for key, value in item.items() if isinstance(value, str) and not str(key).startswith("_")
    )


def extract_keywords(
    items: Sequence[Mapping[str, Any]],
    top_n: int = 5,
    *,
    exclude: Sequence[str] = (),
    stop_words: frozenset[str] = DEFAULT_STOP_WORDS,
    min_len: int = 3,
    min_df: int = 1,
) -> list[dict[str, Any]]:
    """抽取候选扩展词：``[{term, count, df}]``，按 ``count`` 降序、词面升序（确定性）."""
    if not items or top_n <= 0:
        return []
    excluded = {str(term).strip().lower() for term in exclude if str(term).strip()}
    counter: Counter[str] = Counter()
    document_freq: Counter[str] = Counter()

    for item in items:
        tokens = [
            token
            for token in tokenize(_text_of(item), min_len=min_len)
            if token not in stop_words and token not in excluded
        ]
        counter.update(tokens)
        document_freq.update(set(tokens))

    ranked = sorted(
        ((term, count) for term, count in counter.items() if document_freq[term] >= min_df),
        key=lambda pair: (-pair[1], pair[0]),
    )
    return [{"term": term, "count": count, "df": document_freq[term]} for term, count in ranked[:top_n]]
