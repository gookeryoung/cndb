"""ADR 0014：llm_prompt provider 单测（请求构造 / JSON 解析 / 校验 / 连通测试）."""

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
    JSON_INSTRUCTION,
    LlmPromptProvider,
    normalize_endpoint,
    strip_json_fences,
    validate_llm_request_spec,
)
from cndb.plugins.datasource.providers.llm_prompt import (
    test_llm_connection as run_connection_test,
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

    def test_missing_variable_raises(self):
        spec = _spec(prompt={"system": "", "user_template": "缺少 {unknown}"})
        with pytest.raises(ProviderError, match="模板变量缺失"):
            PROVIDER.build_requests(_job(request=spec))


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
            ({"url_template": "https://x", "prompt": {"user_template": "x"}, "llm": {"model": ""}}, "model"),
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
            (
                {"url_template": "https://x", "prompt": {"user_template": "{unknown}"}, "llm": {"model": "m"}},
                "模板变量缺失",
            ),
        ],
    )
    def test_invalid_payload(self, payload, match):
        with pytest.raises(ProviderError, match=match):
            validate_llm_request_spec(payload, entrant_param="city")

    def test_cron_requires_match_keys(self):
        payload = {
            "url_template": "https://x",
            "prompt": {"user_template": "生成 {today}"},
            "llm": {"model": "m"},
        }
        with pytest.raises(ProviderError, match="match_keys"):
            validate_llm_request_spec(payload, schedule={"mode": "cron"}, match_keys=[])

    def test_start_end_require_range_window(self):
        payload = {
            "url_template": "https://x",
            "prompt": {"user_template": "区间 {start} ~ {end}"},
            "llm": {"model": "m"},
        }
        with pytest.raises(ProviderError, match="模板变量缺失"):
            validate_llm_request_spec(payload)
        config = validate_llm_request_spec({**payload, "time_window": {"mode": "range"}})
        assert config.model == "m"

    def test_entrant_requires_entrant_param(self):
        payload = {
            "url_template": "https://x",
            "prompt": {"user_template": "生成 {entrant}"},
            "llm": {"model": "m"},
        }
        with pytest.raises(ProviderError, match="模板变量缺失"):
            validate_llm_request_spec(payload)
        assert validate_llm_request_spec(payload, entrant_param="city").model == "m"


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

    def test_fetch_error_is_returned(self):
        def fetch(_config: FetchConfig):
            raise ValueError("API 返回 401: invalid key")

        result = run_connection_test(_spec(), api_key="sk-test", fetch=fetch)
        assert result.ok is False
        assert "401" in result.message

    def test_invalid_config_is_returned(self):
        result = run_connection_test(_spec(llm={"model": ""}), api_key="sk-test")
        assert result.ok is False
        assert "model" in result.message
