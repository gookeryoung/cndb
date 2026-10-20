"""datasource M2：REST 端点测试（providers / sync-jobs CRUD / run / preview / runs）."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import MetaData, func, select

from cndb.plugins.accounts.models import User
from cndb.plugins.datasource.models import DatasourceSyncRun
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

    def fake(job, *, provider=None, fetch=None):
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

        def fake(job, *, provider=None, fetch=None):
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
