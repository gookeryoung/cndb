"""datasource M2：运行编排（落表 / 游标推进 / 留痕 / 预览 / 配置还原）单测."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import MetaData, func, select
from sqlalchemy.orm import Session

from cndb.core.crypto import encrypt_secrets
from cndb.plugins.datasource.models import DatasourceSession, DatasourceSyncJob, DatasourceSyncRun
from cndb.plugins.datasource.providers.base import FieldTransform
from cndb.plugins.datasource.services import runner
from cndb.plugins.datasource.services.runner import (
    build_job_spec,
    execute_job,
    field_mapping_from_payload,
    preview_job,
    request_spec_from_payload,
)
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.importing.api_fetch import FetchConfig

UTC = dt.UTC
NOW = dt.datetime(2024, 7, 1, 9, 0, tzinfo=UTC)


def _make_table(session: Session, engine) -> DataTable:
    table = DataTable(workspace_id=1, name="天气日表")
    table.ensure_db_name()
    session.add(table)
    session.commit()
    session.refresh(table)
    for order, (name, field_type) in enumerate((("city", "text"), ("day", "date"), ("temp", "float"))):
        field = DataField(table_id=table.id, name=name, field_type=field_type, order=order)
        field.ensure_db_name()
        session.add(field)
    session.commit()
    session.refresh(table)
    ddl.create_table(engine, table)
    return table


def _row_count(engine, table: DataTable) -> int:
    metadata = MetaData()
    sa_table = ddl.build_sa_table(metadata, table)
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(sa_table)).scalar_one())


def _make_job(db: Session, table: DataTable, **overrides: object) -> DatasourceSyncJob:
    payload: dict[str, object] = {
        "workspace_id": 1,
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
    payload.update(overrides)
    job = DatasourceSyncJob(**payload)  # type: ignore[arg-type]
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _fetch(rows: list[dict[str, object]]):
    def fetch(_config: FetchConfig) -> list[dict[str, object]]:
        return rows

    return fetch


class TestExecuteJob:
    def test_inserts_and_advances_cursor(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        rows = [
            {"city": "北京", "day": "2024/06/30", "temp": "31.5"},
            {"city": "北京", "day": "2024-07-01", "temp": "33"},
        ]
        execution = execute_job(db, job, fetch=_fetch(rows), now=NOW)

        assert execution.run.status == "success"
        assert (execution.run.fetched, execution.run.inserted, execution.run.updated) == (2, 2, 0)
        assert execution.cursor_from == "2024-01-01"
        assert execution.cursor_to == "2024-07-01"
        assert _row_count(db_engine, table) == 2

        db.refresh(job)
        assert job.last_status == "success"
        assert job.cursor["value"] == "2024-07-01"
        assert job.last_run_at is not None

    def test_second_run_updates_without_duplicates(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        execute_job(db, job, fetch=_fetch([{"city": "北京", "day": "2024-06-30", "temp": "31.5"}]), now=NOW)
        second = execute_job(db, job, fetch=_fetch([{"city": "北京", "day": "2024-06-30", "temp": "35"}]), now=NOW)
        assert second.run.inserted == 0
        assert second.run.updated == 1
        assert _row_count(db_engine, table) == 1
        # 第二次的窗口起点取自上一轮推进后的游标
        assert second.cursor_from == "2024-06-30"

    def test_failure_recorded_without_raising(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)

        def boom(_config: FetchConfig) -> list[dict[str, object]]:
            raise ValueError("HTTP 500: 源故障")

        execution = execute_job(db, job, fetch=boom, now=NOW)
        assert execution.run.status == "failed"
        assert "源故障" in execution.run.error_message
        db.refresh(job)
        assert job.last_status == "failed"

    def test_missing_table_marks_failed(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table, table_id=999)
        execution = execute_job(db, job, fetch=_fetch([{"city": "北京", "day": "2024-06-30"}]), now=NOW)
        assert execution.run.status == "failed"
        assert "目标表不存在" in execution.run.error_message

    def test_no_table_only_fetches(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table, table_id=None)
        execution = execute_job(db, job, fetch=_fetch([{"city": "北京", "day": "2024-06-30"}]), now=NOW)
        assert execution.run.status == "success"
        assert execution.run.fetched == 1
        assert execution.run.inserted == 0

    def test_empty_rows_keep_cursor(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(
            db,
            table,
            cursor={"strategy": "date", "field": "day", "backfill_start": "2024-01-01", "value": "2024-05-05"},
        )
        execution = execute_job(db, job, fetch=_fetch([]), now=NOW)
        assert execution.run.status == "success"
        assert execution.cursor_from == "2024-05-05"
        assert execution.cursor_to == "2024-05-05"

    def test_event_recorded(self, db_engine, db):
        from cndb.core.events import CoreEvent

        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        execute_job(db, job, fetch=_fetch([{"city": "北京", "day": "2024-06-30"}]), now=NOW)
        actions = [event.action for event in db.query(CoreEvent).all()]
        assert "datasource.sync" in actions


class TestPreviewJob:
    def test_preview_does_not_persist(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        preview = preview_job(job, fetch=_fetch([{"city": "北京", "day": "2024-06-30", "temp": "30"}]), now=NOW)
        assert preview.status == "success"
        assert preview.total == 1
        assert preview.columns == ["city", "day", "temp"]
        assert preview.rows[0]["temp"] == 30.0
        assert preview.cursor_to == "2024-06-30"
        assert _row_count(db_engine, table) == 0
        assert db.query(DatasourceSyncRun).count() == 0

    def test_preview_limit(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        rows = [{"city": "北京", "day": f"2024-06-{day:02d}"} for day in range(1, 11)]
        preview = preview_job(job, fetch=_fetch(rows), now=NOW, limit=3)
        assert preview.total == 10
        assert len(preview.rows) == 3

    def test_preview_reports_failures(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)

        def boom(_config: FetchConfig) -> list[dict[str, object]]:
            raise ValueError("HTTP 500")

        preview = preview_job(job, fetch=boom, now=NOW)
        assert preview.status == "failed"
        assert preview.failures[0]["entrant"] == "北京"


class TestPayloadParsing:
    def test_request_spec_injects_window(self):
        spec = request_spec_from_payload(
            {
                "url_template": "https://a.example.com/x",
                "time_window": {"mode": "range", "start_param": "s", "end_param": "e"},
            },
            cursor_from="2024-01-01",
            today="2024-07-01",
        )
        assert (spec.time_window.start, spec.time_window.end) == ("2024-01-01", "2024-07-01")

    def test_request_spec_without_window_untouched(self):
        spec = request_spec_from_payload(
            {"url_template": "https://a.example.com/x", "time_window": {"mode": "none"}},
            cursor_from="2024-01-01",
            today="2024-07-01",
        )
        assert spec.time_window.start == ""

    def test_request_spec_requires_url(self):
        with pytest.raises(ValueError, match="url_template"):
            request_spec_from_payload({})

    def test_request_spec_defaults(self):
        spec = request_spec_from_payload({"url_template": "https://a.example.com/x"})
        assert spec.method == "GET"
        assert spec.encoding == "utf-8"
        assert spec.paging.mode == "none"

    def test_field_mapping_variants(self):
        mapping = field_mapping_from_payload(
            {
                "a": None,
                "b": "renamed",
                "c": {"name": "target", "field_type": "float"},
                "d": {"field_type": "int"},
            }
        )
        assert mapping["a"] is None
        assert mapping["b"] == FieldTransform(name="renamed", field_type="text")
        assert mapping["c"] == FieldTransform(name="target", field_type="float")
        assert mapping["d"] == FieldTransform(name="d", field_type="int")

    def test_field_mapping_invalid_entry(self):
        with pytest.raises(ValueError, match="field_mapping"):
            field_mapping_from_payload({"a": 123})

    def test_build_job_spec_roundtrip(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        spec = build_job_spec(job, cursor_from="2024-01-01", today="2024-07-01")
        assert spec.provider == "http_json"
        assert spec.entrant_param == "city"
        assert spec.entrant_values == ("北京",)
        assert spec.match_keys == ("city", "day")
        assert spec.request.time_window.mode == "range"


class TestCursorGuards:
    def test_invalid_cursor_config_marks_failed(self, db_engine, db):
        """坏游标配置落成 failed 记录，不抛给调度器."""
        table = _make_table(db, db_engine)
        job = _make_job(db, table, cursor={"strategy": "weekly"})
        execution = execute_job(db, job, fetch=_fetch([]), now=NOW)
        assert execution.run.status == "failed"
        assert "游标策略" in execution.run.error_message


# ── ADR 0019：llm_prompt 落表自动化 / 连接默认值 ─────────────────


def _make_llm_job(
    db: Session,
    *,
    table_id: int | None = None,
    request_spec: dict[str, object] | None = None,
    session: DatasourceSession | None = None,
    match_keys: list[str] | None = None,
) -> DatasourceSyncJob:
    """建一个 llm_prompt 任务；缺省带 api_key 会话（provider 运行必需）."""
    if session is None:
        session = DatasourceSession(
            workspace_id=1,
            name="LLM",
            headers={},
            secrets=encrypt_secrets({"api_key": "sk-test"}),
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    payload = {
        "url_template": "https://llm.example.com/v1",
        "prompt": {"system": "你是数据助手", "user_template": "生成 {today} 的摘要"},
        "llm": {"model": "model-a"},
    }
    if request_spec:
        payload.update(request_spec)
    job = DatasourceSyncJob(
        workspace_id=1,
        name="LLM 同步",
        provider="llm_prompt",
        table_id=table_id,
        request_spec=payload,
        parser="json",
        entrant_param=None,
        entrant_keys=[],
        match_keys=list(match_keys or []),
        field_mapping={},
        session_id=session.id,
        cursor={"strategy": "none"},
        schedule={"mode": "manual"},
        enabled=True,
        last_status="",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


class TestLlmAutoLandingDetail:
    def test_run_detail_records_auto_fields_and_match_keys(self, db_engine, db, monkeypatch):
        monkeypatch.setattr(runner, "_load_llm_connection", lambda _db, _wid: None)
        job = _make_llm_job(db)
        rows = [
            {"date": "2024-07-01", "city": "北京"},
            {"date": "2024-07-02", "city": "上海"},
        ]
        execution = execute_job(db, job, fetch=_fetch(rows), now=NOW)

        assert execution.run.status == "success"
        # 常规留痕字段仍在
        assert {"plans", "succeeded", "failures", "normalize_failures"} <= set(execution.run.detail)
        assert set(execution.run.detail["auto_fields"]) >= {"date", "city"}
        assert execution.run.detail["auto_match_keys"] == ["date"]
        db.refresh(job)
        assert job.match_keys == ["date"]
        assert job.table_id is not None

    def test_non_llm_provider_detail_has_empty_auto_keys(self, db_engine, db):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        execution = execute_job(db, job, fetch=_fetch([{"city": "北京", "day": "2024-06-30"}]), now=NOW)
        assert execution.run.detail["auto_fields"] == []
        assert execution.run.detail["auto_match_keys"] == []


class TestLlmPreviewSuggestedMatchKeys:
    def test_preview_suggests_keys_for_unbound_table(self, db_engine, db, monkeypatch):
        monkeypatch.setattr(runner, "_load_llm_connection", lambda _db, _wid: None)
        job = _make_llm_job(db)
        session = db.get(DatasourceSession, job.session_id)
        rows = [
            {"date": "2024-07-01", "city": "北京"},
            {"date": "2024-07-02", "city": "上海"},
        ]
        preview = preview_job(job, db=db, session=session, fetch=_fetch(rows), now=NOW)

        assert preview.suggested_match_keys == ["date"]
        # 预览无副作用：不建表、不写运行记录、不回填 table_id
        assert db.query(DataTable).count() == 0
        assert db.query(DatasourceSyncRun).count() == 0
        db.refresh(job)
        assert job.table_id is None

    def test_preview_uses_existing_table_fields_as_candidates(self, db_engine, db, monkeypatch):
        monkeypatch.setattr(runner, "_load_llm_connection", lambda _db, _wid: None)
        table = _make_table(db, db_engine)
        job = _make_llm_job(db, table_id=table.id)
        session = db.get(DatasourceSession, job.session_id)
        rows = [
            {"city": "北京", "day": "2024-07-01", "temp": 30},
            {"city": "上海", "day": "2024-07-02", "temp": 31},
        ]
        preview = preview_job(job, db=db, session=session, fetch=_fetch(rows), now=NOW)

        # city / day 都在表字段里且都唯一；city 先出现、权重相同 → 取 city
        assert preview.suggested_match_keys == ["city"]

    def test_preview_without_db_keeps_legacy_behavior(self, db_engine, db, monkeypatch):
        monkeypatch.setattr(runner, "_load_llm_connection", lambda _db, _wid: None)
        job = _make_llm_job(db)
        session = db.get(DatasourceSession, job.session_id)
        preview = preview_job(job, session=session, fetch=_fetch([{"date": "2024-07-01"}]), now=NOW)
        # 没有 db 时按行 key 推断（无法读已有表字段），不落库
        assert preview.suggested_match_keys == ["date"]


class _FakeConnection:
    """backend-llm 的 LlmConnection 契约替身（base_url/model/api_key/system_prompt/has_api_key）."""

    base_url = "https://conn.example.com/v1"
    model = "conn-model"
    api_key = "sk-conn"
    system_prompt = "连接默认系统提示词"
    has_api_key = True


class TestBuildJobSpecWithConnection:
    def test_connection_fills_missing_url_model_and_key(self, db_engine, db, monkeypatch):
        monkeypatch.setattr(runner, "_load_llm_connection", lambda _db, _wid: _FakeConnection())
        job = _make_llm_job(db, request_spec={"url_template": "", "llm": {}})
        spec = build_job_spec(job, cursor_from="", today="2024-07-01", db=db)

        assert spec.request.url_template == "https://conn.example.com/v1"
        assert spec.request.llm["model"] == "conn-model"
        assert spec.extra_variables["api_key"] == "sk-conn"
        assert spec.extra_variables["system_prompt_default"] == "连接默认系统提示词"
        assert spec.extra_variables["today"] == "2024-07-01"

    def test_session_api_key_wins_over_connection(self, db_engine, db, monkeypatch):
        monkeypatch.setattr(runner, "_load_llm_connection", lambda _db, _wid: _FakeConnection())
        job = _make_llm_job(db)
        session = db.get(DatasourceSession, job.session_id)
        spec = build_job_spec(job, cursor_from="", today="2024-07-01", session=session, db=db)

        assert spec.extra_variables["api_key"] == "sk-test"
        # 连接默认值只在 request_spec 缺项时补齐，已有配置不被覆盖
        assert spec.request.url_template == "https://llm.example.com/v1"
        assert spec.request.llm["model"] == "model-a"
