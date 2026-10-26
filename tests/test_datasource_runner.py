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


class TestStartJob:
    """ADR 0037 D1：建记录后转后台执行（测试用同步桩），进度与终态都落库."""

    def test_start_job_runs_in_background_and_records_progress(self, db_engine, db, monkeypatch):
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        rows = [{"city": "北京", "day": "2024-06-30", "temp": "31.5"}]

        from cndb.plugins.datasource.services.normalize import NormalizeResult
        from cndb.plugins.datasource.services.pipeline import PipelineOutcome

        def fake_pipeline(spec, *, progress=None, on_batch=None, **kwargs):
            if progress is not None:
                progress.set_total(1)
                progress.tick("北京")
            if on_batch is not None:
                on_batch([dict(row) for row in rows])
            normalize = NormalizeResult(rows=rows)
            return PipelineOutcome(rows=[], plans=1, succeeded=1, failures=[], normalize=normalize)

        monkeypatch.setattr(runner, "run_pipeline", fake_pipeline)
        launched: list[tuple[int, int]] = []

        def sync_spawn(factory, run_id, job_id, user_id, lease, trigger):
            launched.append((run_id, job_id))
            runner.execute_run_in_background(factory, run_id, job_id, user_id, lease, trigger)

        monkeypatch.setattr(runner, "_spawn_execution", sync_spawn)
        run = runner.start_job(db, job, now=NOW)

        assert launched == [(run.id, job.id)]
        db.refresh(run)
        assert run.status == "success"
        assert run.progress_total == 1
        assert run.progress_done == 1
        db.refresh(job)
        assert job.last_status == "success"
        assert _row_count(db_engine, table) == 1

    def test_start_job_marks_job_running_before_spawn(self, db_engine, db, monkeypatch):
        """释放请求时任务状态已是 running（前端据此立即开始轮询，C2/C3）."""
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        seen: list[str] = []

        def noop_spawn(factory, run_id, job_id, user_id, lease, trigger):
            db.refresh(job)
            seen.append(job.last_status)

        monkeypatch.setattr(runner, "_spawn_execution", noop_spawn)
        run = runner.start_job(db, job, now=NOW)

        assert seen == ["running"]
        assert run.status == "running"
        assert run.progress_total == 0

    def test_background_missing_job_logs_and_returns(self, db, caplog):
        """后台线程找不到任务/运行记录时只告警返回，不抛异常."""
        factory = runner.session_factory(db)
        runner.execute_run_in_background(factory, 9999, 9999, None, None, "manual")
        assert any("后台同步跳过" in record.message for record in caplog.records)


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

    def test_run_records_request_progress(self, db_engine, db):
        """ADR 0037 C2：运行记录落计划/完成请求数与当前标的."""
        table = _make_table(db, db_engine)
        job = _make_job(db, table)
        execution = execute_job(db, job, fetch=_fetch([{"city": "北京", "day": "2024-06-30", "temp": "31.5"}]), now=NOW)
        db.refresh(execution.run)
        assert execution.run.progress_total == 1
        assert execution.run.progress_done == 1
        assert execution.run.progress_entrant == "北京"
        assert _row_count(db_engine, table) == 1

    def test_failed_run_keeps_progress_snapshot(self, db_engine, db):
        """失败也落进度快照：前端能看到跑到第几个请求（ADR 0037 D4 边界 1）."""
        table = _make_table(db, db_engine)
        job = _make_job(db, table)

        def boom(_config: FetchConfig) -> list[dict[str, object]]:
            raise ValueError("HTTP 500: 源故障")

        execution = execute_job(db, job, fetch=boom, now=NOW)
        db.refresh(execution.run)
        assert execution.run.status == "failed"
        assert execution.run.progress_total == 1
        assert execution.run.progress_done == 1

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


# ── ADR 0033：股市日线双源同步到同一张本地表 ─────────────────


def _make_stock_table(session: Session, engine) -> DataTable:
    """建「股市日线」表：与示例 CSV 表头一致."""
    table = DataTable(workspace_id=1, name="股市日线")
    table.ensure_db_name()
    session.add(table)
    session.commit()
    session.refresh(table)
    specs = (
        ("股票代码", "text"),
        ("日期", "date"),
        ("开盘", "float"),
        ("收盘", "float"),
        ("最高", "float"),
        ("最低", "float"),
        ("成交量", "number"),
        ("来源", "text"),
        ("复权方式", "text"),
    )
    for order, (name, field_type) in enumerate(specs):
        # 小数位与 CSV 建表推断一致（NumberFieldConfig.decimals 默认 0 会四舍五入）
        config = {"decimals": 2} if field_type == "float" else {}
        field = DataField(table_id=table.id, name=name, field_type=field_type, order=order, config=config)
        field.ensure_db_name()
        session.add(field)
    session.commit()
    session.refresh(table)
    ddl.create_table(engine, table)
    return table


