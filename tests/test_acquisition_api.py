"""acquisition P0 REST 端点测试（ADR 0085 §7）：CRUD / 校验 / 预览 / 运行 / 历史."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.acquisition.models import AcquisitionStrategy
from cndb.plugins.acquisition.services import runner as acquisition_runner
from cndb.plugins.datasource.models import DatasourceSyncJob
from cndb.plugins.datasource.services.pipeline import PipelineOutcome
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

ROWS = [{"city": "北京", "day": "2026-11-01", "temp": "12.5"}]


@pytest.fixture
def workspace_with_auth(client, db):
    """工作区 + OWNER 登录 token（与 datasource API 测试同口径）."""
    user = User(username="acq_user", nickname="ACQ User")
    user.set_password("passw0rd")
    db.add(user)
    db.flush()
    ws = Workspace(name="ACQ-WS", created_by_id=user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER))
    db.commit()
    response = client.post("/api/v1/accounts/auth/login", json={"login": "acq_user", "password": "passw0rd"})
    return ws.id, {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def table(db: Session, db_engine, workspace_with_auth) -> DataTable:
    workspace_id, _ = workspace_with_auth
    table = DataTable(workspace_id=workspace_id, name="采集目标表")
    table.ensure_db_name()
    db.add(table)
    db.commit()
    db.refresh(table)
    for order, name in enumerate(("city", "day", "temp")):
        field = DataField(table_id=table.id, name=name, field_type="text", order=order)
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(table)
    ddl.create_table(db_engine, table)
    return table


@pytest.fixture
def sync_job(db: Session, table: DataTable) -> DatasourceSyncJob:
    """被策略引用的既有同步任务（`job:<id>` 渠道）."""
    job = DatasourceSyncJob(
        workspace_id=table.workspace_id,
        name="政策源",
        provider="http_json",
        table_id=table.id,
        request_spec={"url_template": "https://api.example.com/p?q={query}"},
        parser="json",
        match_keys=["city", "day"],
        cursor={"strategy": "none"},
        schedule={"mode": "manual"},
        enabled=True,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@pytest.fixture(autouse=True)
def fake_pipeline(monkeypatch):
    """抓取层替换成固定行，端点测试不触网."""

    def run_pipeline(spec, *, progress=None, on_batch=None, **kwargs):
        return PipelineOutcome(rows=[dict(row) for row in ROWS], plans=1, succeeded=1, failures=[])

    monkeypatch.setattr(acquisition_runner, "run_pipeline", run_pipeline)


def _payload(table: DataTable, job_id: int = 1, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "政策日报",
        "scope": {"channels": [f"job:{job_id}"], "query": "{today} 北京", "max_results_per_channel": 20},
        "filter_rule": {"must_have_keywords": ["北京"]},
        "targets": [{"kind": "table", "table_id": table.id, "match_keys": ["city", "day"]}],
        "iteration": {"max_rounds": 1, "budget": {"max_requests": 10}},
        "schedule": {"mode": "manual"},
    }
    payload.update(overrides)
    return payload


def test_create_and_update_strategy_bumps_rule_version(client, db, table, sync_job, workspace_with_auth):
    workspace_id, headers = workspace_with_auth
    base = f"/api/v1/workspaces/{workspace_id}/acquisition"

    created = client.post(f"{base}/strategies", json=_payload(table, sync_job.id), headers=headers)
    assert created.status_code == 201, created.text
    strategy = created.json()
    assert strategy["rule_version"] == 1 and strategy["enabled"] is False

    updated = client.put(
        f"{base}/strategies/{strategy['id']}",
        json={"filter_rule": {"must_have_keywords": ["上海"]}},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["rule_version"] == 2
    assert updated.json()["enabled"] is False

    listed = client.get(f"{base}/strategies", headers=headers)
    assert listed.json()["total"] == 1


def test_create_rejects_document_target_and_bad_channel(client, table, sync_job, workspace_with_auth):
    workspace_id, headers = workspace_with_auth
    base = f"/api/v1/workspaces/{workspace_id}/acquisition"

    doc = client.post(
        f"{base}/strategies",
        json=_payload(table, sync_job.id, targets=[{"kind": "document", "parent_id": 1}]),
        headers=headers,
    )
    assert doc.status_code == 400
    assert "目标文件夹不存在" in doc.json()["detail"]

    channel = client.post(
        f"{base}/strategies",
        json=_payload(table, sync_job.id, scope={"channels": ["nope"], "query": "x"}),
        headers=headers,
    )
    assert channel.status_code == 400


def test_preview_and_run_and_history(client, db, table, sync_job, workspace_with_auth):
    workspace_id, headers = workspace_with_auth
    base = f"/api/v1/workspaces/{workspace_id}/acquisition"
    strategy_id = client.post(f"{base}/strategies", json=_payload(table, sync_job.id), headers=headers).json()["id"]

    preview = client.post(f"{base}/strategies/{strategy_id}/preview", headers=headers)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["collected"] == 1 and body["after_filter"] == 1
    assert body["samples"][0]["title"] == "" or body["samples"][0]["match_score"] >= 50
    # 预览不落运行记录
    assert db.query(AcquisitionStrategy).one().last_status == ""

    run = client.post(f"{base}/strategies/{strategy_id}/run", headers=headers)
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "success"
    assert run.json()["inserted"] == 1

    history = client.get(f"{base}/strategies/{strategy_id}/runs", headers=headers)
    assert history.json()["total"] == 1
    run_id = history.json()["runs"][0]["id"]

    detail = client.get(f"{base}/runs/{run_id}", headers=headers)
    assert detail.status_code == 200
    assert len(detail.json()["rounds"]) == 1
    assert detail.json()["rounds"][0]["stop_reason"] == "max_rounds"


def test_validate_rules_endpoint(client, table, sync_job, workspace_with_auth):
    workspace_id, headers = workspace_with_auth
    base = f"/api/v1/workspaces/{workspace_id}/acquisition"

    ok = client.post(f"{base}/rules/validate", json=_payload(table, sync_job.id), headers=headers)
    assert ok.json() == {"ok": True, "errors": []}

    bad = client.post(
        f"{base}/rules/validate",
        json=_payload(table, sync_job.id, scope={"channels": [], "query": "x"}),
        headers=headers,
    )
    assert bad.json()["ok"] is False
    assert any("channels" in error for error in bad.json()["errors"])


def test_unknown_strategy_returns_404(client, workspace_with_auth):
    workspace_id, headers = workspace_with_auth
    base = f"/api/v1/workspaces/{workspace_id}/acquisition"
    assert client.get(f"{base}/strategies/999", headers=headers).status_code == 404
    assert client.get(f"{base}/runs/999", headers=headers).status_code == 404


def test_manual_review_pauses_and_resumes(client, db, table, sync_job, workspace_with_auth):
    workspace_id, headers = workspace_with_auth
    base = f"/api/v1/workspaces/{workspace_id}/acquisition"
    payload = _payload(
        table,
        sync_job.id,
        iteration={
            "max_rounds": 2,
            "top_keywords_per_round": 3,
            "expand": {"review": "manual"},
            "budget": {"max_requests": 10},
        },
    )
    strategy_id = client.post(f"{base}/strategies", json=payload, headers=headers).json()["id"]

    paused = client.post(f"{base}/strategies/{strategy_id}/run", headers=headers)
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "awaiting_review"
    run_id = paused.json()["id"]

    detail = client.get(f"{base}/runs/{run_id}", headers=headers).json()
    assert detail["rounds"][0]["review_state"] == "pending"

    resumed = client.post(f"{base}/runs/{run_id}/resume", json={"keywords": ["自定义词"]}, headers=headers)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "success"
    assert resumed.json()["round_count"] == 2

    again = client.post(f"{base}/runs/{run_id}/resume", json={}, headers=headers)
    assert again.status_code == 400
