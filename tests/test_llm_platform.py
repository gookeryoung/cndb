"""ADR 0020 P0：大模型能力平台（传输层重试 / 客户端 / 解析 / 网关 / 动作 / 留痕 / 迁移）."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine

from cndb.core.http import FetchConfig, fetch_json, validate_url
from cndb.plugins.accounts.models import User
from cndb.plugins.llm.models import LlmRun, LlmUserConfig
from cndb.plugins.llm.services import actions as action_registry
from cndb.plugins.llm.services import client as llm_client
from cndb.plugins.llm.services import gateway
from cndb.plugins.llm.services.connection import LlmConnection
from cndb.plugins.llm.services.errors import (
    LlmNotConfigured,
    LlmOutputInvalid,
    LlmRateLimited,
    LlmUpstreamError,
)
from cndb.plugins.llm.services.parsing import (
    looks_truncated,
    parse_chat_response,
    parse_content,
    strip_json_fences,
)
from cndb.plugins.llm.services.prompts import DEFAULT_MAX_TOKENS

# ── core.http：可重试状态码 + SSRF 白名单 ───────────────


class _FakeResponse:
    def __init__(self, status: int, text: str = "{}", headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = headers or {}


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def request(self, **kwargs: Any) -> _FakeResponse:
        return self._responses.pop(0)


def _patch_http(monkeypatch: pytest.MonkeyPatch, responses: list[_FakeResponse], sleeps: list[float]) -> None:
    from cndb.core import http as core_http

    monkeypatch.setattr(core_http.httpx2, "Client", lambda **kwargs: _FakeClient(responses))
    monkeypatch.setattr(core_http.time, "sleep", sleeps.append)


def _post_config(**overrides: Any) -> FetchConfig:
    defaults: dict[str, Any] = {
        "url": "https://llm.example.com/chat/completions",
        "method": "POST",
        "body": {"model": "m", "messages": []},
        "max_retries": 2,
        "retry_on_status": (429, 500, 502, 503, 504),
        "response_handler": lambda text, _config: [{"ok": True}],
    }
    defaults.update(overrides)
    return FetchConfig(**defaults)


class TestCoreHttpRetry:
    def test_post_retries_retryable_status_then_succeeds(self, monkeypatch):
        sleeps: list[float] = []
        _patch_http(monkeypatch, [_FakeResponse(429), _FakeResponse(200, '{"ok": true}')], sleeps)
        rows = fetch_json(_post_config())
        assert rows == [{"ok": True}]
        # 429 按「疑似限流」用长退避（2s 起步），与数据源既有口径一致
        assert sleeps == [2.0]

    def test_post_honors_retry_after(self, monkeypatch):
        sleeps: list[float] = []
        _patch_http(monkeypatch, [_FakeResponse(429, headers={"retry-after": "7"}), _FakeResponse(200)], sleeps)
        fetch_json(_post_config())
        assert sleeps == [7.0]

    def test_post_does_not_retry_non_retryable_status(self, monkeypatch):
        sleeps: list[float] = []
        _patch_http(monkeypatch, [_FakeResponse(400, "bad")], sleeps)
        with pytest.raises(ValueError, match="API 返回 400"):
            fetch_json(_post_config())
        assert sleeps == []

    def test_default_still_only_retries_get(self, monkeypatch):
        """其它 provider 不传 retry_on_status：POST 仍然不重试（行为不变）."""
        sleeps: list[float] = []
        _patch_http(monkeypatch, [_FakeResponse(429, "limited")], sleeps)
        with pytest.raises(ValueError, match="429"):
            fetch_json(_post_config(retry_on_status=()))
        assert sleeps == []


class TestCoreHttpAllowHosts:
    def test_private_host_blocked_by_default(self):
        with pytest.raises(ValueError, match="禁止访问"):
            validate_url("http://127.0.0.1:11434/v1/chat/completions")

    def test_explicit_allow_host_passes(self):
        assert validate_url("http://127.0.0.1:11434/v1/chat/completions", allow_hosts=("127.0.0.1",)) is None
        assert validate_url("http://localhost:11434", allow_hosts=("localhost",)) is None


# ── parsing：迁移后文案与截断识别保持一致 ───────────────


def _envelope(content: str, *, model: str = "model-a", usage: dict[str, int] | None = None) -> str:
    import json

    return json.dumps(
        {
            "model": model,
            "choices": [{"message": {"content": content}}],
            "usage": usage or {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }
    )


class TestParsing:
    def test_rows_forms(self):
        assert parse_chat_response(_envelope('{"a": 1}')) == [{"a": 1}]
        assert parse_chat_response(_envelope('[{"a": 1}, {"a": 2}]')) == [{"a": 1}, {"a": 2}]
        assert parse_chat_response(_envelope('{"rows": [{"a": 1}]}')) == [{"a": 1}]
        assert strip_json_fences('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_truncated_hint(self):
        truncated = '{"rows": [{"a": "被截断'
        with pytest.raises(LlmOutputInvalid, match=f"max_tokens（当前默认 {DEFAULT_MAX_TOKENS}）"):
            parse_content(truncated)

    def test_regular_syntax_error_keeps_message(self):
        with pytest.raises(LlmOutputInvalid, match="不是合法 JSON"):
            parse_content('{"a": 1 "b": 2}')

    def test_content_empty_raises(self):
        with pytest.raises(LlmOutputInvalid, match="content 为空"):
            parse_chat_response(_envelope(""))

    def test_looks_truncated_tail_only(self):
        import json

        try:
            json.loads('{"a": 1, "b": }')
        except json.JSONDecodeError as exc:
            assert looks_truncated(exc, '{"a": 1, "b": }') is True

    def test_metadata_captured(self):
        metadata: dict[str, Any] = {}
        parse_chat_response(_envelope('{"a": 1}', model="model-b"), metadata)
        assert metadata["model"] == "model-b"
        assert metadata["usage"]["total_tokens"] == 3


# ── client：重试配置注入 / 错误分类 / 连通测试 ───────────────


class TestLlmClient:
    def test_as_fetcher_injects_retry_policy_and_allowlist(self, monkeypatch):
        captured: dict[str, Any] = {}

        def fake_fetch(config: FetchConfig):
            captured["config"] = config
            return [{"ok": True}]

        monkeypatch.setattr(llm_client, "fetch_json", fake_fetch)
        fetcher = llm_client.as_fetcher()
        fetcher(FetchConfig(url="https://x", method="POST", body={}))
        config = captured["config"]
        assert config.retry_on_status == llm_client.RETRYABLE_STATUS
        assert config.max_retries == llm_client.MAX_RETRIES

    def test_complete_maps_429_to_rate_limited(self, monkeypatch):
        def fake_fetch(_config: FetchConfig):
            raise ValueError("API 返回 429: slow down")

        monkeypatch.setattr(llm_client, "fetch_json", fake_fetch)
        connection = LlmConnection(api_key="sk-test")
        with pytest.raises(LlmRateLimited):
            llm_client.complete(connection, messages=[{"role": "user", "content": "hi"}])

    def test_complete_maps_500_to_upstream_error(self, monkeypatch):
        def fake_fetch(_config: FetchConfig):
            raise ValueError("API 返回 500: boom")

        monkeypatch.setattr(llm_client, "fetch_json", fake_fetch)
        connection = LlmConnection(api_key="sk-test")
        with pytest.raises(LlmUpstreamError):
            llm_client.complete(connection, messages=[{"role": "user", "content": "hi"}])

    def test_complete_returns_content_and_usage(self, monkeypatch):
        def fake_fetch(config: FetchConfig):
            config.response_handler(_envelope("pong", model="model-b"), config)
            return []

        monkeypatch.setattr(llm_client, "fetch_json", fake_fetch)
        connection = LlmConnection(api_key="sk-test")
        response = llm_client.complete(connection, messages=[{"role": "user", "content": "hi"}])
        assert response.content == "pong"
        assert response.model == "model-b"
        assert response.usage["total_tokens"] == 3

    def test_complete_without_key_raises(self):
        with pytest.raises(LlmNotConfigured, match="个人设置"):
            llm_client.complete(LlmConnection(), messages=[{"role": "user", "content": "hi"}])

    def test_test_connection_without_key_hint(self):
        result = llm_client.test_connection(LlmConnection())
        assert result.ok is False
        assert "个人设置" in result.message


# ── gateway：schema 校验 / 留痕 / 失败零副作用 ───────────────


class _Out(BaseModel):
    text: str


@pytest.fixture
def llm_user(db):
    user = User(username="llm_gateway_user", nickname="LLM Gateway")
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestGateway:
    def _action(self, **overrides: Any) -> action_registry.ActionSpec:
        defaults: dict[str, Any] = {
            "name": "test.polish",
            "label": "测试润色",
            "output_schema": _Out,
            "system_prompt": '只输出 JSON：{"text": "..."}',
            "json_mode": True,
        }
        defaults.update(overrides)
        return action_registry.ActionSpec(**defaults)

    def test_invoke_success_records_run(self, db, llm_user, monkeypatch):
        monkeypatch.setattr(
            gateway.client,
            "complete",
            lambda *args, **kwargs: llm_client.LlmResponse(
                content='{"text": "ok"}', model="model-a", usage={"total_tokens": 9}
            ),
        )
        result = gateway.invoke(
            db,
            llm_user,
            self._action(),
            user_content="请润色",
            context=gateway.LlmContext(workspace_id=None, target_type="document", target_id=1),
        )
        assert result.parsed.text == "ok"
        assert result.run_id is not None
        run = db.query(LlmRun).filter(LlmRun.id == result.run_id).one()
        assert run.status == "success"
        assert run.total_tokens == 9
        assert run.action == "test.polish"
        assert "请润色" not in (run.detail or {})  # 不存正文

    def test_invoke_schema_error_records_failed_run(self, db, llm_user, monkeypatch):
        monkeypatch.setattr(
            gateway.client,
            "complete",
            lambda *args, **kwargs: llm_client.LlmResponse(content='{"wrong": 1}', model="model-a"),
        )
        with pytest.raises(LlmOutputInvalid):
            gateway.invoke(db, llm_user, self._action(), user_content="x")
        run = db.query(LlmRun).order_by(LlmRun.id.desc()).first()
        assert run is not None
        assert run.status == "failed"
        assert run.error

    def test_invoke_rejects_too_long_input(self, db, llm_user):
        with pytest.raises(LlmOutputInvalid, match="输入过长"):
            gateway.invoke(db, llm_user, self._action(max_input_chars=3), user_content="abcdef")


# ── 动作注册表 / 接口 ─────────────────────────────────


def _preserve_actions() -> list[action_registry.ActionSpec]:
    return action_registry.list_actions()


def _restore_actions(specs: list[action_registry.ActionSpec]) -> None:
    action_registry.reset_registry()
    for spec in specs:
        action_registry.register(spec)


class TestActionsRegistry:
    def test_register_get_catalog_and_reset(self):
        before = _preserve_actions()
        action_registry.reset_registry()
        try:
            action_registry.register(action_registry.ActionSpec(name="doc.polish", label="润色", scope="document"))
            assert action_registry.get("doc.polish") is not None
            assert action_registry.get("missing") is None
            assert action_registry.catalog() == [{"name": "doc.polish", "label": "润色", "scope": "document"}]
        finally:
            _restore_actions(before)

    def test_actions_endpoint_lists_registered(self, client, db):
        before = _preserve_actions()
        action_registry.reset_registry()
        try:
            action_registry.register(action_registry.ActionSpec(name="doc.summarize", label="摘要"))
            user = User(username="llm_actions_user", nickname="Actions")
            user.set_password("passw0rd")
            db.add(user)
            db.commit()
            login = client.post(
                "/api/v1/accounts/auth/login", json={"login": "llm_actions_user", "password": "passw0rd"}
            )
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            response = client.get("/api/v1/llm/actions", headers=headers)
            assert response.status_code == 200
            assert response.json()["items"] == [{"name": "doc.summarize", "label": "摘要", "scope": "personal"}]
        finally:
            _restore_actions(before)


class TestRunsEndpoint:
    def test_only_current_user_runs(self, client, db):
        mine = User(username="llm_runs_me", nickname="Me")
        mine.set_password("passw0rd")
        other = User(username="llm_runs_other", nickname="Other")
        other.set_password("passw0rd")
        db.add_all([mine, other])
        db.commit()
        db.refresh(mine)
        db.refresh(other)
        db.add_all(
            [
                LlmRun(user_id=mine.id, action="doc.polish", status="success", model="m", detail={}),
                LlmRun(user_id=other.id, action="doc.polish", status="success", model="m", detail={}),
            ]
        )
        db.commit()
        login = client.post("/api/v1/accounts/auth/login", json={"login": "llm_runs_me", "password": "passw0rd"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = client.get("/api/v1/llm/runs", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["action"] == "doc.polish"

    def test_old_accounts_endpoint_removed(self, client):
        assert client.get("/api/v1/accounts/llm-config").status_code == 404
        assert client.post("/api/v1/accounts/llm-config/test", json={}).status_code == 404


# ── 迁移：7b8c9d0e1f2a ──────────────────────────────


class TestLlmMigration:
    OLD = "datasource_user_llm_config"
    NEW = "llm_user_config"
    RUN = "llm_run"
    PREV = "6a7b8c9d0e1f"
    HEAD = "7b8c9d0e1f2a"

    @staticmethod
    def _tables(db_path: Path) -> set[str]:
        conn = sqlite3.connect(str(db_path))
        try:
            return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        finally:
            conn.close()

    def test_upgrade_moves_rows_and_drops_old(self, tmp_path: Path):
        from alembic import command

        from cndb.core.migrations import _build_config

        db_path = tmp_path / "mig_llm_up.db"
        url = f"sqlite:///{db_path}"
        command.upgrade(_build_config(url), self.PREV)
        assert self.OLD in self._tables(db_path)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                f"INSERT INTO {self.OLD} (user_id, base_url, model, api_key, system_prompt) VALUES (7, ?, ?, ?, ?)",
                ("https://a.example.com", "model-a", "enc:v1:secret", "自定义"),
            )
            conn.commit()
        finally:
            conn.close()

        command.upgrade(_build_config(url), self.HEAD)
        tables = self._tables(db_path)
        assert self.NEW in tables
        assert self.RUN in tables
        assert self.OLD not in tables
        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(f"SELECT user_id, base_url, model, api_key FROM {self.NEW}").fetchall()
        finally:
            conn.close()
        assert rows == [(7, "https://a.example.com", "model-a", "enc:v1:secret")]

    def test_downgrade_recreates_empty_old_table(self, tmp_path: Path):
        from alembic import command

        from cndb.core.migrations import _build_config

        db_path = tmp_path / "mig_llm_down.db"
        url = f"sqlite:///{db_path}"
        command.upgrade(_build_config(url), self.HEAD)
        command.downgrade(_build_config(url), self.PREV)
        tables = self._tables(db_path)
        assert self.OLD in tables
        assert self.NEW not in tables
        assert self.RUN not in tables
        conn = sqlite3.connect(str(db_path))
        try:
            assert conn.execute(f"SELECT COUNT(*) FROM {self.OLD}").fetchone()[0] == 0
        finally:
            conn.close()

    def test_upgrade_idempotent_after_create_all(self, tmp_path: Path):
        """create_all 时代已建过新表的库：upgrade 跳过建表、旧表不存在时直接返回."""
        from cndb.core.migrations import _build_config
        from cndb.models.base import Base as ModelBase

        db_path = tmp_path / "mig_llm_idem.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url)
        ModelBase.metadata.create_all(engine)
        engine.dispose()
        from alembic import command

        command.stamp(_build_config(url), self.PREV)
        command.upgrade(_build_config(url), self.HEAD)
        assert self.NEW in self._tables(db_path)
        assert self.RUN in self._tables(db_path)
        assert self.OLD not in self._tables(db_path)


# ── 插件注册 ───────────────────────────────────────


def test_llm_plugin_is_registered_without_app_entry():
    from cndb.core.plugin_registry import plugin_registry

    plugin = plugin_registry.get_plugin("llm")
    assert plugin is not None
    assert plugin.register_apps() == []
    assert plugin.register_navigation() == []
    # 依赖单向：llm 包内不得 import 领域插件
    import pkgutil
    import re
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parent.parent / "src" / "cndb" / "plugins" / "llm"
    pattern = re.compile(r"from cndb\.plugins\.(?!llm|accounts\.models|base)")
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(root)))
    assert offenders == []
    assert pkgutil is not None


def test_llm_user_config_model_table_name():
    assert LlmUserConfig.__tablename__ == "llm_user_config"
    assert LlmRun.__tablename__ == "llm_run"
