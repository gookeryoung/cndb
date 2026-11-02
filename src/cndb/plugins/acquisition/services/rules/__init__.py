"""acquisition 规则引擎 —— 表达式 / 筛选打分 / 去重 / 关键词 / 扩展 / 停止（ADR 0085 §2）.

全部为纯函数：不碰 DB、不碰网络，便于表驱动单测与「同一输入同一输出」。
"""

from __future__ import annotations

from cndb.plugins.acquisition.services.rules.dedupe import dedupe_key, normalize_url
from cndb.plugins.acquisition.services.rules.expand import (
    apply_llm_decisions,
    apply_user_edit,
    build,
)
from cndb.plugins.acquisition.services.rules.expr import (
    RuleError,
    evaluate_boolean,
    extract_terms,
    parse_boolean_query,
    render_query,
    substitute_placeholders,
)
from cndb.plugins.acquisition.services.rules.filter import FilterRule, apply_filters
from cndb.plugins.acquisition.services.rules.keywords import extract_keywords
from cndb.plugins.acquisition.services.rules.stop import decide_stop

__all__ = [
    "FilterRule",
    "RuleError",
    "apply_filters",
    "apply_llm_decisions",
    "apply_user_edit",
    "build",
    "decide_stop",
    "dedupe_key",
    "evaluate_boolean",
    "extract_keywords",
    "extract_terms",
    "normalize_url",
    "parse_boolean_query",
    "render_query",
    "substitute_placeholders",
]
