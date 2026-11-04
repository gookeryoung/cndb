"""数据同步对外推送（需求 0099）：校验 / 批量发送 / 增量游标 / 失败留痕."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.datasource.models import DatasourceSyncJob, RunStatus
from cndb.plugins.datasource.providers.base import ProviderError
from cndb.plugins.datasource.services.push import validate_push_spec
from cndb.plugins.datasource.services.runner import execute_job
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core.records import create_row
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


def _make_workspace(db: Session) -> tuple[Workspace, User]:
    user = User(username="push_user", nickname="推送用户")
    user.set_password("passw0rd")
    db.add(user)
    db.flush()
    ws = Workspace(name="推送工作区", created_by_id=user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(ws)
    db.refresh(user)
    return ws, user


def _make_table(db: Session, engine: Any, workspace_id: int) -> DataTable:
    table = DataTable(workspace_id=workspace_id, name="推送源表")
    table.ensure_db_name()
    db.add(table)
    db.commit()
    db.refresh(table)
    for order, (name, ftype) in enumerate((("名称", "text"), ("金额", "number"), ("日期", "date"))):
        field = DataField(table_id=table.id, name=name, field_type=ftype, order=order)
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(table)
    ddl.create_table(engine, table)
    return table


def _job(db: Session, workspace_id: int, table_id: int, push_spec: dict[str, Any]) -> DatasourceSyncJob:
    job = DatasourceSyncJob(
        workspace_id=workspace_id,
        name="对外推送任务",
        direction="push",
        provider="http_json",
        table_id=table_id,
        request_spec={},
        push_spec=push_spec,
        cursor={"strategy": "none"},
        schedule={"mode": "manual"},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


class _Response:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.text = "ok" if status_code < 400 else "boom"


class _Client:
    def __init__(self, statuses: list[int] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.statuses = statuses or []

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def request(self, method: str, url: str, *, headers: dict[str, str], json: Any) -> _Response:
        status = self.statuses[len(self.calls)] if len(self.calls) < len(self.statuses) else 200
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        return _Response(status)


def test_validate_push_spec_rejects_bad_fields(db, db_engine):
    ws, _user = _make_workspace(db)
    table = _make_table(db, db_engine, ws.id)
    with pytest.raises(ProviderError):
        validate_push_spec({"url_template": "ftp://x"}, table_id=table.id, db=db, workspace_id=ws.id)
    with pytest.raises(ProviderError):
        validate_push_spec(
            {"url_template": "https://x", "fields": ["不存在"]}, table_id=table.id, db=db, workspace_id=ws.id
        )
    with pytest.raises(ProviderError):
        validate_push_spec({"url_template": "https://x", "batch_size": 0}, table_id=table.id, db=db, workspace_id=ws.id)
    with pytest.raises(ProviderError):
        validate_push_spec({"url_template": "https://x"}, table_id=None, db=db, workspace_id=ws.id)


def test_push_batches_and_incremental_cursor(db, db_engine, monkeypatch):
    ws, user = _make_workspace(db)
    table = _make_table(db, db_engine, ws.id)
    create_row(db_engine, table, {"名称": "A", "金额": 1, "日期": "2026-01-01"})
    create_row(db_engine, table, {"名称": "B", "金额": 2, "日期": "2026-01-02"})
    client = _Client()
    monkeypatch.setattr("cndb.plugins.datasource.services.push.open_http_client", lambda **kw: client)
    spec = {
        "url_template": "https://example.com/ingest",
        "method": "POST",
        "headers_template": {"X-Token": "static-token"},
        "body_template": {"items": "{rows}", "count": "{count}"},
        "batch_size": 1,
        "fields": ["名称", "日期"],
        "watermark_field": "日期",
    }
    job = _job(db, ws.id, table.id, spec)
    job.session_id = None
    db.commit()
    execution = execute_job(db, job, user=user)
    assert execution.run.status == RunStatus.SUCCESS.value
    assert execution.run.inserted == 2
    assert len(client.calls) == 2
    first = client.calls[0]
    assert first["url"] == "https://example.com/ingest"
    assert first["json"] == {"items": [{"名称": "A", "日期": "2026-01-01"}], "count": 1}
    assert first["headers"]["X-Token"] == "static-token"
    assert job.cursor["value"] == "2026-01-02"

    create_row(db_engine, table, {"名称": "C", "金额": 3, "日期": "2026-01-03"})
    client.calls.clear()
    execution = execute_job(db, job, user=user)
    assert execution.run.status == RunStatus.SUCCESS.value
    assert execution.run.inserted == 1
    assert client.calls[0]["json"]["items"] == [{"名称": "C", "日期": "2026-01-03"}]


def test_push_failure_is_recorded(db, db_engine, monkeypatch):
    ws, user = _make_workspace(db)
    table = _make_table(db, db_engine, ws.id)
    create_row(db_engine, table, {"名称": "A", "金额": 1, "日期": "2026-01-01"})
    client = _Client(statuses=[500])
    monkeypatch.setattr("cndb.plugins.datasource.services.push.open_http_client", lambda **kw: client)
    job = _job(db, ws.id, table.id, {"url_template": "https://example.com/ingest", "batch_size": 10})
    execution = execute_job(db, job, user=user)
    assert execution.run.status == RunStatus.FAILED.value
    assert execution.run.skipped == 1
    assert "500" in execution.run.error_message
    assert execution.run.detail["push"]["failed_batches"] == 1


def test_push_job_api_validation(client, auth_headers, db, db_engine):
    from sqlalchemy import select

    user = db.execute(select(User).where(User.username == "testuser")).scalar_one()
    ws = Workspace(name="API 推送工作区", created_by_id=user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(ws)
    table = _make_table(db, db_engine, ws.id)
    payload = {
        "name": "推送任务",
        "direction": "push",
        "provider": "http_json",
        "table_id": table.id,
        "request_spec": {},
        "push_spec": {"url_template": "https://example.com/ingest", "batch_size": 50},
        "schedule": {"mode": "manual"},
    }
    created = client.post(f"/api/v1/workspaces/{ws.id}/datasource/sync-jobs", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["direction"] == "push"
    assert body["push_spec"]["batch_size"] == 50

    bad = {**payload, "push_spec": {"url_template": "https://example.com", "fields": ["不存在"]}}
    rejected = client.post(f"/api/v1/workspaces/{ws.id}/datasource/sync-jobs", json=bad, headers=auth_headers)
    assert rejected.status_code == 400
    assert "不存在的字段" in rejected.text
