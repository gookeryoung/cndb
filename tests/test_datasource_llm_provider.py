"""ADR 0014 / ADR 0019：llm_prompt provider 单测（请求构造 / JSON 解析 / 校验 / 连通测试）."""

from __future__ import annotations

import json

import pytest

from cndb.plugins.datasource.providers.base import (
    FieldTransform,
    ProviderError,
    RequestSpec,
    SyncJobSpec,
    TimeWindowSpec,
)
from cndb.plugins.datasource.providers.llm_prompt import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_SYSTEM_PROMPT,
    JSON_INSTRUCTION,
    LLM_PROMPT_PARAMS_SCHEMA,
    LlmConfig,
    LlmPromptProvider,
    normalize_endpoint,
    strip_json_fences,
    validate_llm_request_spec,
)
from cndb.plugins.datasource.providers.llm_prompt import (
    test_llm_connection as run_connection_test,
)
from cndb.plugins.datasource.services.connection import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LlmConnection,
    resolve_request_spec_defaults,
)
from cndb.plugins.datasource.services.pipeline import run_pipeline
from cndb.plugins.tables.services.importing.api_fetch import FetchConfig

PROVIDER = LlmPromptProvider()


def _spec(**overrides: object) -> RequestSpec:
    base: dict[str, object] = {
        "url_template": "https://llm.example.com",
        "prompt": {"system": "你是数据助手", "user_template": "生成 {today} {city} 的摘要"},
        "llm": {"model": "model-a", "temperature": 0.5, "max_tokens": 256},
    }
    base.update(overrides)
    return RequestSpec(**base)  # type: ignore[arg-type]


def _job(**overrides: object) -> SyncJobSpec:
    base: dict[str, object] = {
        "request": _spec(),
        "provider": "llm_prompt",
        "entrant_param": "city",
        "entrant_values": ("北京",),
        "extra_variables": {"api_key": "sk-test", "today": "2024-06-30"},
    }
    base.update(overrides)
    return SyncJobSpec(**base)  # type: ignore[arg-type]


