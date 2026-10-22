"""ADR 0019：**个人**「大模型连接」接口测试（CRUD / 用户隔离 / 加密不回显 / 默认值 / 清除 / 连通测试）."""

from __future__ import annotations

import json
from typing import Any

import pytest

from cndb.core.crypto import decrypt_secret, encrypt_secret, is_encrypted
from cndb.plugins.accounts.models import User
from cndb.plugins.datasource.models import UserLlmConfig
from cndb.plugins.datasource.providers.llm_prompt import DEFAULT_SYSTEM_PROMPT, LlmConnectionResult
from cndb.plugins.datasource.services.connection import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    find_user_llm_config,
    load_llm_connection,
)


@pytest.fixture
def personal_user(client, db):
    """一个登录用户（个人接口不要求工作区 / 工作区权限）."""
    user = User(username="llm_personal", nickname="LLM Personal")
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    response = client.post("/api/v1/accounts/auth/login", json={"login": "llm_personal", "password": "passw0rd"})
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    return user, headers


def _url() -> str:
    return "/api/v1/accounts/llm-config"


def _make_user(db, username: str) -> User:
    user = User(username=username, nickname=username)
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestGetUserLlmConfig:
    def test_defaults_when_not_configured(self, client, personal_user):
        _user, headers = personal_user
        response = client.get(_url(), headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["configured"] is False
        assert body["base_url"] == DEFAULT_BASE_URL
        assert body["model"] == DEFAULT_MODEL
        assert body["has_api_key"] is False
        assert body["system_prompt"] == ""
        assert body["default_system_prompt"] == DEFAULT_SYSTEM_PROMPT
        # 响应结构里不存在 api_key 字段（只回 has_api_key）
        assert "api_key" not in body

    def test_requires_login(self, client):
        assert client.get(_url()).status_code == 401

    def test_each_user_sees_own_config(self, client, db, personal_user):
        _user, headers = personal_user
        client.put(_url(), json={"model": "model-a", "api_key": "sk-a"}, headers=headers)
        other = _make_user(db, "llm_other")
        login = client.post("/api/v1/accounts/auth/login", json={"login": other.username, "password": "passw0rd"})
        other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        body = client.get(_url(), headers=other_headers).json()
        assert body["configured"] is False
        assert body["has_api_key"] is False

        own = client.get(_url(), headers=headers).json()
        assert own["configured"] is True
        assert own["model"] == "model-a"


class TestPutUserLlmConfig:
    def test_create_encrypts_api_key_and_does_not_echo_it(self, client, db, personal_user):
        user, headers = personal_user
        response = client.put(
            _url(),
            json={
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "api_key": "sk-plain",
                "system_prompt": "你只输出 JSON",
            },
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["configured"] is True
        assert body["base_url"] == "https://api.deepseek.com/v1"
        assert body["model"] == "deepseek-chat"
        assert body["has_api_key"] is True
        assert body["system_prompt"] == "你只输出 JSON"
        assert "api_key" not in body
        assert "sk-plain" not in json.dumps(body)

        row = db.query(UserLlmConfig).filter(UserLlmConfig.user_id == user.id).one()
        assert row.api_key != "sk-plain"
        assert is_encrypted(row.api_key)
        assert decrypt_secret(row.api_key) == "sk-plain"

    def test_create_with_minimal_payload_uses_defaults(self, client, personal_user):
        _user, headers = personal_user
        response = client.put(_url(), json={"api_key": "sk-plain"}, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["base_url"] == DEFAULT_BASE_URL
        assert body["model"] == DEFAULT_MODEL

    def test_update_without_api_key_keeps_existing(self, client, db, personal_user):
        user, headers = personal_user
        client.put(_url(), json={"api_key": "sk-plain", "model": "model-a"}, headers=headers)
        before = db.query(UserLlmConfig).filter(UserLlmConfig.user_id == user.id).one().api_key

        response = client.put(_url(), json={"base_url": "https://proxy.example.com"}, headers=headers)
        assert response.status_code == 200
        assert response.json()["has_api_key"] is True

        db.expire_all()
        row = db.query(UserLlmConfig).filter(UserLlmConfig.user_id == user.id).one()
        assert row.api_key == before
        assert row.base_url == "https://proxy.example.com"

    def test_clear_api_key(self, client, db, personal_user):
        user, headers = personal_user
        client.put(_url(), json={"api_key": "sk-plain"}, headers=headers)
        response = client.put(_url(), json={"clear_api_key": True}, headers=headers)
        assert response.status_code == 200
        assert response.json()["has_api_key"] is False
        row = db.query(UserLlmConfig).filter(UserLlmConfig.user_id == user.id).one()
        assert row.api_key == ""

    def test_empty_system_prompt_clears_override(self, client, personal_user):
        _user, headers = personal_user
        client.put(_url(), json={"system_prompt": "自定义"}, headers=headers)
        response = client.put(_url(), json={"system_prompt": ""}, headers=headers)
        assert response.status_code == 200
        assert response.json()["system_prompt"] == ""

    @pytest.mark.parametrize(
        ("payload", "match"),
        [
            ({"base_url": "ftp://x"}, "http"),
            ({"base_url": ""}, "不能为空"),
            ({"model": ""}, "模型"),
            ({"model": "   "}, "模型"),
        ],
    )
    def test_rejects_invalid_payload(self, client, personal_user, payload, match):
        _user, headers = personal_user
        response = client.put(_url(), json=payload, headers=headers)
        assert response.status_code == 400
        assert match in response.json()["detail"]

    def test_does_not_create_workspace_level_config(self, client, db, personal_user):
        """个人接口不写工作区表：只有 UserLlmConfig 一行."""
        user, headers = personal_user
        client.put(_url(), json={"api_key": "sk-plain"}, headers=headers)
        assert db.query(UserLlmConfig).filter(UserLlmConfig.user_id == user.id).count() == 1


class TestConnectionTest:
    def test_uses_saved_personal_key(self, client, db, personal_user, monkeypatch):
        _user, headers = personal_user
        client.put(
            _url(),
            json={"base_url": "https://llm.example.com", "model": "model-a", "api_key": "sk-saved"},
            headers=headers,
        )
        captured: dict[str, Any] = {}

        def fake(spec, *, api_key, session_headers=None, fetch=None):
            captured.update(spec=spec, api_key=api_key)
            return LlmConnectionResult(ok=True, latency_ms=12, model="model-a", message="连通成功")

        # 路由模块直接 import 了函数，替换其命名空间
        from cndb.plugins.accounts.routers import llm_config as llm_config_router

        monkeypatch.setattr(llm_config_router, "test_llm_connection", fake)
        response = client.post(_url() + "/test", json={}, headers=headers)
        assert response.status_code == 200
        assert response.json() == {"ok": True, "latency_ms": 12, "model": "model-a", "message": "连通成功"}
        assert captured["api_key"] == "sk-saved"
        assert captured["spec"].url_template == "https://llm.example.com"
        assert captured["spec"].llm["model"] == "model-a"

    def test_unsaved_overrides_used_and_not_persisted(self, client, db, personal_user, monkeypatch):
        user, headers = personal_user
        captured: dict[str, object] = {}

        def fake(spec, *, api_key, session_headers=None, fetch=None):
            captured.update(spec=spec, api_key=api_key)
            return LlmConnectionResult(ok=True, latency_ms=8, model="model-b", message="连通成功")

        from cndb.plugins.accounts.routers import llm_config as llm_config_router

        monkeypatch.setattr(llm_config_router, "test_llm_connection", fake)
        response = client.post(
            _url() + "/test",
            json={
                "base_url": "https://api.deepseek.com",
                "model": "model-b",
                "api_key": "sk-unsaved",
                "system_prompt": "临时系统提示词",
            },
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert captured["api_key"] == "sk-unsaved"
        assert captured["spec"].llm["model"] == "model-b"
        assert captured["spec"].prompt["system"] == "临时系统提示词"
        # 未保存的配置只用于本次请求，不产生任何连接
        assert db.query(UserLlmConfig).count() == 0
        assert find_user_llm_config(db, user.id) is None

    def test_without_any_key_reports_hint(self, client, personal_user):
        _user, headers = personal_user
        response = client.post(_url() + "/test", json={}, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert "个人设置" in body["message"]

    def test_rejects_bad_url(self, client, personal_user):
        _user, headers = personal_user
        response = client.post(_url() + "/test", json={"base_url": "ftp://bad.example.com"}, headers=headers)
        assert response.status_code == 400

    def test_rejects_empty_model(self, client, personal_user):
        _user, headers = personal_user
        response = client.post(_url() + "/test", json={"model": "  "}, headers=headers)
        assert response.status_code == 400


class TestLoadUserConnection:
    def test_defaults_without_record(self, db):
        conn = load_llm_connection(db, 99999)
        assert conn.base_url == DEFAULT_BASE_URL
        assert conn.model == DEFAULT_MODEL
        assert conn.api_key == ""
        assert conn.system_prompt == ""
        assert conn.has_api_key is False

    def test_reads_and_decrypts_record(self, db, personal_user):
        user, _headers = personal_user
        db.add(
            UserLlmConfig(
                user_id=user.id,
                base_url="https://proxy.example.com",
                model="model-a",
                api_key=encrypt_secret("sk-secret"),
                system_prompt="自定义系统提示词",
            )
        )
        db.commit()

        conn = load_llm_connection(db, user.id)
        assert conn.base_url == "https://proxy.example.com"
        assert conn.model == "model-a"
        assert conn.api_key == "sk-secret"
        assert conn.has_api_key is True
        assert conn.system_prompt == "自定义系统提示词"

    def test_missing_key_is_not_configured(self, db, personal_user):
        user, _headers = personal_user
        db.add(UserLlmConfig(user_id=user.id, base_url="", model="", api_key="", system_prompt=""))
        db.commit()
        conn = load_llm_connection(db, user.id)
        # 空地址 / 模型回内置默认，空 Key 视为未配置
        assert conn.base_url == DEFAULT_BASE_URL
        assert conn.model == DEFAULT_MODEL
        assert conn.has_api_key is False

    def test_corrupted_ciphertext_treated_as_missing(self, db, personal_user):
        user, _headers = personal_user
        db.add(
            UserLlmConfig(
                user_id=user.id,
                base_url=DEFAULT_BASE_URL,
                model=DEFAULT_MODEL,
                api_key="enc:v1:not-a-valid-token",
                system_prompt="",
            )
        )
        db.commit()
        conn = load_llm_connection(db, user.id)
        assert conn.has_api_key is False


def test_find_user_llm_config_returns_none_without_record(db):
    """find_user_llm_config 供接口 / 运行期使用：无记录返回 None（而不是默认对象）."""
    assert find_user_llm_config(db, 123456) is None
