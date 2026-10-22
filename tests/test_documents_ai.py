"""ADR 0020 P1：文档 AI 动作（选区改写 / 摘要 / 标签建议）.

覆盖：接口 wiring、权限（成员 / 非成员）、输入校验、输出 schema、平台留痕、失败零副作用。
模型调用用 monkeypatch 假响应，不触发真实网络。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.core.crypto import encrypt_secret
from cndb.plugins.accounts.models import User
from cndb.plugins.documents import services as doc_services
from cndb.plugins.llm.models import LlmRun, LlmUserConfig
from cndb.plugins.llm.services import client as llm_client
from cndb.plugins.llm.services import gateway
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

AI_URL = "/api/v1/workspaces/{ws}/documents/{doc}/ai/actions/{action}"


def _make_user(db: Session, username: str) -> User:
    user = User(username=username, nickname=username)
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _give_connection(db: Session, user: User, *, api_key: str = "sk-test") -> None:
    db.add(
        LlmUserConfig(
            user_id=user.id,
            base_url="https://llm.example.com",
            model="model-a",
            api_key=encrypt_secret(api_key),
            system_prompt="",
        )
    )
    db.commit()


@pytest.fixture
def ai_user(db) -> User:
    return _make_user(db, "doc_ai_user")


@pytest.fixture
def ai_ws(db, ai_user) -> Workspace:
    ws = Workspace(name="DocAI", created_by_id=ai_user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=ai_user.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(ws)
    return ws


@pytest.fixture
def ai_headers(client, ai_user) -> dict[str, str]:
    return _login(client, "doc_ai_user")


@pytest.fixture
def ai_doc(db, ai_ws, ai_user):
    return doc_services.content.create_document(
        db,
        ai_ws.id,
        ai_user,
        title="流程优化方案",
        content="## 一、现状\n\n现有流程有五个审批节点，周均处理时长 3.2 天。\n\n## 二、建议\n\n收敛到三个节点，并建立指标看板。",
        status="published",
    )


def _patch_complete(monkeypatch: pytest.MonkeyPatch, content: str, *, usage: dict[str, int] | None = None) -> None:
    monkeypatch.setattr(
        gateway.client,
        "complete",
        lambda *args, **kwargs: llm_client.LlmResponse(
            content=content,
            model="model-a",
            usage=usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        ),
    )


class TestPolish:
    def test_polish_returns_rewritten_text_and_records_run(
        self, client, db, ai_ws, ai_doc, ai_user, ai_headers, monkeypatch
    ):
        _give_connection(db, ai_user)
        _patch_complete(monkeypatch, '{"text": "该方案需重新梳理现有流程。"}')
        response = client.post(
            AI_URL.format(ws=ai_ws.id, doc=ai_doc.id, action="polish"),
            json={"selection": "该方案需要对现有流程进行重新梳理。", "instruction": "polish"},
            headers=ai_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["action"] == "document.polish"
        assert body["result"] == {"text": "该方案需重新梳理现有流程。"}
        assert body["run_id"]
        run = db.query(LlmRun).filter(LlmRun.id == body["run_id"]).one()
        assert run.action == "document.polish"
        assert run.status == "success"
        assert run.total_tokens == 15

    def test_polish_requires_selection(self, client, db, ai_ws, ai_doc, ai_user, ai_headers):
        _give_connection(db, ai_user)
        response = client.post(
            AI_URL.format(ws=ai_ws.id, doc=ai_doc.id, action="polish"),
            json={"selection": "   ", "instruction": "polish"},
            headers=ai_headers,
        )
        assert response.status_code == 400
        assert "选中" in response.json()["detail"]

    def test_polish_rejects_too_long_selection(self, client, db, ai_ws, ai_doc, ai_user, ai_headers):
        _give_connection(db, ai_user)
        response = client.post(
            AI_URL.format(ws=ai_ws.id, doc=ai_doc.id, action="polish"),
            json={"selection": "字" * 4001, "instruction": "polish"},
            headers=ai_headers,
        )
        assert response.status_code == 400
        assert "过长" in response.json()["detail"]

    def test_polish_rejects_unknown_instruction(self, client, db, ai_ws, ai_doc, ai_user, ai_headers):
        _give_connection(db, ai_user)
        response = client.post(
            AI_URL.format(ws=ai_ws.id, doc=ai_doc.id, action="polish"),
            json={"selection": "一段文字", "instruction": "delete-everything"},
            headers=ai_headers,
        )
        assert response.status_code == 400

    def test_polish_schema_error_has_no_side_effect(self, client, db, ai_ws, ai_doc, ai_user, ai_headers, monkeypatch):
        _give_connection(db, ai_user)
        _patch_complete(monkeypatch, '{"wrong": 1}')
        response = client.post(
            AI_URL.format(ws=ai_ws.id, doc=ai_doc.id, action="polish"),
            json={"selection": "一段文字", "instruction": "polish"},
            headers=ai_headers,
        )
        assert response.status_code == 422
        failed = db.query(LlmRun).filter(LlmRun.status == "failed").one()
        assert failed.action == "document.polish"
        # 文档正文未被修改
        db.refresh(ai_doc)
        version = doc_services.content.latest_version(db, ai_doc.id)
        assert "一段文字" not in doc_services.content.load_content(version, ai_doc)


class TestSummarizeAndTags:
    def test_summarize_returns_structured_result(self, client, db, ai_ws, ai_doc, ai_user, ai_headers, monkeypatch):
        _give_connection(db, ai_user)
        _patch_complete(
            monkeypatch,
            '{"summary": "本文给出流程优化建议。", "key_points": ["现状五个审批节点"], "suggested_tags": ["流程优化", "审批效率"]}',
        )
        response = client.post(
            AI_URL.format(ws=ai_ws.id, doc=ai_doc.id, action="summarize"),
            json={},
            headers=ai_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["action"] == "document.summarize"
        assert body["result"]["summary"] == "本文给出流程优化建议。"
        assert body["result"]["suggested_tags"] == ["流程优化", "审批效率"]
        assert body["truncated"] is False

    def test_summarize_truncates_long_document(self, client, db, ai_ws, ai_user, ai_headers, monkeypatch):
        _give_connection(db, ai_user)
        long_doc = doc_services.content.create_document(
            db, ai_ws.id, ai_user, title="长文", content="长" * 13000, status="published"
        )
        _patch_complete(monkeypatch, '{"summary": "长文摘要", "key_points": [], "suggested_tags": []}')
        response = client.post(
            AI_URL.format(ws=ai_ws.id, doc=long_doc.id, action="summarize"),
            json={},
            headers=ai_headers,
        )
        assert response.status_code == 200
        assert response.json()["truncated"] is True

    def test_suggest_tags_returns_tags(self, client, db, ai_ws, ai_doc, ai_user, ai_headers, monkeypatch):
        _give_connection(db, ai_user)
        _patch_complete(monkeypatch, '{"suggested_tags": ["流程优化", "指标看板"]}')
        response = client.post(
            AI_URL.format(ws=ai_ws.id, doc=ai_doc.id, action="suggest_tags"),
            json={},
            headers=ai_headers,
        )
        assert response.status_code == 200
        assert response.json()["result"]["suggested_tags"] == ["流程优化", "指标看板"]

    def test_empty_document_rejected(self, client, db, ai_ws, ai_user, ai_headers):
        _give_connection(db, ai_user)
        empty = doc_services.content.create_document(db, ai_ws.id, ai_user, title="空文档", content="")
        response = client.post(
            AI_URL.format(ws=ai_ws.id, doc=empty.id, action="summarize"),
            json={},
            headers=ai_headers,
        )
        assert response.status_code == 400
        assert "正文为空" in response.json()["detail"]


class TestPermissionsAndErrors:
    def test_non_member_denied(self, client, db, ai_ws, ai_doc, monkeypatch):
        _make_user(db, "doc_ai_outsider")
        headers = _login(client, "doc_ai_outsider")
        response = client.post(
            AI_URL.format(ws=ai_ws.id, doc=ai_doc.id, action="summarize"),
            json={},
            headers=headers,
        )
        assert response.status_code == 403

    def test_unknown_action_404(self, client, db, ai_ws, ai_doc, ai_user, ai_headers):
        _give_connection(db, ai_user)
        response = client.post(
            AI_URL.format(ws=ai_ws.id, doc=ai_doc.id, action="nope"),
            json={},
            headers=ai_headers,
        )
        assert response.status_code == 404

    def test_folder_rejected(self, client, db, ai_ws, ai_user, ai_headers):
        _give_connection(db, ai_user)
        folder = doc_services.content.create_document(db, ai_ws.id, ai_user, title="目录", is_folder=True)
        response = client.post(
            AI_URL.format(ws=ai_ws.id, doc=folder.id, action="summarize"),
            json={},
            headers=ai_headers,
        )
        assert response.status_code == 400

    def test_unconfigured_key_reports_setup_hint(self, client, db, ai_ws, ai_doc, ai_headers):
        response = client.post(
            AI_URL.format(ws=ai_ws.id, doc=ai_doc.id, action="summarize"),
            json={},
            headers=ai_headers,
        )
        assert response.status_code == 400
        assert "个人设置" in response.json()["detail"]

    def test_viewer_can_run_read_only_action(self, client, db, ai_ws, ai_doc, monkeypatch):
        viewer = _make_user(db, "doc_ai_viewer")
        db.add(WorkspaceMember(workspace_id=ai_ws.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        _give_connection(db, viewer)
        _patch_complete(monkeypatch, '{"summary": "摘要", "key_points": [], "suggested_tags": []}')
        headers = _login(client, "doc_ai_viewer")
        response = client.post(
            AI_URL.format(ws=ai_ws.id, doc=ai_doc.id, action="summarize"),
            json={},
            headers=headers,
        )
        assert response.status_code == 200


class TestActionCatalog:
    def test_document_actions_registered_in_platform_catalog(self, client, db, ai_user):
        headers = _login(client, "doc_ai_user")
        response = client.get("/api/v1/llm/actions", headers=headers)
        assert response.status_code == 200
        names = {item["name"] for item in response.json()["items"]}
        assert {"document.polish", "document.summarize", "document.suggest_tags"} <= names