def _model_response(content: object, *, model: str = "model-a", usage: dict[str, int] | None = None) -> str:
    payload = {
        "choices": [{"message": {"content": content}}],
        "model": model,
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    return json.dumps(payload)


class TestBuildRequests:
    def test_builds_openai_compatible_request(self):
        plans = PROVIDER.build_requests(_job())
        assert len(plans) == 1
        plan = plans[0]
        assert plan.config.url == "https://llm.example.com/chat/completions"
        assert plan.config.method == "POST"
        assert plan.config.headers["Authorization"] == "Bearer sk-test"
        assert plan.config.headers["Content-Type"] == "application/json"
        assert plan.config.body["model"] == "model-a"
        assert plan.config.body["temperature"] == 0.5
        assert plan.config.body["max_tokens"] == 256
        assert plan.config.body["response_format"] == {"type": "json_object"}
        assert plan.config.body["messages"][0]["content"].startswith("你是数据助手")
        assert JSON_INSTRUCTION in plan.config.body["messages"][0]["content"]
        assert plan.config.body["messages"][1]["content"] == "生成 2024-06-30 北京 的摘要"
        assert plan.entrant == "北京"
        assert plan.label == "entrant=北京"

    def test_url_already_has_path(self):
        plans = PROVIDER.build_requests(
            _job(request=_spec(url_template="https://llm.example.com/v1/chat/completions/"))
        )
        assert plans[0].config.url == "https://llm.example.com/v1/chat/completions"

    def test_json_mode_can_be_disabled(self):
        spec = _spec(llm={"model": "model-a", "json_mode": False})
        plans = PROVIDER.build_requests(_job(request=spec))
        assert "response_format" not in plans[0].config.body

    def test_missing_api_key_raises(self):
        with pytest.raises(ProviderError, match="api_key"):
            PROVIDER.build_requests(_job(extra_variables={}))

    def test_inline_authorization_header_is_kept(self):
        spec = _spec(headers_template={"Authorization": "Bearer {api_key}"})
        plans = PROVIDER.build_requests(_job(request=spec))
        assert plans[0].config.headers["Authorization"] == "Bearer sk-test"

    def test_time_window_variables_are_injected(self):
        spec = _spec(
            prompt={"system": "", "user_template": "区间 {start} ~ {end}，今天 {today}"},
            time_window=TimeWindowSpec(mode="range", start="2024-01-01", end="2024-01-03"),
        )
        plans = PROVIDER.build_requests(_job(request=spec))
        assert plans[0].config.body["messages"][1]["content"] == "区间 2024-01-01 ~ 2024-01-03，今天 2024-06-30"

    def test_unknown_placeholder_is_kept_literal(self):
        """ADR 0019：提示词里的未知占位符原样保留，不再阻断运行."""
        spec = _spec(prompt={"system": "系统 {unknown}", "user_template": "缺少 {unknown}"})
        plan = PROVIDER.build_requests(_job(request=spec))[0]
        assert "{unknown}" in plan.config.body["messages"][0]["content"]
        assert plan.config.body["messages"][1]["content"] == "缺少 {unknown}"

    def test_json_example_in_user_prompt_is_kept(self):
        """用户提示词直接写 JSON 示例（裸花括号）不再报模板错误."""
        spec = _spec(
            prompt={
                "system": "",
                "user_template": '请按 {"rows": [{"city": "北京", "date": "{today}"}]} 的格式输出',
            }
        )
        content = PROVIDER.build_requests(_job(request=spec))[0].config.body["messages"][1]["content"]
        assert '{"rows": [{"city": "北京", "date": "2024-06-30"}]}' in content

    def test_escaped_braces_still_unescape(self):
        """{{ / }} 转义口径不变（前端推荐提示词无需修改）."""
        spec = _spec(prompt={"system": "", "user_template": '输出 {{"ok": true}}，今天 {today}'})
        content = PROVIDER.build_requests(_job(request=spec))[0].config.body["messages"][1]["content"]
        assert content == '输出 {"ok": true}，今天 2024-06-30'

    def test_headers_still_strict(self):
        """其它请求模板保持严格语义：未知占位符照旧报错."""
        spec = _spec(headers_template={"X-Test": "{unknown}"})
        with pytest.raises(ProviderError, match="模板变量缺失"):
            PROVIDER.build_requests(_job(request=spec))

    def test_default_max_tokens_is_used_when_not_configured(self):
        """默认 max_tokens 提到 4096，避免长 JSON 输出被截断（实机故障回归）."""
        plan = PROVIDER.build_requests(_job(request=_spec(llm={"model": "model-a"})))[0]
        assert plan.config.body["max_tokens"] == 4096

    def test_default_system_prompt_is_used_when_not_configured(self):
        """ADR 0019：任务不填系统提示词时用内置默认（用户只配用户提示词）."""
        spec = _spec(prompt={"user_template": "生成 {today} 的摘要"})
        plans = PROVIDER.build_requests(_job(request=spec))
        system = plans[0].config.body["messages"][0]["content"]
        assert system.startswith(DEFAULT_SYSTEM_PROMPT)
        assert JSON_INSTRUCTION in system

    def test_connection_system_prompt_overrides_builtin_default(self):
        """工作区连接的系统提示词覆盖优先于内置默认，但仍低于任务显式配置."""
        spec = _spec(prompt={"user_template": "生成 {today} 的摘要"})
        job = _job(
            request=spec,
            extra_variables={
                "api_key": "sk-test",
                "today": "2024-06-30",
                "system_prompt_default": "工作区自定义系统提示词",
            },
        )
        system = PROVIDER.build_requests(job)[0].config.body["messages"][0]["content"]
        assert system.startswith("工作区自定义系统提示词")

    def test_task_system_prompt_beats_connection_override(self):
        spec = _spec(prompt={"system": "任务系统提示词", "user_template": "生成 {today}"})
        job = _job(
            request=spec,
            extra_variables={
                "api_key": "sk-test",
                "today": "2024-06-30",
                "system_prompt_default": "工作区自定义系统提示词",
            },
        )
        system = PROVIDER.build_requests(job)[0].config.body["messages"][0]["content"]
        assert system.startswith("任务系统提示词")

    def test_missing_url_and_model_fall_back_to_defaults(self):
        """ADR 0019：config 层允许地址 / 模型缺省，补内置默认值（路由层在构造 RequestSpec 前补齐）."""
        config = LlmConfig.from_payload(url_template="", prompt={"user_template": "ping"}, llm={})
        assert config.url == f"{DEFAULT_BASE_URL}/chat/completions"
        assert config.model == DEFAULT_MODEL

    def test_default_system_prompt_requires_synthesis_tasks_output(self):
        """系统提示词新口径：综述 / 摘要 / 推荐类必须尽力输出，不能因无法联网返回空."""
        assert "综合整理" in DEFAULT_SYSTEM_PROMPT
        assert "不要因为无法联网" in DEFAULT_SYSTEM_PROMPT
        assert "综述 / 摘要 / 推荐类任务" in DEFAULT_SYSTEM_PROMPT
        assert '{"rows": []}' in DEFAULT_SYSTEM_PROMPT
        assert "编造" in DEFAULT_SYSTEM_PROMPT

    def test_default_system_prompt_supports_chinese_field_names(self):
        """字段命名支持中文：不再强制英文 snake_case，指定字段名必须逐字沿用（2026-10-23）."""
        assert "字段名支持中文" in DEFAULT_SYSTEM_PROMPT
        assert "逐字沿用" in DEFAULT_SYSTEM_PROMPT
        # 旧口径整句已移除，避免模型继续把中文字段翻译成英文
        assert "不要使用中文" not in DEFAULT_SYSTEM_PROMPT
        assert "统一使用英文 snake_case" not in DEFAULT_SYSTEM_PROMPT

    def test_chinese_field_mapping_is_preserved(self):
        """中文字段名走归一链路时原样保留（映射键与目标名均为中文）."""
        job = _job(
            field_mapping={
                "标题": {"name": "标题", "field_type": "text"},
                "适用部门": {"name": "适用部门", "field_type": "text"},
            }
        )
        rows = PROVIDER.parse(
            _model_response('{"rows": [{"标题": "数据出境安全评估申报指引", "适用部门": "法务合规部"}]}'),
            job,
        )
        result = PROVIDER.normalize(rows, job)
        assert result.rows == [{"标题": "数据出境安全评估申报指引", "适用部门": "法务合规部"}]


class TestParse:
    def test_object_becomes_single_row(self):
        rows = PROVIDER.parse(_model_response('{"summary": "晴"}'), _job())
        assert rows == [{"summary": "晴"}]

    def test_array_becomes_rows(self):
        rows = PROVIDER.parse(_model_response('[{"summary": "晴"}, {"summary": "雨"}]'), _job())
        assert rows == [{"summary": "晴"}, {"summary": "雨"}]

    def test_rows_key_is_unwrapped(self):
        rows = PROVIDER.parse(_model_response('{"rows": [{"summary": "晴"}]}'), _job())
        assert rows == [{"summary": "晴"}]

    def test_markdown_fence_is_stripped(self):
        content = '```json\n{"summary": "晴"}\n```'
        rows = PROVIDER.parse(_model_response(content), _job())
        assert rows == [{"summary": "晴"}]

    def test_content_parts_are_joined(self):
        content = [{"type": "text", "text": '{"summary":'}, {"type": "text", "text": '"晴"}'}]
        rows = PROVIDER.parse(_model_response(content), _job())
        assert rows == [{"summary": "晴"}]

    def test_response_metadata_is_recorded(self):
        plan = PROVIDER.build_requests(_job())[0]
        assert plan.config.response_handler is not None
        plan.config.response_handler(_model_response('{"summary": "晴"}'), plan.config)
        assert plan.metadata == {
            "model": "model-a",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    @pytest.mark.parametrize(
        ("content", "match"),
        [
            ("not json", "模型返回内容不是合法 JSON"),
            ('"just a string"', "必须是对象或对象数组"),
            ("[1, 2]", "数组元素必须是对象"),
            ("", "content 为空"),
        ],
    )
    def test_invalid_content_raises(self, content, match):
        with pytest.raises(ProviderError, match=match):
            PROVIDER.parse(_model_response(content), _job())

    def test_invalid_envelope_raises(self):
        with pytest.raises(ProviderError, match="不是合法 JSON"):
            PROVIDER.parse("<html>", _job())
        with pytest.raises(ProviderError, match="必须是 JSON 对象"):
            PROVIDER.parse("[]", _job())
        with pytest.raises(ProviderError, match="缺少 choices"):
            PROVIDER.parse('{"model": "x"}', _job())
        with pytest.raises(ProviderError, match="模型接口错误"):
            PROVIDER.parse('{"error": {"message": "invalid key"}}', _job())

    def test_truncated_content_reports_max_tokens_hint(self):
        """实机故障：长输出在字符串中途结束（Unterminated string）→ 提示提高 max_tokens."""
        content = '{"rows": [{"dish_name": "宫保鸡丁", "steps": "第一步 准备鸡腿肉与花生米'
        with pytest.raises(ProviderError, match="截断") as excinfo:
            PROVIDER.parse(_model_response(content), _job())
        message = str(excinfo.value)
        assert "max_tokens" in message
        assert "4096" in message
        assert f"本次返回 {len(content)} 字符" in message

    def test_truncated_expecting_error_at_tail_is_classified(self):
        """截断也可能表现为末尾缺分隔符（Expecting），同样按截断提示."""
        content = '{"rows": [{"date": "2026-10-22"}'
        with pytest.raises(ProviderError, match="截断"):
            PROVIDER.parse(_model_response(content), _job())

    def test_syntax_error_inside_content_keeps_original_message(self):
        """内容中间的语法错误（漏逗号）不是截断，保留原「不是合法 JSON」文案."""
        content = '{"a": 1 "b": 2}'
        with pytest.raises(ProviderError, match="模型返回内容不是合法 JSON") as excinfo:
            PROVIDER.parse(_model_response(content), _job())
        assert "截断" not in str(excinfo.value)

    def test_normalize_uses_field_mapping(self):
        job = _job(field_mapping={"summary": FieldTransform(name="摘要", field_type="text")})
        result = PROVIDER.normalize([{"summary": "晴"}], job)
        assert result.rows == [{"摘要": "晴"}]


class TestValidation:
    def test_valid_payload(self):
        config = validate_llm_request_spec(
            {
                "url_template": "https://llm.example.com",
                "prompt": {"user_template": "生成 {today} {city}", "system": ""},
                "llm": {"model": "model-a"},
            },
            entrant_param="city",
            schedule={"mode": "cron"},
            match_keys=["city"],
        )
        assert config.url == "https://llm.example.com/chat/completions"
        assert config.model == "model-a"

    @pytest.mark.parametrize(
        ("payload", "match"),
        [
            ({"url_template": "https://x", "prompt": {"user_template": ""}, "llm": {"model": "m"}}, "user_template"),
            ({"url_template": "ftp://x", "prompt": {"user_template": "x"}, "llm": {"model": "m"}}, "http"),
            (
                {
                    "url_template": "https://x",
                    "prompt": {"user_template": "x"},
                    "llm": {"model": "m", "temperature": 3},
                },
                "temperature",
            ),
            (
                {"url_template": "https://x", "prompt": {"user_template": "x"}, "llm": {"model": "m", "max_tokens": 0}},
                "max_tokens",
            ),
        ],
    )
    def test_invalid_payload(self, payload, match):
        with pytest.raises(ProviderError, match=match):
            validate_llm_request_spec(payload, entrant_param="city")

    def test_missing_url_and_model_use_defaults(self):
        """ADR 0019：地址 / 模型缺省时补内置默认值，不再报「不能为空」."""
        config = validate_llm_request_spec({"prompt": {"user_template": "生成 {today}"}})
        assert config.url == f"{DEFAULT_BASE_URL}/chat/completions"
        assert config.model == DEFAULT_MODEL

    def test_default_max_tokens_is_4096(self):
        """默认 max_tokens 4096（1024 会截断长 JSON），schema 默认值同步."""
        assert DEFAULT_MAX_TOKENS == 4096
        config = validate_llm_request_spec({"prompt": {"user_template": "生成 {today}"}})
        assert config.max_tokens == 4096
        fields = {field["name"]: field for field in LLM_PROMPT_PARAMS_SCHEMA["fields"]}
        assert fields["max_tokens"]["default"] == 4096

    def test_cron_does_not_require_match_keys(self):
        """ADR 0019：幂等键由运行期自动识别，cron 不再强制手填 match_keys."""
        payload = {
            "url_template": "https://x",
            "prompt": {"user_template": "生成 {today}"},
            "llm": {"model": "m"},
        }
        config = validate_llm_request_spec(payload, schedule={"mode": "cron"}, match_keys=[])
        assert config.model == "m"

    def test_start_end_placeholders_kept_without_range_window(self):
        """未配置时间区间时 {start} / {end} 原样保留，保存不再失败."""
        payload = {
            "url_template": "https://x",
            "prompt": {"user_template": "区间 {start} ~ {end}"},
            "llm": {"model": "m"},
        }
        config = validate_llm_request_spec(payload)
        assert config.user_template == "区间 {start} ~ {end}"
        assert validate_llm_request_spec({**payload, "time_window": {"mode": "range"}}).model == "m"

    def test_entrant_placeholder_kept_without_entrant_param(self):
        payload = {
            "url_template": "https://x",
            "prompt": {"user_template": "生成 {entrant}"},
            "llm": {"model": "m"},
        }
        assert "{entrant}" in validate_llm_request_spec(payload).user_template
        assert validate_llm_request_spec(payload, entrant_param="city").model == "m"

    def test_json_in_system_prompt_validates(self):
        """系统提示词含 JSON 裸花括号也能保存（宽松模板）."""
        config = validate_llm_request_spec(
            {
                "prompt": {"system": '返回 {"rows": []}', "user_template": "x"},
                "llm": {"model": "m"},
            }
        )
        assert config.system == '返回 {"rows": []}'


def test_pipeline_collects_response_metadata():
    job = _job(
        request=_spec(prompt={"system": "", "user_template": "生成 {today}"}),
        entrant_param=None,
        entrant_values=(),
        field_mapping={"summary": FieldTransform(name="摘要", field_type="text")},
    )
    raw = _model_response('[{"summary": "晴"}]')

    def fetch(config: FetchConfig):
        return config.response_handler(raw, config)

    outcome = run_pipeline(job, provider=PROVIDER, fetch=fetch)
    assert outcome.rows == [{"摘要": "晴"}]
    assert outcome.metadata == [
        {
            "label": "single",
            "model": "model-a",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    ]


class TestHelpers:
    def test_normalize_endpoint(self):
        assert normalize_endpoint("https://x") == "https://x/chat/completions"
        assert normalize_endpoint("https://x/") == "https://x/chat/completions"
        assert normalize_endpoint("https://x/v1/chat/completions") == "https://x/v1/chat/completions"
        with pytest.raises(ProviderError, match="不能为空"):
            normalize_endpoint("")

    def test_strip_json_fences(self):
        assert strip_json_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
        assert strip_json_fences('{"a": 1}') == '{"a": 1}'
        assert strip_json_fences("```\n[1]\n```") == "[1]"


class TestConnection:
    def test_success(self):
        calls: list[FetchConfig] = []

        def fetch(config: FetchConfig):
            calls.append(config)
            config.response_handler(_model_response('{"ok": true}', model="model-b"), config)
            return []

        result = run_connection_test(_spec(), api_key="sk-test", fetch=fetch)
        assert result.ok is True
        assert result.model == "model-b"
        assert result.latency_ms >= 0
        assert calls[0].url == "https://llm.example.com/chat/completions"
        assert calls[0].body["max_tokens"] == 64

    def test_missing_key(self):
        result = run_connection_test(_spec(), api_key="")
        assert result.ok is False
        assert "api_key" in result.message
        assert "大模型连接" in result.message

    def test_fetch_error_is_returned(self):
        def fetch(_config: FetchConfig):
            raise ValueError("API 返回 401: invalid key")

        result = run_connection_test(_spec(), api_key="sk-test", fetch=fetch)
        assert result.ok is False
        assert "401" in result.message

    def test_invalid_config_is_returned(self):
        result = run_connection_test(_spec(llm={"model": "m", "max_tokens": 0}), api_key="sk-test")
        assert result.ok is False
        assert "max_tokens" in result.message


class TestResolveDefaults:
    """ADR 0019：任务 request_spec 的连接默认值补全（api_key 永不写入）."""

    def test_fills_missing_url_and_model(self):
        conn = LlmConnection(base_url="https://proxy.example.com/v1", model="deepseek-chat", api_key="sk-secret")
        filled = resolve_request_spec_defaults({"prompt": {"user_template": "生成 {today}"}}, conn)
        assert filled["url_template"] == "https://proxy.example.com/v1"
        assert filled["llm"]["model"] == "deepseek-chat"
        assert "api_key" not in json.dumps(filled)

    def test_keeps_explicit_values(self):
        conn = LlmConnection(base_url="https://proxy.example.com", model="deepseek-chat")
        spec = {"url_template": "https://custom.example.com", "llm": {"model": "custom-model", "temperature": 0.5}}
        filled = resolve_request_spec_defaults(spec, conn)
        assert filled["url_template"] == "https://custom.example.com"
        assert filled["llm"] == {"model": "custom-model", "temperature": 0.5}

    def test_does_not_mutate_input(self):
        conn = LlmConnection()
        spec: dict[str, object] = {"prompt": {"user_template": "x"}}
        resolve_request_spec_defaults(spec, conn)
        assert spec == {"prompt": {"user_template": "x"}}
