"""内置 provider：``llm_prompt`` —— 用大模型提示词生成数据行（ADR 0014 / ADR 0019 / ADR 0020）.

ADR 0020 P0 起，模型调用 / 连接解析 / JSON 解析已抽到平台插件 ``cndb.plugins.llm``；
本模块只保留数据源领域语义：提示词变量求值、请求体组装、行解析与落表（``auto_table``）。
因此这里不出现任何 HTTP 细节，``provider.build_requests`` 产出的 ``RequestPlan`` 通过
``fetcher`` 指回平台客户端（重试 / SSRF 白名单统一在 ``llm.services.client``）。

协议限定为 OpenAI 兼容 ``POST {base_url}/chat/completions``：

- 请求：``system`` / ``user_template`` 经 ``render_text_lenient`` 宽松求值后组成 messages
  （未知占位符 / JSON 裸花括号原样保留，ADR 0019），``json_mode=true`` 时附带
  ``response_format={"type":"json_object"}``；
  系统提示词优先级：任务显式 system > 个人连接覆盖 > 内置 :data:`DEFAULT_SYSTEM_PROMPT`；
- 响应：取 ``choices[0].message.content``，去掉 Markdown 代码围栏后解析 JSON；
  对象 → 1 行，对象数组 → N 行，``{"rows": [...]}`` → 取 rows；
- 落表：复用 ``apply_field_mapping`` + 既有 ``upsert_rows``（按 ``match_keys`` 幂等）。

API Key 只从运行期模板变量 ``api_key`` 取（凭证会话或个人连接），缺失直接报错，不发出请求。
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cndb.core.http import DEFAULT_TIMEOUT as HTTP_DEFAULT_TIMEOUT
from cndb.core.http import FetchConfig, fetch_json
from cndb.plugins.datasource.providers.base import (
    CursorStrategy,
    FetchFn,
    ProviderError,
    RequestPlan,
    RequestSpec,
    SourceProvider,
    SyncJobSpec,
)
from cndb.plugins.datasource.providers.template import render_text, render_text_lenient
from cndb.plugins.datasource.services.normalize import NormalizeResult, apply_field_mapping
from cndb.plugins.llm.services.client import (
    LlmConnectionResult,
    as_fetcher,
    build_chat_body,
)
from cndb.plugins.llm.services.client import (
    normalize_endpoint as _normalize_endpoint,
)
from cndb.plugins.llm.services.connection import DEFAULT_BASE_URL, DEFAULT_MODEL
from cndb.plugins.llm.services.parsing import parse_chat_response, strip_json_fences
from cndb.plugins.llm.services.prompts import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TEMPERATURE,
    JSON_INSTRUCTION,
    MAX_TOKENS_LIMIT,
    TEST_MAX_TOKENS,
    TEST_PROMPT,
)

DEFAULT_TIMEOUT = HTTP_DEFAULT_TIMEOUT

# 供前端动态渲染的表单描述；前端当前按 provider 条件渲染固定字段，此处仍对外暴露。
# ADR 0019 起地址 / 模型从个人「大模型连接」继承，任务侧留空即可，因此 required=False。
LLM_PROMPT_PARAMS_SCHEMA: dict[str, Any] = {
    "fields": [
        {"name": "url_template", "type": "text", "required": False, "label": "API 地址（留空用个人连接）"},
        {"name": "model", "type": "text", "required": False, "label": "模型（留空用个人连接）"},
        {"name": "system_prompt", "type": "textarea", "label": "系统提示词（留空用内置默认）"},
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
        try:
            url = _normalize_endpoint(str(url_template or "").strip() or DEFAULT_BASE_URL)
        except ValueError as exc:  # 平台层抛 ValueError，保持既有 ProviderError 语义
            raise ProviderError(str(exc)) from exc
        prompt_data = dict(prompt or {})
        llm_data = dict(llm or {})
        # ADR 0019：地址 / 模型可从个人「大模型连接」继承，任务配置允许缺省。
        model = str(llm_data.get("model") or "").strip() or DEFAULT_MODEL
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
        # ADR 0020：LLM 请求经平台客户端执行（重试 / SSRF 白名单 / 错误分类统一）
        fetcher: FetchFn = as_fetcher()
        plans: list[RequestPlan] = []
        for entrant in job.entrant_values or (None,):
            variables = self._variables(job, entrant)
            metadata: dict[str, Any] = {}
            plan = RequestPlan(
                config=self._fetch_config(config, job, variables, api_key, metadata),
                label=f"entrant={entrant}" if entrant is not None else "single",
                entrant=entrant,
                metadata=metadata,
                fetcher=fetcher,
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
        # 提示词用宽松模板（ADR 0019）：用户提示词里的 JSON 裸花括号 / 未注册占位符原样保留，
        # 但 headers 等请求模板仍走严格 render_text，语义不变。
        system = render_text_lenient(_system_prompt(config, job), variables)
        body = build_chat_body(
            model=config.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": render_text_lenient(config.user_template, variables)},
            ],
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            json_mode=config.json_mode,
        )

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
    """把 base_url 归一为 ``.../chat/completions`` 端点（平台实现 + 既有错误类型）."""
    try:
        return _normalize_endpoint(url)
    except ValueError as exc:
        raise ProviderError(str(exc)) from exc


def validate_llm_request_spec(
    payload: Mapping[str, Any] | None,
    *,
    entrant_param: str | None = None,
    schedule: Mapping[str, Any] | None = None,
    match_keys: Sequence[str] = (),
) -> LlmConfig:
    """创建 / 更新时的 LLM 配置校验（错误信息直接返回前端）.

    ADR 0019 起不再强制「cron 必须手填 match_keys」：幂等键由运行期根据数据自动识别，
    ``schedule`` / ``match_keys`` 参数仅为兼容既有调用方保留。
    """
    del schedule, match_keys
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
    # 提示词宽松求值（ADR 0019）：未知占位符 / JSON 裸花括号原样保留，不阻断保存
    render_text_lenient(config.system, allowed)
    render_text_lenient(config.user_template, allowed)
    return config


def test_llm_connection(
    spec: RequestSpec,
    *,
    api_key: str,
    session_headers: Mapping[str, str] | None = None,
    fetch: FetchFn | None = None,
) -> LlmConnectionResult:
    """发一次最小模型请求验证地址 / Key / 模型；不落库、不写运行记录.

    ADR 0020：连通测试只用于「个人设置 → 大模型」，接口层已迁到
    ``POST /api/v1/llm/config/test``；本函数保留给数据源侧诊断与既有测试。
    """
    started = time.perf_counter()
    if not api_key.strip():
        return LlmConnectionResult(
            ok=False,
            latency_ms=0,
            message="未配置 api_key：请先在「大模型连接」或凭证会话中配置 API Key",
        )
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
        # 连通测试仍用最小请求（固定用户提示、限制 max_tokens），避免真实提示词被截断误判；
        # system / user 的求值同样走宽松模板，含 JSON 裸花括号也不会报错。
        variables: dict[str, Any] = {"api_key": api_key, "today": _today()}
        system_content = render_text_lenient(config.system, variables) if config.system else JSON_INSTRUCTION
        body = build_chat_body(
            model=config.model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": render_text_lenient(TEST_PROMPT, variables)},
            ],
            temperature=0,
            max_tokens=min(config.max_tokens, TEST_MAX_TOKENS),
            json_mode=config.json_mode,
        )

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


def _system_prompt(config: LlmConfig, job: SyncJobSpec) -> str:
    """系统提示词优先级：任务显式 > 个人连接覆盖 > 内置默认；始终追加 JSON 指令."""
    override = str(job.extra_variables.get("system_prompt_default") or "").strip()
    system = config.system or override or DEFAULT_SYSTEM_PROMPT
    if JSON_INSTRUCTION not in system:
        system = f"{system}\n{JSON_INSTRUCTION}"
    return system


def _parse_response(
    text: str,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """OpenAI 兼容响应 → 行数组（解析实现已迁到 ``llm.services.parsing``）."""
    try:
        return parse_chat_response(text, metadata)
    except ValueError as exc:  # 平台层 LlmOutputInvalid → 数据源既有 ProviderError
        raise ProviderError(str(exc)) from exc


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
    "DEFAULT_SYSTEM_PROMPT",
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