def _make_stock_job(db: Session, table: DataTable, source: str, **request_spec: object) -> DatasourceSyncJob:
    """按示例配置的形态建双源任务（只保留影响落表口径的声明）."""
    cursor: dict[str, object] = {"strategy": "none"}
    if source == "腾讯":
        cursor = {"strategy": "date", "field": "日期", "backfill_start": "2024-01-01"}
    job = DatasourceSyncJob(
        workspace_id=1,
        name=f"股市日线（{source}）",
        provider="http_json",
        table_id=table.id,
        request_spec={
            "url_template": f"https://api.example.com/{source}?symbol={{entrant}}",
            **request_spec,
            "row_defaults": {
                "来源": source,
                "复权方式": "前复权" if source == "腾讯" else "不复权",
            },
        },
        parser="json",
        entrant_param="symbol",
        entrant_keys=["sh600519", "sz000001"],
        match_keys=["股票代码", "日期", "来源"],
        field_mapping={
            "symbol": {"name": "股票代码", "field_type": "text"},
            "day": {"name": "日期", "field_type": "date"},
            "open": {"name": "开盘", "field_type": "float"},
            "close": {"name": "收盘", "field_type": "float"},
            "high": {"name": "最高", "field_type": "float"},
            "low": {"name": "最低", "field_type": "float"},
            "volume": {"name": "成交量", "field_type": "number"},
        },
        cursor=cursor,
        schedule={"mode": "manual"},
        enabled=True,
        last_status="",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _make_tencent_job(db: Session, table: DataTable) -> DatasourceSyncJob:
    """腾讯任务：rows_array 形态 + 成交量手→股缩放."""
    job = _make_stock_job(
        db,
        table,
        "腾讯",
        record_mode="rows_array",
        data_path="data.{entrant}.qfqday",
        record_layout={"日期": 0, "开盘": 1, "收盘": 2, "最高": 3, "最低": 4, "成交量": 5},
        time_window={"mode": "range"},
    )
    job.field_mapping = {
        **{key: value for key, value in job.field_mapping.items() if key != "volume"},
        "成交量": {"name": "成交量", "field_type": "number", "scale": 100},
    }
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _read_all(engine, table: DataTable) -> list[dict[str, object]]:
    metadata = MetaData()
    sa_table = ddl.build_sa_table(metadata, table)
    fields = [f for f in table.active_fields() if f.db_column_name]
    with engine.connect() as conn:
        raw = conn.execute(select(*[sa_table.c[f.db_column_name] for f in fields])).all()
    return [{field.name: value for field, value in zip(fields, row, strict=True)} for row in raw]


SINA_ROWS = [
    {
        "day": "2024-06-28",
        "open": "1502.00",
        "close": "1518.50",
        "high": "1523.00",
        "low": "1495.00",
        "volume": "3125400",
    },
    {
        "day": "2024-07-01",
        "open": "1518.50",
        "close": "1525.30",
        "high": "1531.00",
        "low": "1512.00",
        "volume": "2871900",
    },
]
TENCENT_RAW = [
    ["2024-06-28", "1503.00", "1519.60", "1524.10", "1496.30", "31005"],
    ["2024-07-01", "1519.60", "1526.10", "1531.80", "1513.20", "28563"],
]


class TestStockDailyDualSourceExample:
    """双源写同一张表：来源 / 复权方式补齐、成交量单位统一、幂等可重跑."""

    def test_sina_job_fills_source_and_is_idempotent(self, db_engine, db):
        table = _make_stock_table(db, db_engine)
        job = _make_stock_job(db, table, "新浪", record_mode="rows")

        first = execute_job(db, job, fetch=_fetch(SINA_ROWS), now=NOW)
        assert first.run.status == "success"
        assert (first.run.inserted, first.run.updated) == (4, 0)
        rows = _read_all(db_engine, table)
        assert {row["来源"] for row in rows} == {"新浪"}
        assert {row["复权方式"] for row in rows} == {"不复权"}
        assert {row["股票代码"] for row in rows} == {"sh600519", "sz000001"}
        assert {row["成交量"] for row in rows} == {3125400, 2871900}

        second = execute_job(db, job, fetch=_fetch(SINA_ROWS), now=NOW)
        assert second.run.inserted == 0
        assert second.run.updated == 4
        assert _row_count(db_engine, table) == 4

    def test_tencent_job_converts_lot_to_share_and_parses_rows_array(self, db_engine, db):
        table = _make_stock_table(db, db_engine)
        job = _make_tencent_job(db, table)
        # 假源模拟 parse 之后的形态：data_path / record_layout 由单测覆盖，这里验证落表口径
        parsed = [
            dict(zip(("日期", "开盘", "收盘", "最高", "最低", "成交量"), item, strict=True)) for item in TENCENT_RAW
        ]

        execution = execute_job(db, job, fetch=_fetch(parsed), now=NOW)
        assert execution.run.status == "success"
        assert execution.run.inserted == 4
        rows = _read_all(db_engine, table)
        assert {row["来源"] for row in rows} == {"腾讯"}
        assert {row["复权方式"] for row in rows} == {"前复权"}
        assert {row["成交量"] for row in rows} == {3100500, 2856300}, "成交量须由手换算为股"
        db.refresh(job)
        assert job.cursor["value"] == "2024-07-01"

    def test_both_sources_coexist_without_overwrite(self, db_engine, db):
        table = _make_stock_table(db, db_engine)
        sina = _make_stock_job(db, table, "新浪", record_mode="rows")
        tencent = _make_tencent_job(db, table)
        parsed = [
            dict(zip(("日期", "开盘", "收盘", "最高", "最低", "成交量"), item, strict=True)) for item in TENCENT_RAW
        ]

        execute_job(db, sina, fetch=_fetch(SINA_ROWS), now=NOW)
        execute_job(db, tencent, fetch=_fetch(parsed), now=NOW)

        rows = _read_all(db_engine, table)
        assert len(rows) == 8, "两源同标的同日应并存（幂等键含来源）"
        assert {row["来源"] for row in rows} == {"新浪", "腾讯"}
        assert _row_count(db_engine, table) == 8
        # 同一天同标的两行价格口径不同，互不覆盖
        moutai = [row for row in rows if row["股票代码"] == "sh600519" and str(row["日期"]).startswith("2024-06-28")]
        assert len(moutai) == 2
        assert {float(row["收盘"]) for row in moutai} == {1518.5, 1519.6}
