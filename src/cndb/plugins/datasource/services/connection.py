"""个人「大模型连接」读取（兼容 shim）.

实现已迁到 :mod:`cndb.plugins.llm.services.connection`（ADR 0020 P0）；本模块只做 re-export，
历史 import（数据源 runner / 测试）保持不变。新代码请直接 import ``cndb.plugins.llm.services.connection``。
"""

from __future__ import annotations

from cndb.plugins.llm.services.connection import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LlmConnection,
    find_user_config,
    find_user_llm_config,
    load_connection,
    load_llm_connection,
    resolve_request_spec_defaults,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "LlmConnection",
    "find_user_config",
    "find_user_llm_config",
    "load_connection",
    "load_llm_connection",
    "resolve_request_spec_defaults",
]
