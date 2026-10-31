"""流水线事件触发测试：命中判定 / 单飞跳过 / 失败静默 / 三个分发点（ADR 0076 P1）."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import select

from cndb.plugins.datasource.models import DatasourceSyncJob
from cndb.plugins.datasource.services.runner import execute_job
from cndb.plugins.pipeline.models import (
    TRIGGER_EVENT,
    TRIGGER_MANUAL,
    PipelineRun,
    PipelineWorkflow,
)
from cndb.plugins.pipeline.services import runner, triggers
from cndb.plugins.pipeline.services.dsl.parse import compile_workflow
from tests.pipeline_helpers import add_rows, login, make_document, make_table, make_user, make_workspace

BASE = "/api/v1/workspaces/{ws}/pipelines"
NOW = dt.datetime(2024, 7, 1, 9, 0, tzinfo=dt.UTC)


@pytest.fixture
def owner(db):
    return make_user(db, "pipeline_trigger_owner")


@pytest.fixture
def ws(db, owner):
    return make_workspace(db, owner, "PipelineTriggerWS")


@pytest.fixture
def people(db, ws):
    return make_table(db, ws, "人员", [("姓名", "text"), ("城市", "text")])


@pytest.fixture
def auth(client, owner):
    return login(client, owner)


def _content(events: list[str], *, manual: bool = False) -> str:
    event_line = ", ".join(events)
    return (
        "name: 空值巡检\n"
        "on:\n"
        f"  manual: {str(manual).lower()}\n"
        f"  events: [{event_line}]\n"
        "jobs:\n"
        "  表:\n"
        "    steps:\n"
        "      - uses: table/null-rate\n"
        "        with:\n"
        "          table: 人员\n"
        "          fields: [城市]\n"
    )


def _make_workflow(
    db,
    ws,
    events: list[str],
    *,
    enabled: bool = True,
    name: str = "空值巡检",
) -> PipelineWorkflow:
    content = _content(events).replace("name: 空值巡检", f"name: {name}")
    ir = compile_workflow(content)
    workflow = PipelineWorkflow(
        workspace_id=ws.id,
        name=ir.name,
        content=content,
        compiled=ir.to_dict(),
        enabled=enabled,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def _runs(db, workflow: PipelineWorkflow) -> list[PipelineRun]:
    db.expire_all()
    return list(
        db.execute(select(PipelineRun).where(PipelineRun.workflow_id == workflow.id).order_by(PipelineRun.id)).scalars()
    )


class TestEventWorkflows:
    def test_matches_subscribed_and_enabled(self, db, ws):
        hit = _make_workflow(db, ws, [triggers.EVENT_RECORD_UPDATED])
        _make_workflow(db, ws, ["document.saved"], name="文档巡检")
        _make_workflow(db, ws, [triggers.EVENT_RECORD_UPDATED], enabled=False, name="停用巡检")

        matched = triggers.event_workflows(db, ws.id, triggers.EVENT_RECORD_UPDATED)
        assert [workflow.id for workflow in matched] == [hit.id]

    def test_unknown_event_returns_empty(self, db, ws, caplog):
        assert triggers.dispatch_event(db, "record.deleted", workspace_id=ws.id) == []
        assert any("未知的流水线事件" in record.message for record in caplog.records)

    def test_no_subscriber_returns_empty(self, db, ws):
        _make_workflow(db, ws, ["document.saved"], name="文档巡检")
        assert triggers.dispatch_event(db, triggers.EVENT_RECORD_UPDATED, workspace_id=ws.id) == []

    def test_broken_compiled_is_skipped(self, db, ws, monkeypatch, caplog):
        _make_workflow(db, ws, [triggers.EVENT_RECORD_UPDATED])

        def boom(_data: dict[str, Any]):
            raise RuntimeError("编译快照损坏")

        monkeypatch.setattr(triggers.WorkflowIR, "from_dict", boom)
        assert triggers.event_workflows(db, ws.id, triggers.EVENT_RECORD_UPDATED) == []
        assert any("编译快照损坏" in record.message for record in caplog.records)


class TestDispatchEvent:
    def test_creates_event_run_with_payload(self, db, ws, people):
        workflow = _make_workflow(db, ws, [triggers.EVENT_RECORD_UPDATED])
        run_ids = triggers.dispatch_event(
            db,
            triggers.EVENT_RECORD_UPDATED,
            workspace_id=ws.id,
            payload={"table_id": people.id, "action": "updated"},
        )

        assert len(run_ids) == 1
        run = _runs(db, workflow)[0]
        assert run.id == run_ids[0]
        assert run.trigger == TRIGGER_EVENT
        assert run.trigger_payload["event"] == triggers.EVENT_RECORD_UPDATED
        assert run.trigger_payload["table_id"] == people.id
        assert run.trigger_payload["action"] == "updated"

    def test_active_run_skips_event_trigger(self, db, ws):
        workflow = _make_workflow(db, ws, [triggers.EVENT_RECORD_UPDATED])
        existing = runner.create_run(db, workflow, trigger=TRIGGER_MANUAL)

        assert triggers.dispatch_event(db, triggers.EVENT_RECORD_UPDATED, workspace_id=ws.id) == []
        runs = _runs(db, workflow)
        assert [run.id for run in runs] == [existing.id]

    def test_dispatch_failure_is_silent(self, db, ws, monkeypatch, caplog):
        _make_workflow(db, ws, [triggers.EVENT_RECORD_UPDATED])

        def boom(*_args: Any, **_kwargs: Any):
            raise RuntimeError("建运行失败")

        monkeypatch.setattr(triggers, "create_run", boom)
        assert triggers.dispatch_event(db, triggers.EVENT_RECORD_UPDATED, workspace_id=ws.id) == []
        assert any("流水线事件分发失败" in record.message for record in caplog.records)


class TestRecordUpdatedDispatch:
    """记录批量变更三个端点都触发 ``record.updated``."""

    def test_bulk_create_triggers(self, db, client, ws, people, auth):
        workflow = _make_workflow(db, ws, [triggers.EVENT_RECORD_UPDATED])
        resp = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{people.id}/records/bulk-create",
            json={"rows": [{"values": {"姓名": "张三", "城市": "北京"}}]},
            headers=auth,
        )
        assert resp.status_code == 201, resp.text
        run = _runs(db, workflow)[0]
        assert run.trigger == TRIGGER_EVENT
        assert run.trigger_payload["action"] == "created"
        assert run.trigger_payload["count"] == 1

    def test_bulk_update_triggers(self, db, client, ws, people, auth):
        workflow = _make_workflow(db, ws, [triggers.EVENT_RECORD_UPDATED])
        row_ids = add_rows(db, people, [{"姓名": "张三", "城市": "北京"}])
        resp = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{people.id}/records/bulk-update",
            json={"row_ids": row_ids, "values": {"城市": "上海"}},
            headers=auth,
        )
        assert resp.status_code == 200, resp.text
        run = _runs(db, workflow)[0]
        assert run.trigger_payload["action"] == "updated"
        assert run.trigger_payload["row_ids"] == row_ids

    def test_bulk_delete_triggers(self, db, client, ws, people, auth):
        workflow = _make_workflow(db, ws, [triggers.EVENT_RECORD_UPDATED])
        row_ids = add_rows(db, people, [{"姓名": "张三", "城市": "北京"}])
        resp = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{people.id}/records/bulk-delete",
            json={"row_ids": row_ids},
            headers=auth,
        )
        assert resp.status_code == 200, resp.text
        run = _runs(db, workflow)[0]
        assert run.trigger_payload["action"] == "deleted"
        assert run.trigger_payload["count"] == 1


class TestDocumentSavedDispatch:
    def test_direct_save_triggers(self, db, client, ws, owner, auth):
        workflow = _make_workflow(db, ws, [triggers.EVENT_DOCUMENT_SAVED], name="文档巡检")
        doc = make_document(db, ws, "会议纪要", "# 第一版", user=owner)
        resp = client.put(
            f"/api/v1/workspaces/{ws.id}/documents/{doc.id}/content",
            json={"content": "# 第二版"},
            headers=auth,
        )
        assert resp.status_code == 200, resp.text
        run = _runs(db, workflow)[0]
        assert run.trigger == TRIGGER_EVENT
        assert run.trigger_payload["document_id"] == doc.id
        assert run.trigger_payload["event"] == triggers.EVENT_DOCUMENT_SAVED


class TestSyncFinishedDispatch:
    def test_sync_success_triggers(self, db, ws):
        weather = make_table(db, ws, "天气日表", [("city", "text"), ("day", "date"), ("temp", "float")])
        workflow = _make_workflow(db, ws, [triggers.EVENT_SYNC_FINISHED], name="同步巡检")
        job = _make_job(db, ws, weather)
        execution = execute_job(
            db,
            job,
            fetch=lambda _config: [{"city": "北京", "day": "2024-06-30", "temp": "31.5"}],
            now=NOW,
        )
        assert execution.run.status == "success"
        run = _runs(db, workflow)[0]
        assert run.trigger == TRIGGER_EVENT
        assert run.trigger_payload["job_id"] == job.id
        assert run.trigger_payload["status"] == "success"


def _make_job(db, ws, table) -> DatasourceSyncJob:
    payload: dict[str, Any] = {
        "workspace_id": ws.id,
        "name": "天气同步",
        "provider": "http_json",
        "table_id": table.id,
        "request_spec": {
            "url_template": "https://api.example.com/w?city={city}&from={from}&to={to}",
            "time_window": {"mode": "range", "start_param": "from", "end_param": "to"},
        },
        "parser": "json",
        "entrant_param": "city",
        "entrant_keys": ["北京"],
        "match_keys": ["city", "day"],
        "field_mapping": {
            "day": {"name": "day", "field_type": "date"},
            "temp": {"name": "temp", "field_type": "float"},
        },
        "cursor": {"strategy": "date", "field": "day", "backfill_start": "2024-01-01"},
        "schedule": {"mode": "manual"},
        "enabled": True,
        "last_status": "",
    }
    job = DatasourceSyncJob(**payload)  # type: ignore[arg-type]
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
