"""ADR 0019：工作区级「大模型连接」接口测试（CRUD / 权限 / 加密不回显 / 默认值 / 清除）."""

from __future__ import annotations

import pytest

from cndb.core.crypto import decrypt_secret, encrypt_secret, is_encrypted
from cndb.plugins.accounts.models import User
from cndb.plugins.datasource.models import DatasourceLlmConfig
from cndb.plugins.datasource.providers.llm_prompt import DEFAULT_SYSTEM_PROMPT
from cndb.plugins.datasource.services.connection import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    find_llm_connection,
    load_llm_connection,
)
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def workspace_with_auth(client, db):
    """工作区 + OWNER 登录 token."""
    user = User(username="llm_user", nickname="LLM User")
    user.set_password("passw0rd")
    db.add(user)
    db.flush()
    ws = Workspace(name="LLM-WS", created_by_id=user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER))
    db.commit()
    response = client.post("/api/v1/accounts/auth/login", json={"login": "llm_user", "password": "passw0rd"})
    return ws.id, {"Authorization": f"Bearer {response.json()['access_token']}"}


def _url(wid: int) -> str:
    return f"/api/v1/workspaces/{wid}/datasource/llm-config"


class TestGetLlmConfig:
    def test_defaults_when_not_configured(self, client, workspace_with_auth):
        wid, headers = workspace_with_auth
        response = client.get(_url(wid), headers=headers)
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

    def test_viewer_can_read(self, client, db, workspace_with_auth):
        wid, _ = workspace_with_auth
        viewer = User(username="llm_viewer", nickname="Viewer")
        viewer.set_password("passw0rd")
        db.add(viewer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        login = client.post("/api/v1/accounts/auth/login", json={"login": "llm_viewer", "password": "passw0rd"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get(_url(wid), headers=headers).status_code == 200


class TestPutLlmConfig:
    def test_create_encrypts_api_key_and_does_not_echo_it(self, client, db, workspace_with_auth):
        wid, headers = workspace_with_auth
        response = client.put(
            _url(wid),
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

        row = db.query(DatasourceLlmConfig).filter(DatasourceLlmConfig.workspace_id == wid).one()
        assert row.api_key != "sk-plain"
        assert is_encrypted(row.api_key)
        assert decrypt_secret(row.api_key) == "sk-plain"

    def test_create_with_minimal_payload_uses_defaults(self, client, db, workspace_with_auth):
        wid, headers = workspace_with_auth
        response = client.put(_url(wid), json={"api_key": "sk-plain"}, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["base_url"] == DEFAULT_BASE_URL
        assert body["model"] == DEFAULT_MODEL

    def test_update_without_api_key_keeps_existing(self, client, db, workspace_with_auth):
        wid, headers = workspace_with_auth
        client.put(_url(wid), json={"api_key": "sk-plain", "model": "model-a"}, headers=headers)
        before = db.query(DatasourceLlmConfig).filter(DatasourceLlmConfig.workspace_id == wid).one().api_key

        response = client.put(_url(wid), json={"base_url": "https://proxy.example.com"}, headers=headers)
        assert response.status_code == 200
        assert response.json()["has_api_key"] is True

        db.expire_all()
        row = db.query(DatasourceLlmConfig).filter(DatasourceLlmConfig.workspace_id == wid).one()
        assert row.api_key == before
        assert row.base_url == "https://proxy.example.com"

    def test_clear_api_key(self, client, db, workspace_with_auth):
        wid, headers = workspace_with_auth
        client.put(_url(wid), json={"api_key": "sk-plain"}, headers=headers)
        response = client.put(_url(wid), json={"clear_api_key": True}, headers=headers)
        assert response.status_code == 200
        assert response.json()["has_api_key"] is False
        row = db.query(DatasourceLlmConfig).filter(DatasourceLlmConfig.workspace_id == wid).one()
        assert row.api_key == ""

    def test_empty_system_prompt_clears_override(self, client, db, workspace_with_auth):
        wid, headers = workspace_with_auth
        client.put(_url(wid), json={"system_prompt": "自定义"}, headers=headers)
        response = client.put(_url(wid), json={"system_prompt": ""}, headers=headers)
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
    def test_rejects_invalid_payload(self, client, workspace_with_auth, payload, match):
        wid, headers = workspace_with_auth
        response = client.put(_url(wid), json=payload, headers=headers)
        assert response.status_code == 400
        assert match in response.json()["detail"]

    def test_viewer_cannot_write(self, client, db, workspace_with_auth):
        wid, _ = workspace_with_auth
        viewer = User(username="llm_viewer2", nickname="Viewer")
        viewer.set_password("passw0rd")
        db.add(viewer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        login = client.post("/api/v1/accounts/auth/login", json={"login": "llm_viewer2", "password": "passw0rd"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = client.put(_url(wid), json={"model": "m"}, headers=headers)
        assert response.status_code == 403


class TestLoadConnection:
    def test_defaults_without_record(self, db):
        conn = load_llm_connection(db, 99999)
        assert conn.base_url == DEFAULT_BASE_URL
        assert conn.model == DEFAULT_MODEL
        assert conn.api_key == ""
        assert conn.system_prompt == ""
        assert conn.has_api_key is False

    def test_reads_and_decrypts_record(self, db, workspace_with_auth):
        wid, _ = workspace_with_auth
        db.add(
            DatasourceLlmConfig(
                workspace_id=wid,
                base_url="https://proxy.example.com",
                model="model-a",
                api_key=encrypt_secret("sk-secret"),
                system_prompt="自定义系统提示词",
            )
        )
        db.commit()

        conn = load_llm_connection(db, wid)
        assert conn.base_url == "https://proxy.example.com"
        assert conn.model == "model-a"
        assert conn.api_key == "sk-secret"
        assert conn.has_api_key is True
        assert conn.system_prompt == "自定义系统提示词"

    def test_missing_key_is_not_configured(self, db, workspace_with_auth):
        wid, _ = workspace_with_auth
        db.add(
            DatasourceLlmConfig(
                workspace_id=wid,
                base_url="",
                model="",
                api_key="",
                system_prompt="",
            )
        )
        db.commit()
        conn = load_llm_connection(db, wid)
        # 空地址 / 模型回内置默认，空 Key 视为未配置
        assert conn.base_url == DEFAULT_BASE_URL
        assert conn.model == DEFAULT_MODEL
        assert conn.has_api_key is False

    def test_corrupted_ciphertext_treated_as_missing(self, db, workspace_with_auth):
        wid, _ = workspace_with_auth
        db.add(
            DatasourceLlmConfig(
                workspace_id=wid,
                base_url=DEFAULT_BASE_URL,
                model=DEFAULT_MODEL,
                api_key="enc:v1:not-a-valid-token",
                system_prompt="",
            )
        )
        db.commit()
        conn = load_llm_connection(db, wid)
        assert conn.has_api_key is False


def test_find_llm_connection_returns_none_for_workspace_without_config(db):
    """find_llm_connection 供备份导出使用：无记录返回 None（而不是默认对象）."""
    assert find_llm_connection(db, 123456) is None
