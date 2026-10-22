"""datasource M2：REST 端点测试（providers / sync-jobs CRUD / run / preview / runs）."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import MetaData, func, select

from cndb.core.crypto import encrypt_secret, encrypt_secrets
from cndb.plugins.accounts.models import User
from cndb.plugins.datasource.models import (
    DatasourceLlmConfig,
    DatasourceSession,
    DatasourceSyncJob,
    DatasourceSyncRun,
)
from cndb.plugins.datasource.providers.llm_prompt import LlmConnectionResult
from cndb.plugins.datasource.routers import sync_jobs
from cndb.plugins.datasource.services import runner
from cndb.plugins.datasource.services.normalize import NormalizeResult
from cndb.plugins.datasource.services.pipeline import FetchFailure, PipelineOutcome
from cndb.plugins.datasource.services.scheduler import acquire_lease
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def workspace_with_auth(client, db):
    """工作区 + OWNER 登录 token."""
    user = User(username="ds_user", nickname="DS User")
    user.set_password("passw0rd")
    db.add(user)
    db.flush()
    ws = Workspace(name="DS-WS", created_by_id=user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER))
    db.commit()
    response = client.post("/api/v1/accounts/auth/login", json={"login": "ds_user", "password": "passw0rd"})
    return ws.id, {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def fake_pipeline(monkeypatch):
    """替换 runner.run_pipeline，避免端点测试真实联网."""
    rows = [{"city": "北京", "day": "2024-06-30", "temp": 30.0}]

    def fake(job, *, provider=None, fetch=None, rate_limit_ms=0, sleep=None):
        normalize = NormalizeResult(rows=[dict(row) for row in rows])
        return PipelineOutcome(rows=[dict(row) for row in rows], plans=1, succeeded=1, failures=[], normalize=normalize)

    monkeypatch.setattr(runner, "run_pipeline", fake)
    return rows


@pytest.fixture
def table_with_fields(db, db_engine, workspace_with_auth) -> DataTable:
    wid, _ = workspace_with_auth
    table = DataTable(workspace_id=wid, name="天气日表")
    table.ensure_db_name()
    db.add(table)
    db.commit()
    db.refresh(table)
    for order, (name, field_type) in enumerate((("city", "text"), ("day", "date"), ("temp", "float"))):
        field = DataField(table_id=table.id, name=name, field_type=field_type, order=order)
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(table)
    ddl.create_table(db_engine, table)
    return table


@pytest.fixture
def llm_connection_config(db, workspace_with_auth):
    """工作区级大模型连接（已配置 Key），供 llm_prompt 任务创建 / 连通测试用."""
    wid, _ = workspace_with_auth
    config = DatasourceLlmConfig(
        workspace_id=wid,
        base_url="https://llm.example.com",
        model="model-a",
        api_key=encrypt_secret("sk-conn"),
        system_prompt="",
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "天气同步",
        "provider": "http_json",
        "request_spec": {"url_template": "https://api.example.com/w?city={city}"},
        "entrant_param": "city",
        "entrant_keys": ["北京"],
        "cursor": {"strategy": "none"},
        "schedule": {"mode": "manual"},
    }
    payload.update(overrides)
    return payload


class TestProviders:
    def test_lists_builtin(self, client, workspace_with_auth):
        wid, headers = workspace_with_auth
        response = client.get(f"/api/v1/workspaces/{wid}/datasource/providers", headers=headers)
        assert response.status_code == 200
        names = [item["name"] for item in response.json()["providers"]]
        assert "http_json" in names


class TestCreate:
    def test_create_ok(self, client, workspace_with_auth):
        wid, headers = workspace_with_auth
        response = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=_payload(), headers=headers)
        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "天气同步"
        assert body["enabled"] is True
        assert body["last_status"] == ""

    def test_create_rejects_bad_request_spec(self, client, workspace_with_auth):
        wid, headers = workspace_with_auth
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sync-jobs",
            json=_payload(request_spec={}),
            headers=headers,
        )
        assert response.status_code == 400
        assert "url_template" in response.json()["detail"]

    def test_create_rejects_unknown_provider(self, client, workspace_with_auth):
        wid, headers = workspace_with_auth
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=_payload(provider="nope"), headers=headers
        )
        assert response.status_code == 400

    def test_create_rejects_bad_cursor_and_schedule(self, client, workspace_with_auth):
        wid, headers = workspace_with_auth
        assert (
            client.post(
                f"/api/v1/workspaces/{wid}/datasource/sync-jobs",
                json=_payload(cursor={"strategy": "weekly"}),
                headers=headers,
            ).status_code
            == 400
        )
        assert (
            client.post(
                f"/api/v1/workspaces/{wid}/datasource/sync-jobs",
                json=_payload(schedule={"mode": "cron", "expr": "bad"}),
                headers=headers,
            ).status_code
            == 400
        )

    def test_create_rejects_foreign_table(self, client, workspace_with_auth):
        wid, headers = workspace_with_auth
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=_payload(table_id=999), headers=headers
        )
        assert response.status_code == 400
        assert "目标表不存在" in response.json()["detail"]

    def test_create_rejects_unknown_match_key(self, client, workspace_with_auth, table_with_fields):
        wid, headers = workspace_with_auth
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sync-jobs",
            json=_payload(table_id=table_with_fields.id, match_keys=["nope"]),
            headers=headers,
        )
        assert response.status_code == 400
        assert "幂等键" in response.json()["detail"]

    def test_create_and_run_immediately(self, client, workspace_with_auth, table_with_fields, fake_pipeline):
        wid, headers = workspace_with_auth
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sync-jobs",
            json=_payload(table_id=table_with_fields.id, match_keys=["city", "day"], run_immediately=True),
            headers=headers,
        )
        assert response.status_code == 201
        assert response.json()["last_status"] == "success"

    def test_create_requires_editor(self, client, db, workspace_with_auth):
        wid, _ = workspace_with_auth
        viewer = User(username="ds_viewer", nickname="Viewer")
        viewer.set_password("passw0rd")
        db.add(viewer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        token = client.post("/api/v1/accounts/auth/login", json={"login": "ds_viewer", "password": "passw0rd"})
        headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
        response = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=_payload(), headers=headers)
        assert response.status_code == 403


class TestReadUpdateDelete:
    def test_list_and_detail(self, client, workspace_with_auth):
        wid, headers = workspace_with_auth
        created = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=_payload(), headers=headers).json()
        listing = client.get(f"/api/v1/workspaces/{wid}/datasource/sync-jobs", headers=headers)
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        detail = client.get(f"/api/v1/workspaces/{wid}/datasource/sync-jobs/{created['id']}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["name"] == "天气同步"

    def test_cross_workspace_blocked(self, client, workspace_with_auth, db):
        """非成员访问别的工作区任务被权限层拦下（403，不泄露存在性）."""
        wid, headers = workspace_with_auth
        created = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=_payload(), headers=headers).json()
        other = Workspace(name="other")
        db.add(other)
        db.commit()
        response = client.get(f"/api/v1/workspaces/{other.id}/datasource/sync-jobs/{created['id']}", headers=headers)
        assert response.status_code == 403

    def test_update_toggles_and_validates(self, client, workspace_with_auth):
        wid, headers = workspace_with_auth
        created = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=_payload(), headers=headers).json()
        url = f"/api/v1/workspaces/{wid}/datasource/sync-jobs/{created['id']}"
        updated = client.put(
            url, json={"enabled": False, "schedule": {"mode": "interval", "seconds": 600}}, headers=headers
        )
        assert updated.status_code == 200
        assert updated.json()["enabled"] is False
        assert updated.json()["schedule"]["seconds"] == 600
        bad = client.put(url, json={"schedule": {"mode": "weekly"}}, headers=headers)
        assert bad.status_code == 400

    def test_delete_removes_runs(self, client, db, workspace_with_auth, fake_pipeline):
        wid, headers = workspace_with_auth
        created = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=_payload(), headers=headers).json()
        client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs/{created['id']}/run", headers=headers)
        assert db.query(DatasourceSyncRun).count() == 1
        url = f"/api/v1/workspaces/{wid}/datasource/sync-jobs/{created['id']}"
        assert client.delete(url, headers=headers).status_code == 204
        assert client.get(url, headers=headers).status_code == 404
        assert db.query(DatasourceSyncRun).count() == 0


class TestRunPreview:
    def test_run_writes_rows(self, client, db_engine, workspace_with_auth, table_with_fields, fake_pipeline):
        wid, headers = workspace_with_auth
        created = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sync-jobs",
            json=_payload(table_id=table_with_fields.id, match_keys=["city", "day"]),
            headers=headers,
        ).json()
        response = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs/{created['id']}/run", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["run"]["status"] == "success"
        assert body["run"]["inserted"] == 1
        assert body["job"]["last_status"] == "success"

        metadata = MetaData()
        sa_table = ddl.build_sa_table(metadata, table_with_fields)
        with db_engine.connect() as conn:
            assert int(conn.execute(select(func.count()).select_from(sa_table)).scalar_one()) == 1

    def test_run_conflicts_when_leased(self, client, db, workspace_with_auth):
        wid, headers = workspace_with_auth
        created = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=_payload(), headers=headers).json()
        assert acquire_lease(db, created["id"], "other", now=dt.datetime.now(dt.UTC))
        response = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs/{created['id']}/run", headers=headers)
        assert response.status_code == 409

    def test_run_history(self, client, workspace_with_auth, fake_pipeline):
        wid, headers = workspace_with_auth
        created = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=_payload(), headers=headers).json()
        client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs/{created['id']}/run", headers=headers)
        runs = client.get(f"/api/v1/workspaces/{wid}/datasource/sync-jobs/{created['id']}/runs", headers=headers)
        assert runs.status_code == 200
        assert runs.json()["total"] == 1
        assert runs.json()["runs"][0]["trigger"] == "manual"

    def test_preview_does_not_write(self, client, db, workspace_with_auth, fake_pipeline):
        wid, headers = workspace_with_auth
        created = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=_payload(), headers=headers).json()
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sync-jobs/{created['id']}/preview",
            json={"limit": 10},
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["rows"][0]["city"] == "北京"
        assert db.query(DatasourceSyncRun).count() == 0

    def test_preview_reports_partial(self, client, workspace_with_auth, monkeypatch):
        wid, headers = workspace_with_auth
        created = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=_payload(), headers=headers).json()

        def fake(job, *, provider=None, fetch=None, rate_limit_ms=0, sleep=None):
            outcome = PipelineOutcome(rows=[], plans=2, succeeded=1, failures=[], normalize=NormalizeResult())
            outcome.failures.append(FetchFailure(label="city=上海", error="HTTP 500"))
            return outcome

        monkeypatch.setattr(runner, "run_pipeline", fake)
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sync-jobs/{created['id']}/preview",
            json={"limit": 5},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "partial"
        assert response.json()["failures"][0]["label"] == "city=上海"


def _llm_payload(**overrides: Any) -> dict[str, Any]:
    payload = _payload(
        provider="llm_prompt",
        request_spec={
            "url_template": "https://llm.example.com",
            "prompt": {"system": "你是数据助手", "user_template": "生成 {today} 的摘要"},
            "llm": {"model": "model-a", "temperature": 0.2},
        },
        entrant_param=None,
        entrant_keys=[],
        match_keys=["day"],
        schedule={"mode": "cron", "expr": "0 7 * * *"},
    )
    payload.update(overrides)
    return payload


class TestLlmPrompt:
    def test_provider_is_listed_with_schema(self, client, workspace_with_auth):
        wid, headers = workspace_with_auth
        response = client.get(f"/api/v1/workspaces/{wid}/datasource/providers", headers=headers)
        provider = next(item for item in response.json()["providers"] if item["name"] == "llm_prompt")
        assert provider["supports_paging"] is False
        assert provider["default_cursor"] == "none"
        assert "user_template" in [field["name"] for field in provider["params_schema"]["fields"]]

    def test_create_ok(self, client, workspace_with_auth, llm_connection_config):
        wid, headers = workspace_with_auth
        response = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=_llm_payload(), headers=headers)
        assert response.status_code == 201
        body = response.json()
        assert body["provider"] == "llm_prompt"
        assert body["request_spec"]["llm"]["model"] == "model-a"

    def test_create_prompt_only_uses_connection_defaults(self, client, workspace_with_auth, llm_connection_config):
        """ADR 0019：任务只填用户提示词，地址 / 模型从工作区连接补齐后落库."""
        wid, headers = workspace_with_auth
        payload = _llm_payload(
            request_spec={"prompt": {"user_template": "生成 {today} 的市场摘要"}},
            match_keys=[],
            schedule={"mode": "manual"},
        )
        response = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=payload, headers=headers)
        assert response.status_code == 201
        spec = response.json()["request_spec"]
        assert spec["url_template"] == llm_connection_config.base_url
        assert spec["llm"]["model"] == llm_connection_config.model
        assert "api_key" not in spec

    def test_create_requires_api_key(self, client, workspace_with_auth):
        wid, headers = workspace_with_auth
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sync-jobs",
            json=_llm_payload(match_keys=[], schedule={"mode": "manual"}),
            headers=headers,
        )
        assert response.status_code == 400
        assert "大模型连接" in response.json()["detail"]
        assert "API Key" in response.json()["detail"]

    def test_create_accepts_cron_without_match_keys(self, client, workspace_with_auth, llm_connection_config):
        """ADR 0019：幂等键由运行期自动识别，cron 不再强制手填."""
        wid, headers = workspace_with_auth
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sync-jobs",
            json=_llm_payload(match_keys=[]),
            headers=headers,
        )
        assert response.status_code == 201
        assert response.json()["match_keys"] == []

    def test_create_accepts_session_api_key(self, client, db, workspace_with_auth):
        """存量任务口径：会话里带 api_key 时无需工作区连接也能保存."""
        wid, headers = workspace_with_auth
        session = DatasourceSession(
            workspace_id=wid,
            name="LLM",
            headers={},
            secrets=encrypt_secrets({"api_key": "sk-test"}),
        )
        db.add(session)
        db.commit()
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sync-jobs",
            json=_llm_payload(session_id=session.id),
            headers=headers,
        )
        assert response.status_code == 201

    def test_rejects_empty_user_template(self, client, workspace_with_auth, llm_connection_config):
        wid, headers = workspace_with_auth
        spec = _llm_payload()["request_spec"]
        spec["prompt"] = {"system": "", "user_template": ""}
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sync-jobs",
            json=_llm_payload(request_spec=spec),
            headers=headers,
        )
        assert response.status_code == 400
        assert "user_template" in response.json()["detail"]

    def test_accepts_json_example_in_user_prompt(self, client, workspace_with_auth, llm_connection_config):
        """ADR 0019：用户提示词直接写 JSON 示例（裸花括号）也能保存."""
        wid, headers = workspace_with_auth
        user_template = '请按 {"rows": [{"city": "北京", "date": "{today}"}]} 的格式输出数据'
        payload = _llm_payload(
            request_spec={"prompt": {"user_template": user_template}},
            match_keys=[],
            schedule={"mode": "manual"},
        )
        response = client.post(f"/api/v1/workspaces/{wid}/datasource/sync-jobs", json=payload, headers=headers)
        assert response.status_code == 201
        assert response.json()["request_spec"]["prompt"]["user_template"] == user_template

    def test_connection_uses_session_key_and_has_no_side_effect(self, client, db, workspace_with_auth, monkeypatch):
        wid, headers = workspace_with_auth
        session = DatasourceSession(
            workspace_id=wid,
            name="LLM",
            headers={"X-Tenant": "t1"},
            secrets=encrypt_secrets({"api_key": "sk-test"}),
        )
        db.add(session)
        db.commit()
        captured: dict[str, Any] = {}

        def fake(spec, *, api_key, session_headers=None, fetch=None):
            captured.update(spec=spec, api_key=api_key, headers=session_headers)
            return LlmConnectionResult(ok=True, latency_ms=12, model="model-a", message="连通成功")

        monkeypatch.setattr(sync_jobs, "test_llm_connection", fake)
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/test-connection",
            json={"request_spec": _llm_payload()["request_spec"], "session_id": session.id},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True, "latency_ms": 12, "model": "model-a", "message": "连通成功"}
        assert captured["api_key"] == "sk-test"
        assert captured["headers"] == {"X-Tenant": "t1"}
        assert db.query(DatasourceSyncRun).count() == 0
        assert db.query(DatasourceSyncJob).count() == 0

    def test_connection_failure_is_reported(self, client, db, workspace_with_auth, monkeypatch):
        wid, headers = workspace_with_auth
        session = DatasourceSession(
            workspace_id=wid,
            name="LLM",
            headers={},
            secrets=encrypt_secrets({"api_key": "bad"}),
        )
        db.add(session)
        db.commit()
        monkeypatch.setattr(
            sync_jobs,
            "test_llm_connection",
            lambda *args, **kwargs: LlmConnectionResult(ok=False, latency_ms=3, message="API 返回 401"),
        )
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/test-connection",
            json={"request_spec": _llm_payload()["request_spec"], "session_id": session.id},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert "401" in response.json()["message"]

    def test_connection_rejects_missing_session(self, client, workspace_with_auth):
        wid, headers = workspace_with_auth
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/test-connection",
            json={"request_spec": _llm_payload()["request_spec"], "session_id": 9999},
            headers=headers,
        )
        assert response.status_code == 400
        assert "凭证会话不存在" in response.json()["detail"]

    def test_connection_falls_back_to_workspace_connection(
        self, client, db, workspace_with_auth, llm_connection_config, monkeypatch
    ):
        """ADR 0019：不传 session 时用工作区连接 Key 与默认地址 / 模型."""
        wid, headers = workspace_with_auth
        captured: dict[str, Any] = {}

        def fake(spec, *, api_key, session_headers=None, fetch=None):
            captured.update(spec=spec, api_key=api_key, headers=session_headers)
            return LlmConnectionResult(ok=True, latency_ms=9, model="model-a", message="连通成功")

        monkeypatch.setattr(sync_jobs, "test_llm_connection", fake)
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/test-connection",
            json={"request_spec": {"prompt": {"user_template": "ping"}}},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert captured["api_key"] == "sk-conn"
        assert captured["headers"] is None
        assert captured["spec"].url_template == llm_connection_config.base_url
        assert captured["spec"].llm["model"] == llm_connection_config.model

    def test_connection_without_any_key_reports_hint(self, client, workspace_with_auth):
        """工作区连接与会话都没有 Key 时给出指向「大模型连接」的提示（不联网）."""
        wid, headers = workspace_with_auth
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/test-connection",
            json={"request_spec": {"prompt": {"user_template": "ping"}}},
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert "大模型连接" in body["message"]

    def test_connection_rejects_bad_url(self, client, workspace_with_auth):
        wid, headers = workspace_with_auth
        spec = _llm_payload()["request_spec"]
        spec["url_template"] = "ftp://bad.example.com"
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/test-connection",
            json={"request_spec": spec},
            headers=headers,
        )
        assert response.status_code == 400
