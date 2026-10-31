"""流水线执行器测试：结论推导 / 条件 / 错误隔离 / 单飞（ADR 0076 D9 / I3 / I6）."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from cndb.core.events import CoreEvent
from cndb.plugins.pipeline.models import (
    ACTIVE_RUN_STATUSES,
    CONCLUSION_FAILED,
    CONCLUSION_SKIPPED,
    CONCLUSION_SUCCESS,
    RUN_STATUS_FAILED,
    RUN_STATUS_PARTIAL,
    RUN_STATUS_PENDING,
    RUN_STATUS_SUCCESS,
    PipelineRun,
    PipelineWorkflow,
)
from cndb.plugins.pipeline.services import runner
from cndb.plugins.pipeline.services.checks.base import FindingDraft
from cndb.plugins.pipeline.services.dsl.parse import compile_workflow
from cndb.plugins.pipeline.services.errors import PipelineConflictError
from tests.pipeline_helpers import add_rows, make_document, make_table, make_user, make_workspace


@pytest.fixture
def owner(db):
    return make_user(db, "pipeline_runner_owner")


@pytest.fixture
def ws(db, owner):
    return make_workspace(db, owner, "PipelineRunnerWS")


@pytest.fixture
def people(db, ws):
    return make_table(db, ws, "人员", [("姓名", "text"), ("城市", "text")])


def _make_workflow(db, ws, content: str) -> PipelineWorkflow:
    ir = compile_workflow(content)
    workflow = PipelineWorkflow(
        workspace_id=ws.id,
        name=ir.name,
        content=content,
        compiled=ir.to_dict(),
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def _run(db, workflow, *, payload: dict | None = None) -> PipelineRun:
    run = runner.create_run(db, workflow, payload=payload)
    runner.execute_pipeline_run(db, run.id)
    db.refresh(run)
    return run


def _dsl(steps: str, *, name: str = "巡检", job_extra: str = "", vars_block: str = "") -> str:
    return f"name: {name}\n{vars_block}jobs:\n  体检:\n{job_extra}    steps:\n{steps}"


STEP = "      - uses: table/null-rate\n        with: {table: 人员, fields: [城市]}\n"


class TestConclusions:
    def test_success_when_no_findings(self, db, ws, people):
        add_rows(db, people, [{"姓名": "张三", "城市": "北京"}])
        run = _run(db, _make_workflow(db, ws, _dsl(STEP)))
        assert run.status == RUN_STATUS_SUCCESS
        assert run.stats["jobs"][0]["conclusion"] == CONCLUSION_SUCCESS
        assert run.stats["findings"] == {"error": 0, "warn": 0, "info": 0}

    def test_partial_on_warn(self, db, ws, people):
        add_rows(db, people, [{"姓名": "张三", "城市": None}])
        run = _run(db, _make_workflow(db, ws, _dsl(STEP)))
        assert run.status == RUN_STATUS_PARTIAL
        assert run.stats["findings"]["warn"] == 1

    def test_failed_on_error_severity(self, db, ws, people):
        add_rows(db, people, [{"姓名": "张三", "城市": None}])
        content = _dsl(
            "      - uses: table/null-rate\n        with: {table: 人员, fields: [城市]}\n        severity: error\n"
        )
        run = _run(db, _make_workflow(db, ws, content))
        assert run.status == RUN_STATUS_FAILED
        assert run.stats["jobs"][0]["conclusion"] == CONCLUSION_FAILED

    def test_continue_on_error_keeps_job_success(self, db, ws, people):
        add_rows(db, people, [{"姓名": "张三", "城市": None}])
        content = _dsl(
            "      - uses: table/null-rate\n        with: {table: 人员, fields: [城市]}\n"
            "        severity: error\n        continue-on-error: true\n"
        )
        run = _run(db, _make_workflow(db, ws, content))
        assert run.status == RUN_STATUS_PARTIAL
        assert run.stats["jobs"][0]["conclusion"] == CONCLUSION_SUCCESS
        assert run.stats["findings"]["error"] == 1

    def test_skipped_job_keeps_success(self, db, ws, people):
        content = _dsl(STEP, job_extra="    if: ${{ false }}\n")
        run = _run(db, _make_workflow(db, ws, content))
        assert run.status == RUN_STATUS_SUCCESS
        assert run.stats["jobs"][0]["conclusion"] == CONCLUSION_SKIPPED
        assert run.stats["jobs_done"] == 0

    def test_if_eval_failure_is_skipped_with_warning(self, db, ws, people):
        content = _dsl(STEP, job_extra="    if: ${{ on.missing }}\n")
        run = _run(db, _make_workflow(db, ws, content))
        assert run.status == RUN_STATUS_SUCCESS
        assert run.stats["jobs"][0]["conclusion"] == CONCLUSION_SKIPPED
        assert any("求值失败" in warning for warning in run.stats["warnings"])

    def test_needs_skips_downstream_when_upstream_failed(self, db, ws, people):
        content = (
            "name: 依赖\n"
            "jobs:\n"
            "  坏检查:\n"
            "    steps:\n"
            "      - uses: table/null-rate\n"
            "        with: {table: 不存在}\n"
            "  下游:\n"
            "    needs: 坏检查\n"
            "    steps:\n"
            "      - uses: document/links\n"
        )
        run = _run(db, _make_workflow(db, ws, content))
        assert run.status == RUN_STATUS_FAILED
        conclusions = {item["id"]: item["conclusion"] for item in run.stats["jobs"]}
        assert conclusions == {"坏检查": CONCLUSION_FAILED, "下游": CONCLUSION_SKIPPED}


class TestIsolation:
    def test_check_error_does_not_block_next_step(self, db, ws, people):
        content = _dsl("      - uses: table/null-rate\n        with: {table: 不存在}\n      - uses: document/links\n")
        run = _run(db, _make_workflow(db, ws, content))
        steps = run.stats["jobs"][0]["steps"]
        assert steps[0]["conclusion"] == CONCLUSION_FAILED
        assert steps[0]["error"]
        assert steps[1]["conclusion"] == CONCLUSION_SUCCESS
        assert run.status == RUN_STATUS_FAILED

    def test_param_coercion_failure_marks_step_failed(self, db, ws, people):
        content = _dsl("      - uses: document/broken-refs\n        with: {scopes: ['${{ on.missing }}', file]}\n")
        run = _run(db, _make_workflow(db, ws, content))
        assert run.stats["jobs"][0]["steps"][0]["conclusion"] == CONCLUSION_FAILED
        assert run.stats["warnings"]

    def test_engine_error_on_broken_compiled(self, db, ws):
        workflow = _make_workflow(db, ws, _dsl(STEP))
        workflow.compiled = {"jobs": "bad"}
        db.commit()
        run = _run(db, workflow)
        assert run.status == RUN_STATUS_FAILED
        assert run.error_message

    def test_missing_workflow_marks_failed(self, db, ws):
        workflow = _make_workflow(db, ws, _dsl(STEP))
        run = runner.create_run(db, workflow)
        db.query(PipelineWorkflow).filter(PipelineWorkflow.id == workflow.id).delete()
        db.commit()
        runner.execute_pipeline_run(db, run.id)
        db.refresh(run)
        assert run.status == RUN_STATUS_FAILED
        assert run.error_message == "流水线定义已删除"


class TestFindings:
    def test_truncation_aggregates_info(self, db, ws, people, monkeypatch):
        add_rows(
            db,
            people,
            [
                {"姓名": "a", "城市": "x"},
                {"姓名": "a", "城市": "x"},
                {"姓名": "b", "城市": "y"},
                {"姓名": "b", "城市": "y"},
            ],
        )
        monkeypatch.setattr(runner, "MAX_FINDINGS_PER_CHECK", 1)
        content = _dsl("      - uses: table/duplicates\n        with: {table: 人员, fields: [姓名]}\n")
        run = _run(db, _make_workflow(db, ws, content))
        findings = (
            db.execute(select(runner.PipelineFinding).where(runner.PipelineFinding.run_id == run.id)).scalars().all()
        )
        assert len(findings) == 2
        assert any("截断" in item.message for item in findings)
        assert run.stats["findings"]["info"] == 1

    def test_severity_fallback_unknown_value(self):
        draft = FindingDraft(message="x", severity="fatal")
        assert runner._severity_of(draft, "warn") == "warn"

    def test_trigger_payload_and_vars(self, db, ws, people):
        content = _dsl(
            STEP,
            job_extra="    if: ${{ vars.b == 'x' }}\n",
            vars_block="vars:\n  a: ${{ on.event }}\n  b: ${{ vars.a }}\n",
        )
        workflow = _make_workflow(db, ws, content)
        run = _run(db, workflow, payload={"event": "x"})
        assert run.stats["jobs"][0]["conclusion"] == CONCLUSION_SUCCESS
        assert run.stats["warnings"] == []


class TestSingleFlight:
    def test_second_trigger_conflicts(self, db, ws, people):
        workflow = _make_workflow(db, ws, _dsl(STEP))
        first = runner.create_run(db, workflow)
        assert first.status == RUN_STATUS_PENDING
        with pytest.raises(PipelineConflictError):
            runner.create_run(db, workflow)
        runner.execute_pipeline_run(db, first.id)
        second = runner.create_run(db, workflow)
        assert second.id != first.id

    def test_active_statuses_defined(self):
        assert RUN_STATUS_PENDING in ACTIVE_RUN_STATUSES


class TestBackground:
    def test_background_thread_runs_to_completion(self, db, ws, people, _session_factory):
        add_rows(db, people, [{"姓名": "张三", "城市": "北京"}])
        workflow = _make_workflow(db, ws, _dsl(STEP))
        run = runner.create_run(db, workflow)
        factory = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
        assert callable(factory)
        runner.run_pipeline_in_background(factory, run.id)
        runner.join_background_threads(timeout=10)
        with _session_factory() as session:
            stored = session.get(PipelineRun, run.id)
            assert stored is not None
            assert stored.status == RUN_STATUS_SUCCESS


class TestEvents:
    def test_run_records_event(self, db, ws, people):
        run = _run(db, _make_workflow(db, ws, _dsl(STEP)))
        event = db.execute(
            select(CoreEvent).where(CoreEvent.target_type == "pipeline_run", CoreEvent.target_id == str(run.id))
        ).scalar_one_or_none()
        assert event is not None
        assert event.action == "pipeline.run"

    def test_document_check_runs_against_workspace(self, db, ws, people):
        make_document(db, ws, "文档", "[[不存在]]")
        content = _dsl("      - uses: document/links\n")
        run = _run(db, _make_workflow(db, ws, content))
        assert run.status == RUN_STATUS_PARTIAL
