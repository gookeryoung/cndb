"""大模型调用错误分类（ADR 0020 P0）.

路由层按 ``status_code`` 映射 HTTP 状态码；错误文案里禁止出现提示词 / 输出全文。
"""

from __future__ import annotations


class LlmError(ValueError):
    """大模型能力层基类（继承 ``ValueError``，兼容既有按 ValueError 捕获的调用方）."""

    status_code: int = 400
    code: str = "llm_error"


class LlmNotConfigured(LlmError):
    """未配置个人连接 / API Key（400）."""

    status_code = 400
    code = "llm_not_configured"


class LlmUpstreamError(LlmError):
    """上游模型接口失败：非 2xx、网络错误、响应形态不符（502）."""

    status_code = 502
    code = "llm_upstream_error"


class LlmRateLimited(LlmUpstreamError):
    """上游限流（重试后仍 429，429）."""

    status_code = 429
    code = "llm_rate_limited"


class LlmOutputInvalid(LlmError):
    """模型输出不可解析 / 不符合 schema（422，零副作用）."""

    status_code = 422
    code = "llm_output_invalid"


__all__ = [
    "LlmError",
    "LlmNotConfigured",
    "LlmOutputInvalid",
    "LlmRateLimited",
    "LlmUpstreamError",
]
