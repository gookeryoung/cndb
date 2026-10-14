"""Jinja2 安全沙箱环境。

SandboxedEnvironment 默认禁用 __import__/open/exec/eval 等内置；此处再额外收紧：
过滤器仅保留白名单、globals 中的危险内置置空，并注册模板可调用的统计函数。"""

from __future__ import annotations

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from cndb.plugins.reports.services.stats import _group_stats, _stats

# ── Jinja2 安全沙箱 ──────────────────────────────────
# SandboxedEnvironment 默认禁用 __import__/open/exec/eval 等内置，
# 再额外收紧：移除 unsafe 过滤器 + 限制可用内置
_jinja_env = SandboxedEnvironment(
    undefined=StrictUndefined,
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)

# 白名单过滤器（SandboxedEnvironment 已内置大部分，这里确认）
_ALLOWED_FILTERS = {
    "length",
    "sort",
    "reverse",
    "join",
    "trim",
    "upper",
    "lower",
    "default",
    "first",
    "last",
    "dictsort",
    "unique",
    "select",
    "reject",
    "selectattr",
    "rejectattr",
    "map",
    "sum",
    "abs",
    "round",
    "int",
    "float",
    "string",
    "list",
    "title",
    "capitalize",
    "replace",
    "striptags",
    "wordcount",
    "indent",
    "format",
}

# 清理掉所有不安全过滤器，只保留白名单
_jinja_env.filters = {k: v for k, v in _jinja_env.filters.items() if k in _ALLOWED_FILTERS}

# 限制可用内置变量（禁掉 open/exec/eval/compile/__import__ 等）
# SandboxedEnvironment.globals 是 ChainMap，类型检查器可能不认可写操作
_unsafe_builtins = ("open", "exec", "eval", "compile", "__import__", "input", "print", "breakpoint", "exit", "quit")
for _name in _unsafe_builtins:
    _jinja_env.globals.__setitem__(_name, None)  # type: ignore[unsupported-operation]


_jinja_env.globals.__setitem__("stats", _stats)  # type: ignore[unsupported-operation]
_jinja_env.globals.__setitem__("group_stats", _group_stats)  # type: ignore[unsupported-operation]
