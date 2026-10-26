"""datasource M5：凭证会话 / 请求限速 / 列式记录 / 领域模板包.

覆盖：
- ``columns_to_rows``：列式响应拼行（layout / 自动取列 / 长度不齐 / 异常）
- 会话 CRUD：密钥只写不回显、同名拒绝、删除解绑任务
- 运行时注入：会话 headers 铺底（job 覆盖）、secrets 作模板变量、job.rate_limit_ms 透传
- 领域模板包：按 provider 过滤，且全部能通过模板配置校验
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.plugins.accounts.models import User
from cndb.plugins.analytics.schemas import TemplateConfig
from cndb.plugins.analytics.services.templates import normalize_config
from cndb.plugins.datasource.models import DatasourceSession, DatasourceSyncJob
from cndb.plugins.datasource.providers.base import PagingSpec, ProviderError, RequestSpec, SyncJobSpec
from cndb.plugins.datasource.providers.http_json import HttpJsonProvider, columns_to_rows
from cndb.plugins.datasource.services import runner
from cndb.plugins.datasource.services.domain_templates import DOMAIN_TEMPLATES, list_domain_templates
from cndb.plugins.datasource.services.pipeline import run_pipeline
from cndb.plugins.tables.services.importing.api_fetch import FetchConfig
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

PROVIDER = HttpJsonProvider()


class TestColumnsToRows:
    DAILY = {
        "daily": {
            "time": ["2024-01-01", "2024-01-02"],
            "temperature_2m_max": [3.5, 4.1],
            "temperature_2m_min": [-4.0, -3.2],
        }
    }

    def test_auto_columns(self):
        rows = columns_to_rows(self.DAILY, "daily")
        assert rows == [
            {"time": "2024-01-01", "temperature_2m_max": 3.5, "temperature_2m_min": -4.0},
            {"time": "2024-01-02", "temperature_2m_max": 4.1, "temperature_2m_min": -3.2},
        ]

    def test_layout_renames(self):
        rows = columns_to_rows(
            self.DAILY,
            "daily",
            {"day": "time", "temp_max": "temperature_2m_max"},
        )
        assert rows[0] == {"day": "2024-01-01", "temp_max": 3.5}

    def test_missing_column_raises(self):
        with pytest.raises(ProviderError, match="缺少数组列"):
            columns_to_rows(self.DAILY, "daily", {"x": "nope"})

    def test_not_object_raises(self):
        with pytest.raises(ProviderError, match="指向一个对象"):
            columns_to_rows({"daily": [1, 2]}, "daily")

    def test_no_array_raises(self):
        with pytest.raises(ProviderError, match="未找到任何数组列"):
            columns_to_rows({"daily": {"a": 1}}, "daily")

    def test_uneven_columns_pad_none(self):
        rows = columns_to_rows({"a": [1, 2, 3], "b": ["x"]})
        assert rows[-1] == {"a": 3, "b": None}

    def test_parse_uses_columns_mode(self):
        job = SyncJobSpec(
            request=RequestSpec(
                url_template="https://api.example.com/w",
                data_path="daily",
                record_mode="columns",
                record_layout={"day": "time"},
            )
        )
        rows = PROVIDER.parse(json.dumps(self.DAILY), job)
        assert rows[0]["day"] == "2024-01-01"


@pytest.fixture
def owner_env(client, db):
    user = User(username="m5_owner", nickname="M5 Owner")
    user.set_password("passw0rd")
    db.add(user)
    db.flush()
    ws = Workspace(name="M5-WS", created_by_id=user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER))
    db.commit()
    response = client.post("/api/v1/accounts/auth/login", json={"login": "m5_owner", "password": "passw0rd"})
    return ws.id, {"Authorization": f"Bearer {response.json()['access_token']}"}


def _job_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "会话任务",
        "provider": "http_json",
        "request_spec": {"url_template": "https://api.example.com/w?k={api_key}"},
        "cursor": {"strategy": "none"},
        "schedule": {"mode": "manual"},
    }
    payload.update(overrides)
    return payload


class TestSessionApi:
    def test_create_list_hides_secret_values(self, client, owner_env):
        wid, headers = owner_env
        created = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sessions",
            json={"name": "行情源", "headers": {"User-Agent": "cndb"}, "secrets": {"api_key": "s3cr3t"}},
            headers=headers,
        )
        assert created.status_code == 201
        body = created.json()
        assert body["secret_keys"] == ["api_key"]
        assert "s3cr3t" not in str(body)

        listing = client.get(f"/api/v1/workspaces/{wid}/datasource/sessions", headers=headers)
        assert listing.json()["total"] == 1
        assert listing.json()["sessions"][0]["headers"] == {"User-Agent": "cndb"}

    def test_duplicate_name_rejected(self, client, owner_env):
        wid, headers = owner_env
        url = f"/api/v1/workspaces/{wid}/datasource/sessions"
        client.post(url, json={"name": "同名"}, headers=headers)
        again = client.post(url, json={"name": "同名"}, headers=headers)
        assert again.status_code == 400
        assert "已存在" in again.json()["detail"]

    def test_update_replaces_secrets(self, client, owner_env):
        wid, headers = owner_env
        sid = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sessions",
            json={"name": "S", "secrets": {"a": "1"}},
            headers=headers,
        ).json()["id"]
        updated = client.put(
            f"/api/v1/workspaces/{wid}/datasource/sessions/{sid}",
            json={"secrets": {"b": "2"}},
            headers=headers,
        )
        assert updated.json()["secret_keys"] == ["b"]

    def test_delete_unbinds_jobs(self, client, db, owner_env):
        wid, headers = owner_env
        sid = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sessions",
            json={"name": "S"},
            headers=headers,
        ).json()["id"]
        job = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sync-jobs",
            json=_job_payload(session_id=sid),
            headers=headers,
        )
        assert job.status_code == 201
        assert job.json()["session_id"] == sid

        assert client.delete(f"/api/v1/workspaces/{wid}/datasource/sessions/{sid}", headers=headers).status_code == 204
        db.expire_all()
        stored = db.query(DatasourceSyncJob).filter(DatasourceSyncJob.id == job.json()["id"]).one()
        assert stored.session_id is None

    def test_job_rejects_foreign_session(self, client, db, owner_env):
        wid, headers = owner_env
        other = DatasourceSession(workspace_id=wid + 99, name="别人的", headers={}, secrets={})
        db.add(other)
        db.commit()
        response = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sync-jobs",
            json=_job_payload(session_id=other.id),
            headers=headers,
        )
        assert response.status_code == 400
        assert "凭证会话不存在" in response.json()["detail"]

    def test_secrets_are_encrypted_at_rest(self, client, db, owner_env):
        """密钥列落库即密文：键名保留、值不可读，且能解回原文."""
        from cndb.core.crypto import decrypt_secret, is_encrypted

        wid, headers = owner_env
        sid = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sessions",
            json={"name": "加密", "secrets": {"api_key": "plain-value"}},
            headers=headers,
        ).json()["id"]

        db.expire_all()
        stored = db.get(DatasourceSession, sid)
        assert stored is not None
        cipher = stored.secrets["api_key"]
        assert "plain-value" not in cipher
        assert is_encrypted(cipher)
        assert decrypt_secret(cipher) == "plain-value"

    def test_update_also_encrypts(self, client, db, owner_env):
        from cndb.core.crypto import decrypt_secret, is_encrypted

        wid, headers = owner_env
        sid = client.post(
            f"/api/v1/workspaces/{wid}/datasource/sessions",
            json={"name": "S2", "secrets": {"a": "1"}},
            headers=headers,
        ).json()["id"]
        client.put(
            f"/api/v1/workspaces/{wid}/datasource/sessions/{sid}",
            json={"secrets": {"b": "2"}},
            headers=headers,
        )
        db.expire_all()
        stored = db.get(DatasourceSession, sid)
        assert stored is not None
        assert set(stored.secrets) == {"b"}
        assert is_encrypted(stored.secrets["b"])
        assert decrypt_secret(stored.secrets["b"]) == "2"


class TestSessionInjection:
    def _job(self, db: Session, session_id: int | None) -> DatasourceSyncJob:
        job = DatasourceSyncJob(
            workspace_id=1,
            name="带会话",
            provider="http_json",
            request_spec={
                "url_template": "https://api.example.com/w?k={api_key}",
                "headers_template": {"X-Trace": "job"},
            },
            entrant_keys=[],
            match_keys=[],
            field_mapping={},
            cursor={"strategy": "none"},
            schedule={"mode": "manual"},
            session_id=session_id,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    def test_headers_and_secrets_injected(self, db_engine, db):
        session = DatasourceSession(
            workspace_id=1,
            name="S",
            headers={"User-Agent": "cndb-sync", "X-Trace": "session"},
            secrets={"api_key": "tok123"},
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        job = self._job(db, session.id)

        seen: list[str] = []

        def fetch(config: FetchConfig) -> list[dict[str, Any]]:
            seen.append(config.url)
            assert config.headers["User-Agent"] == "cndb-sync"
            assert config.headers["X-Trace"] == "job"  # job 自己的同名头优先
            return []

        execution = runner.execute_job(db, job, fetch=fetch)
        assert execution.run.status == "success"
        assert seen == ["https://api.example.com/w?k=tok123"]

    def test_rate_limit_passed_to_pipeline(self, db_engine, db, monkeypatch):
        job = self._job(db, None)
        captured: dict[str, Any] = {}
        real = runner.run_pipeline

        def spy(
            spec: SyncJobSpec,
            *,
            provider=None,
            fetch=None,
            rate_limit_ms=0,
            sleep=None,
            on_batch=None,
            batch_size=5000,
            progress=None,
        ):
            captured["rate_limit_ms"] = rate_limit_ms
            return real(
                spec,
                provider=provider,
                fetch=fetch,
                rate_limit_ms=0,
                sleep=sleep,
                on_batch=on_batch,
                batch_size=batch_size,
                progress=progress,
            )

        monkeypatch.setattr(runner, "run_pipeline", spy)
        job.rate_limit_ms = 250
        db.add(job)
        db.commit()
        runner.execute_job(db, job, fetch=lambda _cfg: [])
        assert captured["rate_limit_ms"] == 250

    def test_legacy_plaintext_secret_still_works(self, db_engine, db):
        """加密上线前建的会话（明文密钥）不需要迁移即可继续跑."""
        session = DatasourceSession(
            workspace_id=1,
            name="历史会话",
            headers={},
            secrets={"api_key": "legacy-token"},
        )
        db.add(session)
        db.commit()
        job = self._job(db, session.id)

        seen: list[str] = []
        execution = runner.execute_job(db, job, fetch=lambda cfg: seen.append(cfg.url) or [])
        assert execution.run.status == "success"
        assert seen == ["https://api.example.com/w?k=legacy-token"]

    def test_decrypt_failure_lands_failed_run(self, db_engine, db, monkeypatch):
        """换过密钥的密文：运行必须显式失败并给出可读原因，而不是拿空密钥去打接口."""
        from cndb.core import crypto
        from cndb.core.crypto import encrypt_secrets

        session = DatasourceSession(
            workspace_id=1,
            name="旧密钥",
            headers={},
            secrets=encrypt_secrets({"api_key": "x"}),
        )
        db.add(session)
        db.commit()
        job = self._job(db, session.id)

        monkeypatch.setattr(settings, "DATASOURCE_SECRET_KEY", "rotated-key")
        crypto._fernet_for.cache_clear()

        calls: list[str] = []
        execution = runner.execute_job(db, job, fetch=lambda cfg: calls.append(cfg.url) or [])
        assert execution.run.status == "failed"
        assert "解密失败" in (execution.run.error_message or "")
        assert calls == []


class TestPipelineRateLimit:
    def test_waits_between_requests_only(self, monkeypatch):
        rows = [{"a": 1}]
        sleeps: list[float] = []
        clock = {"now": 100.0}

        def fake_sleep(delay: float) -> None:
            sleeps.append(round(delay, 6))
            clock["now"] += delay

        # 全局限速器按真实时钟预约出发时刻（ADR 0034 D5）；假 sleep 不推进时间，须一起假造时钟
        monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
        job = SyncJobSpec(
            request=RequestSpec(
                url_template="https://api.example.com/w?p={page}",
                paging=PagingSpec(mode="page", max_pages=3),
            )
        )
        run_pipeline(job, fetch=lambda _cfg: rows, rate_limit_ms=200, sleep=fake_sleep)
        # 3 个请求 → 只在第 2、3 次之前等待
        assert sleeps == [0.2, 0.2]

    def test_no_wait_by_default(self):
        sleeps: list[float] = []
        job = SyncJobSpec(
            request=RequestSpec(
                url_template="https://api.example.com/w?p={page}",
                paging=PagingSpec(mode="page", max_pages=2),
            )
        )
        run_pipeline(job, fetch=lambda _cfg: [{"a": 1}], sleep=sleeps.append)
        assert sleeps == []

    def test_skipped_pages_do_not_wait(self):
        sleeps: list[float] = []
        calls: list[str] = []

        def fetch(config: FetchConfig) -> list[dict[str, Any]]:
            calls.append(config.url)
            return [] if "p=1" in config.url else [{"a": 1}]

        job = SyncJobSpec(
            request=RequestSpec(
                url_template="https://api.example.com/w?p={page}",
                paging=PagingSpec(mode="page", max_pages=3),
            )
        )
        run_pipeline(job, fetch=fetch, rate_limit_ms=100, sleep=sleeps.append)
        assert len(calls) == 1  # 第 1 页为空即停止后续页
        assert sleeps == []


class TestDomainTemplates:
    def test_filter_by_provider(self):
        assert {item.provider for item in list_domain_templates("http_json")} == {"http_json"}
        assert list_domain_templates("llm_prompt") == []
        assert len(list_domain_templates()) == len(DOMAIN_TEMPLATES) > 0

    @pytest.mark.parametrize("template", DOMAIN_TEMPLATES, ids=lambda item: item.id)
    def test_templates_pass_config_validation(self, template):
        config = TemplateConfig.model_validate(
            {
                "formulas": template.formulas,
                "chart": template.chart,
                "summary": template.summary,
                "fields": [],
                "limit": 1000,
            }
        )
        # field_names=None：跳过字段存在性校验，只校验公式语法 / 聚合方式 / 汇总结构
        normalized = normalize_config(config, None)
        assert normalized["chart"] is not None

    def test_endpoint_returns_templates(self, client, owner_env):
        wid, headers = owner_env
        response = client.get(
            f"/api/v1/workspaces/{wid}/datasource/domain-templates?provider=http_json", headers=headers
        )
        assert response.status_code == 200
        templates = response.json()["templates"]
        assert [item["id"] for item in templates] == ["weather_daily"]
        assert templates[0]["summary"]["group_by"] == "city"
