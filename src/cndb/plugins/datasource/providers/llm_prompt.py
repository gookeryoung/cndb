"""内置 provider：``llm_prompt`` —— 用大模型提示词生成数据行（ADR 0014）.

协议限定为 OpenAI 兼容 ``POST {base_url}/chat/completions``：

- 请求：``system`` / ``user_template`` 经 ``render_text`` 求值后组成 messages，
  ``json_mode=true`` 时附带 ``response_format={"type":"json_object"}``；
- 响应：取 ``choices[0].message.content``，去掉 Markdown 代码围栏后解析 JSON；
  对象 → 1 行，对象数组 → N 行，``{"rows": [...]}`` → 取 rows；
- 落表：复用 ``apply_field_mapping`` + 既有 ``upsert_rows``（按 ``match_keys`` 幂等）。

API Key 只从凭证会话的 ``api_key`` 模板变量取，缺失直接报错，不发出请求。
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cndb.plugins.datasource.providers.base import (
    CursorStrategy,
    FetchFn,
    ProviderError,
    RequestPlan,
    RequestSpec,
    SourceProvider,
    SyncJobSpec,
)
from cndb.plugins.datasource.providers.template import render_text
from cndb.plugins.datasource.services.normalize import NormalizeResult, apply_field_mapping
from cndb.plugins.tables.services.importing.api_fetch import (
    DEFAULT_TIMEOUT,
    FetchConfig,
    fetch_json,
)

DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 1024
MAX_TOKENS_LIMIT = 32768
TEST_MAX_TOKENS = 64
TEST_PROMPT = '只返回 JSON：{"ok": true}'
JSON_INSTRUCTION = "只输出 JSON，不要输出 Markdown 代码围栏或解释文字。"

# 供前端动态渲染的表单描述；前端当前按 provider 条件渲染固定字段，此处仍对外暴露
LLM_PROMPT_PARAMS_SCHEMA: dict[str, Any] = {
    "fields": [
        {"name": "url_template", "type": "text", "required": True, "label": "API 地址"},
        {"name": "model", "type": "text", "required": True, "label": "模型"},
        {"name": "system_prompt", "type": "textarea", "label": "系统提示词"},
        {"name": "user_template", "type": "textarea", "required": True, "label": "用户提示词"},
        {"name": "temperature", "type": "number", "default": DEFAULT_TEMPERATURE},
        {"name": "max_tokens", "type": "number", "default": DEFAULT_MAX_TOKENS},
        {"name": "json_mode", "type": "boolean", "default": True},
    ],
    "placeholders": ["entrant", "start", "end", "today"],
}


@dataclass(frozen=True, slots=True)
class LlmConfig:
    """``request_spec`` 中与模型相关的配置（校验后）."""

    url: str
    model: str
    system: str = ""
    user_template: str = ""
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    json_mode: bool = True
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_payload(
        cls,
        *,
        url_template: Any,
        prompt: Mapping[str, Any] | None,
        llm: Mapping[str, Any] | None,
        timeout: Any = None,
    ) -> LlmConfig:
        url = normalize_endpoint(str(url_template or ""))
        prompt_data = dict(prompt or {})
        llm_data = dict(llm or {})
        model = str(llm_data.get("model") or "").strip()
        if not model:
            raise ProviderError("llm.model 不能为空")
        user_template = str(prompt_data.get("user_template") or "").strip()
        if not user_template:
            raise ProviderError("prompt.user_template 不能为空")
        temperature = _as_float(llm_data.get("temperature"), DEFAULT_TEMPERATURE)
        if not 0 <= temperature <= 2:
            raise ProviderError("llm.temperature 必须在 0-2 之间")
        raw_max_tokens = llm_data.get("max_tokens")
        max_tokens = DEFAULT_MAX_TOKENS if raw_max_tokens in (None, "") else int(raw_max_tokens)
        if not 1 <= max_tokens <= MAX_TOKENS_LIMIT:
            raise ProviderError(f"llm.max_tokens 必须在 1-{MAX_TOKENS_LIMIT} 之间")
        return cls(
            url=url,
            model=model,
            system=str(prompt_data.get("system") or "").strip(),
            user_template=user_template,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=_as_bool(llm_data.get("json_mode"), True),
            timeout=float(timeout or DEFAULT_TIMEOUT),
        )

    @classmethod
    def from_request_spec(cls, spec: RequestSpec) -> LlmConfig:
        return cls.from_payload(
            url_template=spec.url_template,
            prompt=spec.prompt,
            llm=spec.llm,
            timeout=spec.timeout,
        )


@dataclass(slots=True)
class LlmConnectionResult:
    """连通测试结果（不落库、不写运行记录）."""

    ok: bool
    latency_ms: int
    model: str = ""
    message: str = ""


class LlmPromptProvider:
    """大模型提示词 provider：一次请求生成一组行."""

    name = "llm_prompt"
    label = "大模型提示词"
    params_schema: Mapping[str, Any] = LLM_PROMPT_PARAMS_SCHEMA
    default_cursor: CursorStrategy = "none"
    supports_paging = False
    uses_custom_parse = True

    def build_requests(self, job: SyncJobSpec) -> list[RequestPlan]:
        config = LlmConfig.from_request_spec(job.request)
        api_key = _api_key(job)
        plans: list[RequestPlan] = []
        for entrant in job.entrant_values or (None,):
            variables = self._variables(job, entrant)
            metadata: dict[str, Any] = {}
            plan = RequestPlan(
                config=self._fetch_config(config, job, variables, api_key, metadata),
                label=f"entrant={entrant}" if entrant is not None else "single",
                entrant=entrant,
                metadata=metadata,
            )
            plans.append(plan)
        return plans

    def parse(self, text: str, job: SyncJobSpec) -> list[dict[str, Any]]:
        del job  # 解析不依赖任务字段；保留签名以满足 SourceProvider 协议
        return _parse_response(text)

    def normalize(self, rows: Sequence[Mapping[str, Any]], job: SyncJobSpec) -> NormalizeResult:
        return apply_field_mapping(rows, job.field_mapping)

    def _fetch_config(
        self,
        config: LlmConfig,
        job: SyncJobSpec,
        variables: Mapping[str, Any],
        api_key: str,
        metadata: dict[str, Any],
    ) -> FetchConfig:
        headers = {
            "Content-Type": "application/json",
            **{key: render_text(value, variables) for key, value in job.request.headers_template.items()},
        }
        if not any(key.lower() == "authorization" for key in headers):
            headers["Authorization"] = f"Bearer {api_key}"
        system = config.system or JSON_INSTRUCTION
        if JSON_INSTRUCTION not in system:
            system = f"{system}\n{JSON_INSTRUCTION}"
        body: dict[str, Any] = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": render_text(config.user_template, variables)},
            ],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        }
        if config.json_mode:
            body["response_format"] = {"type": "json_object"}

        def handler(text: str, _config: FetchConfig) -> list[dict[str, Any]]:
            return _parse_response(text, metadata)

        return FetchConfig(
            url=config.url,
            method="POST",
            headers=headers,
            body=body,
            timeout=config.timeout,
            response_handler=handler,
        )

    def _variables(self, job: SyncJobSpec, entrant: str | None) -> dict[str, Any]:
        variables: dict[str, Any] = dict(job.extra_variables)
        if job.entrant_param:
            variables[job.entrant_param] = entrant
        variables["entrant"] = entrant
        if "today" not in variables:
            variables["today"] = _today()
        window = job.request.time_window
        if window.mode == "range":
            variables[window.start_param] = window.start
            variables[window.end_param] = window.end
            variables["start"] = window.start
            variables["end"] = window.end
        return variables


def normalize_endpoint(url: str) -> str:
    """把 base_url 归一为 ``.../chat/completions`` 端点；已带路径则原样保留."""
    value = url.strip().rstrip("/")
    if not value:
        raise ProviderError("request_spec.url_template 不能为空")
    if not value.startswith(("http://", "https://")):
        raise ProviderError("request_spec.url_template 必须是 http/https URL")
    if not value.endswith("/chat/completions"):
        value = f"{value}/chat/completions"
    return value


def validate_llm_request_spec(
    payload: Mapping[str, Any] | None,
    *,
    entrant_param: str | None = None,
    schedule: Mapping[str, Any] | None = None,
    match_keys: Sequence[str] = (),
) -> LlmConfig:
    """创建 / 更新时的 LLM 配置校验（错误信息直接返回前端）."""
    data = dict(payload or {})
    config = LlmConfig.from_payload(
        url_template=data.get("url_template"),
        prompt=data.get("prompt") if isinstance(data.get("prompt"), Mapping) else None,
        llm=data.get("llm") if isinstance(data.get("llm"), Mapping) else None,
        timeout=data.get("timeout"),
    )
    raw_window = data.get("time_window")
    window: Mapping[str, Any] = raw_window if isinstance(raw_window, Mapping) else {}
    allowed: dict[str, Any] = {"today": _today(), "api_key": "test-key"}
    if entrant_param:
        allowed["entrant"] = "示例"
        allowed[entrant_param] = "示例"
    if dict(window or {}).get("mode") == "range":
        for key in ("start", "end", str(window.get("start_param") or ""), str(window.get("end_param") or "")):
            if key:
                allowed[key] = "2020-01-01"
    render_text(config.system, allowed)
    render_text(config.user_template, allowed)
    if str(dict(schedule or {}).get("mode") or "") == "cron" and not [key for key in match_keys if key]:
        raise ProviderError("llm_prompt 使用 cron 调度时必须配置 match_keys")
    return config


def test_llm_connection(
    spec: RequestSpec,
    *,
    api_key: str,
    session_headers: Mapping[str, str] | None = None,
    fetch: FetchFn | None = None,
) -> LlmConnectionResult:
    """发一次最小模型请求验证地址 / Key / 模型；不落库、不写运行记录."""
    started = time.perf_counter()
    if not api_key.strip():
        return LlmConnectionResult(ok=False, latency_ms=0, message="未配置 api_key")
    try:
        prompt = dict(spec.prompt or {})
        prompt.setdefault("user_template", TEST_PROMPT)
        config = LlmConfig.from_payload(
            url_template=spec.url_template,
            prompt=prompt,
            llm=spec.llm,
            timeout=spec.timeout,
        )
        metadata: dict[str, Any] = {}
        merged_headers = {**(session_headers or {}), **spec.headers_template}
        headers = {
            "Content-Type": "application/json",
            **{key: render_text(value, {"api_key": api_key}) for key, value in merged_headers.items()},
        }
        if not any(key.lower() == "authorization" for key in headers):
            headers["Authorization"] = f"Bearer {api_key}"
        body: dict[str, Any] = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": JSON_INSTRUCTION},
                {"role": "user", "content": TEST_PROMPT},
            ],
            "temperature": 0,
            "max_tokens": min(config.max_tokens, TEST_MAX_TOKENS),
        }
        if config.json_mode:
            body["response_format"] = {"type": "json_object"}

        def handler(text: str, _config: FetchConfig) -> list[dict[str, Any]]:
            return _parse_response(text, metadata)

        fetcher = fetch or fetch_json
        fetcher(
            FetchConfig(
                url=config.url,
                method="POST",
                headers=headers,
                body=body,
                timeout=config.timeout,
                response_handler=handler,
            )
        )
        latency = int((time.perf_counter() - started) * 1000)
        return LlmConnectionResult(
            ok=True,
            latency_ms=latency,
            model=str(metadata.get("model") or config.model),
            message="连通成功",
        )
    except Exception as exc:  # 连通测试把异常转成可展示结果，不向上抛
        latency = int((time.perf_counter() - started) * 1000)
        return LlmConnectionResult(ok=False, latency_ms=latency, message=str(exc)[:500])


# ── 内部 ──────────────────────────────────────────


def _parse_response(
    text: str,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProviderError(f"模型响应不是合法 JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ProviderError("模型响应必须是 JSON 对象")
    if "choices" not in payload and payload.get("error"):
        raise ProviderError(f"模型接口错误: {_error_message(payload.get('error'))}")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("模型响应缺少 choices")
    first: Mapping[str, Any] = choices[0] if isinstance(choices[0], Mapping) else {}
    raw_message = first.get("message")
    message: Mapping[str, Any] = raw_message if isinstance(raw_message, Mapping) else {}
    content = _content_text(message.get("content"))
    if not content:
        raise ProviderError("模型响应 content 为空")
    if metadata is not None:
        metadata.update(_response_metadata(payload))
    try:
        parsed = json.loads(strip_json_fences(content))
    except json.JSONDecodeError as exc:
        raise ProviderError(f"模型返回内容不是合法 JSON: {exc}") from exc
    return _rows_from_payload(parsed)


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [_as_row(item) for item in payload]
    if isinstance(payload, Mapping):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return [_as_row(item) for item in rows]
        return [dict(payload)]
    raise ProviderError("模型返回的 JSON 必须是对象或对象数组")


def _as_row(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise ProviderError("模型返回的数组元素必须是对象")
    return dict(item)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts).strip()
    return ""


def strip_json_fences(content: str) -> str:
    """去掉模型常见的 ```json ... ``` 代码围栏."""
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _response_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {"model": str(payload.get("model") or "")}
    usage = payload.get("usage")
    if isinstance(usage, Mapping):
        metadata["usage"] = {
            key: int(value)
            for key, value in usage.items()
            if key in ("prompt_tokens", "completion_tokens", "total_tokens") and isinstance(value, int)
        }
    return metadata


def _error_message(error: Any) -> str:
    if isinstance(error, Mapping):
        return str(error.get("message") or error)
    return str(error)


def _api_key(job: SyncJobSpec) -> str:
    value = str(job.extra_variables.get("api_key") or "").strip()
    if not value:
        raise ProviderError("llm_prompt 需要绑定包含 api_key 的凭证会话")
    return value


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("false", "0", "no", "off")


def _as_float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ProviderError(f"llm.temperature 必须是数字: {value!r}") from exc


def _today() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TEMPERATURE",
    "JSON_INSTRUCTION",
    "LLM_PROMPT_PARAMS_SCHEMA",
    "LlmConfig",
    "LlmConnectionResult",
    "LlmPromptProvider",
    "normalize_endpoint",
    "strip_json_fences",
    "test_llm_connection",
    "validate_llm_request_spec",
]

if TYPE_CHECKING:
    # 类型检查期验证实现满足 SourceProvider 协议（运行期零开销）
    _contract: SourceProvider = LlmPromptProvider()
