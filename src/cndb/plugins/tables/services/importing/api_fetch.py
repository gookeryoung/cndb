"""API 数据抓取模块（兼容 shim）.

实现已迁到 :mod:`cndb.core.http`（ADR 0020 P0）：大模型插件与数据源 / 导入共用同一份
SSRF 防护、超时、响应体上限与重试退避，避免跨插件反向依赖。本模块只做 re-export，
历史 import（``from cndb.plugins.tables.services.importing.api_fetch import fetch_json``）
保持不变。
"""

from __future__ import annotations

from cndb.core.http import *  # noqa: F403 - 兼容历史 import
from cndb.core.http import ResponseHandler
from cndb.core.http import __all__ as _CORE_ALL

__all__ = list(_CORE_ALL)
__all__ += ["ResponseHandler"]
