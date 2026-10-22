"""OpenAI 兼容模型客户端（ADR 0020 P0）.

唯一出口：所有大模型 HTTP 调用都必须经本模块（网关 / 数据源 provider / 连通测试）。
底层复用 :mod:`cndb.core.http` 的 ``fetch_json``（SSRF 防护 / 超时 / 响应体上限），
在其上补三件 LLM 专属语义：

- **有限重试**：429 / 500 / 502 / 503 / 504 与超时最多重试 ``MAX_RETRIES`` 次
  （指数退避，``Retry-After`` 优先；4xx 不重试）；
- **内网白名单**：``settings.LLM_PRIVATE_HOST_ALLOWLIST`` 中的主机放行（默认空 = 严格拦截）；
- **统一错误分类**：上游失败 → :class:`LlmUpstreamError`，限流 → :class:`LlmRateLimited`。

提示词模板求值不在这里（P1 由领域动作负责），本模块只发已构造好的 messages。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from cndb.core.config import settings
from cndb.core.http import DEFAULT_TIMEOUT, FetchConfig, fetch_json
from cndb.plugins.llm.services.connection import LlmConnection
from cndb.plugins.llm.services.errors import (
    LlmError,
    LlmNotConfigured,
    LlmRateLimited,
    LlmUpstreamError,
)
from cndb.plugins.llm.services.parsing import parse_envelope
from cndb.plugins.llm.services.prompts import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    JSON_INSTRUCTION,
    TEST_MAX_TOKENS,
    TEST_PROMPT,
)

# 可重试的上游状态码（LLM 端点最常见失败是限流与瞬时 5xx）
RETRYABLE_STATUS: tuple[int, ...] = (429, 500, 502, 503, 504)
MAX_RETRIES = 2

# 与 datasource ``FetchFn`` 等价的签名（此处不 import 领域插件，保持依赖单向）
FetchFn = Callable[[FetchConfig], list[dict[str, Any]]]


@dataclass(slots=True)
class LlmResponse:
    """一次成功的模型调用结果（原始 content + 用量元数据）."""

    content: str
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class LlmConnectionResult:
    """连通测试结果（不落库、不写运行记录）."""

    ok: bool
    latency_ms: int
    model: str = ""
    message: str = ""


def normalize_endpoint(url: str) -> str:
    """把 base_url 归一为 ``.../chat/completions`` 端点；已带路径则原样保留."""
    value = url.strip().rstrip("/")
    if not value:
        raise ValueError("request_spec.url_template 不能为空")
    if not value.startswith(("http://", "https://")):
        raise ValueError("request_spec.url_template 必须是 http/https URL")
    if not value.endswith("/chat/completions"):
        value = f"{value}/chat/completions"
    return value


def _allow_hosts() -> tuple[str, ...]:
    return tuple(str(host).strip() for host in settings.LLM_PRIVATE_HOST_ALLOWLIST if str(host).strip())


def build_headers(connection: LlmConnection) -> dict[str, str]:
    """请求头：缺 API Key 直接报 400（不发请求）."""
    if not connection.api_key.strip():
        raise LlmNotConfigured("未配置 api_key：请先在「个人设置 → 大模型」配置 API Key")
    return {"Content-Type": "application/json", "Authorization": f"Bearer {connection.api_key}"}


def build_chat_body(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


def _map_upstream_error(exc: Exception) -> LlmError:
    text = str(exc)
    if "API 返回 429" in text:
        return LlmRateLimited(text)
    return LlmUpstreamError(text)


def as_fetcher() -> FetchFn:
    """返回给数据源 pipeline 的抓取函数：LLM 请求一路经本模块配置后执行.

    ``plan.fetcher`` 注入后，pipeline 不再直接调 ``fetch_json``；重试 / 白名单 / 错误分类
    统一在这里生效，其它 provider 不受影响。
    """

    def fetch(config: FetchConfig) -> list[dict[str, Any]]:
        overrides: dict[str, Any] = {}
        if not config.retry_on_status:
            overrides["retry_on_status"] = RETRYABLE_STATUS
        if config.max_retries < MAX_RETRIES:
            overrides["max_retries"] = MAX_RETRIES
        if not config.allow_hosts:
            overrides["allow_hosts"] = _allow_hosts()
        active = replace(config, **overrides) if overrides else config
        try:
            return fetch_json(active)
        except LlmError:
            raise
        except ValueError as exc:
            raise _map_upstream_error(exc) from exc

    return fetch


def complete(
    connection: LlmConnection,
    *,
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    json_mode: bool = False,
    timeout: float | None = None,
) -> LlmResponse:
    """调用 OpenAI 兼容 ``/chat/completions`` 并返回原始 content.

    Raises:
        LlmNotConfigured: 未配置 API Key。
        LlmRateLimited: 重试后仍被限流。
        LlmUpstreamError: 上游非 2xx / 网络失败 / 响应形态不符。
        LlmOutputInvalid: 响应 JSON 无法解析（由 :mod:`parsing` 抛出）。
    """
    captured: dict[str, Any] = {}

    def handler(text: str, _config: FetchConfig) -> list[dict[str, Any]]:
        content, metadata = parse_envelope(text)
        captured["content"] = content
        captured["metadata"] = metadata
        return [{"content": content}]

    config = FetchConfig(
        url=normalize_endpoint(connection.base_url),
        method="POST",
        headers=build_headers(connection),
        body=build_chat_body(
            model=model or connection.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        ),
        timeout=timeout or DEFAULT_TIMEOUT,
        max_retries=MAX_RETRIES,
        retry_on_status=RETRYABLE_STATUS,
        allow_hosts=_allow_hosts(),
        response_handler=handler,
    )
    try:
        fetch_json(config)
    except LlmError:
        raise
    except ValueError as exc:
        raise _map_upstream_error(exc) from exc
    metadata: dict[str, Any] = captured.get("metadata") or {}
    raw_usage = metadata.get("usage")
    usage: dict[str, int] = raw_usage if isinstance(raw_usage, dict) else {}
    return LlmResponse(
        content=str(captured.get("content") or ""),
        model=str(metadata.get("model") or model or connection.model),
        usage={str(key): int(value) for key, value in usage.items()},
    )


def test_connection(connection: LlmConnection, *, timeout: float | None = None) -> LlmConnectionResult:
    """发一次最小模型请求验证地址 / Key / 模型；不落库、不写运行记录."""
    started = time.perf_counter()
    if not connection.has_api_key and not connection.api_key.strip():
        return LlmConnectionResult(
            ok=False,
            latency_ms=0,
            model=connection.model,
            message="未配置 api_key：请先在「个人设置 → 大模型」配置 API Key",
        )
    try:
        response = complete(
            connection,
            messages=[
                {"role": "system", "content": JSON_INSTRUCTION},
                {"role": "user", "content": TEST_PROMPT},
            ],
            temperature=0,
            max_tokens=TEST_MAX_TOKENS,
            json_mode=True,
            timeout=timeout,
        )
        latency = int((time.perf_counter() - started) * 1000)
        return LlmConnectionResult(ok=True, latency_ms=latency, model=response.model, message="连通成功")
    except Exception as exc:  # 连通测试把异常转成可展示结果，不向上抛
        latency = int((time.perf_counter() - started) * 1000)
        return LlmConnectionResult(
            ok=False,
            latency_ms=latency,
            model=connection.model,
            message=str(exc)[:500],
        )


__all__ = [
    "MAX_RETRIES",
    "RETRYABLE_STATUS",
    "FetchFn",
    "LlmConnectionResult",
    "LlmResponse",
    "as_fetcher",
    "build_chat_body",
    "build_headers",
    "complete",
    "normalize_endpoint",
    "test_connection",
]
