"""datasource ADR 0034 / ADR 0104：runner 流式落表端到端单测（execute_job 级）.

覆盖：

- date 游标：首跑窗口起点 ``backfill_start``，次跑用推进后的 ``value``；
- 空响应不推进游标（无新数据保持原值）；
- ``entrant_source`` 动态标的解析进入请求；
- 批间租约续期（易主即终止，run 落 failed）；
- 大批量分批落库（write 计数跨批累积）；
- 落表走轻量模式；``llm_prompt`` 不走 ``on_batch``。
"""

from __future__ import annotations

import datetime as dt
from urllib.parse import parse_qs, urlparse

from sqlalchemy import MetaData, func, select
from sqlalchemy.orm import Session

from cndb.plugins.datasource.models import DatasourceSyncJob
from cndb.plugins.datasource.services import runner
from cndb.plugins.datasource.services.runner import execute_job
from cndb.plugins.datasource.services.scheduler import LeaseHandle, acquire_lease
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.importing.api_fetch import FetchConfig

UTC = dt.UTC
NOW = dt.datetime(2026, 10, 25, 16, 0, tzinfo=UTC)
TODAY = "2026-10-25"
WINDOW_CURSOR = {"strategy": "date", "field": "日期", "backfill_start": "2016-01-01"}


def _make_sync_table(session: Session, engine) -> DataTable:
    """「同步宽表」表：代码 / 日期 / 收盘 三列."""
    table = DataTable(workspace_id=1, name="同步宽表")
    table.ensure_db_name()
    session.add(table)
    session.commit()
    session.refresh(table)
    for order, (name, field_type) in enumerate((("代码", "text"), ("日期", "date"), ("收盘", "float"))):
        field = DataField(table_id=table.id, name=name, field_type=field_type, order=order)
        field.ensure_db_name()
        session.add(field)
    session.commit()
    session.refresh(table)
    ddl.create_table(engine, table)
    return table


def _make_job(db: Session, table: DataTable, **overrides: object) -> DatasourceSyncJob:
    payload: dict[str, object] = {
        "workspace_id": 1,
        "name": "日线窗口",
        "provider": "http_json",
        "table_id": table.id,
        "request_spec": {
            "url_template": "https://api.example.com/k?sym={symbol}&start={start}&end={end}",
            "time_window": {"mode": "range"},
        },
        "parser": "json",
        "entrant_param": "symbol",
        "entrant_keys": ["item-a"],
        "match_keys": ["代码", "日期"],
        "field_mapping": {
            # 与真实种子一致：标的源键 symbol 映射到目标列（归一后行内无 symbol 键）
            "symbol": {"name": "代码", "field_type": "text"},
            "日期": {"name": "日期", "field_type": "date"},
            "close": {"name": "收盘", "field_type": "float"},
        },
        "cursor": dict(WINDOW_CURSOR),
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


def _query(config: FetchConfig) -> dict[str, list[str]]:
    return parse_qs(urlparse(config.url).query)


def _capture_fetch(seen: list[FetchConfig], rows_by_symbol: dict[str, list[dict[str, object]]]):
    """记录请求并按 sym 参数返回对应行."""

    def fetch(config: FetchConfig) -> list[dict[str, object]]:
        seen.append(config)
        symbol = _query(config)["sym"][0]
        return [dict(row) for row in rows_by_symbol.get(symbol, [])]

    return fetch


def _row_count(engine, table: DataTable) -> int:
    metadata = MetaData()
    sa_table = ddl.build_sa_table(metadata, table)
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(sa_table)).scalar_one())


class TestDateWindowExecution:
    def test_first_run_starts_at_backfill_start(self, db_engine, db):
        table = _make_sync_table(db, db_engine)
        job = _make_job(db, table, entrant_keys=["item-a", "sz000001"])
        seen: list[FetchConfig] = []
        fetch = _capture_fetch(
            seen,
            {
                "item-a": [{"日期": "2020-06-30", "close": 1500.0}],
                "sz000001": [{"日期": "2020-08-15", "close": 11.0}],
            },
        )

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        assert execution.run.status == "success"
        assert len(seen) == 2
        assert [item["start"][0] for item in map(_query, seen)] == ["2016-01-01", "2016-01-01"]
        assert [item["end"][0] for item in map(_query, seen)] == [TODAY, TODAY]
        # 游标取本轮最大日期（只前进不后退）
        assert (execution.cursor_from, execution.cursor_to) == ("2016-01-01", "2020-08-15")
        db.refresh(job)
        assert job.cursor["value"] == "2020-08-15"
        assert _row_count(db_engine, table) == 2

    def test_second_run_uses_advanced_cursor(self, db_engine, db):
        table = _make_sync_table(db, db_engine)
        job = _make_job(db, table, entrant_keys=["item-a"])
        seen: list[FetchConfig] = []
        fetch = _capture_fetch(seen, {"item-a": [{"日期": "2020-06-30", "close": 1400.0}]})

        execute_job(db, job, fetch=fetch, now=NOW)
        seen.clear()
        second = execute_job(db, job, fetch=fetch, now=NOW)

        assert second.cursor_from == "2020-06-30"
        assert [item["start"][0] for item in map(_query, seen)] == ["2020-06-30"]
        db.refresh(job)
        assert job.cursor["value"] == "2020-06-30"

    def test_empty_response_keeps_cursor(self, db_engine, db):
        table = _make_sync_table(db, db_engine)
        job = _make_job(db, table, entrant_keys=["item-a"])
        fetch = _capture_fetch([], {})

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        assert execution.run.status == "success"
        assert execution.cursor_to == ""
        db.refresh(job)
        assert "value" not in job.cursor or not job.cursor["value"]

    def test_entrant_source_dynamic_values(self, db_engine, db):
        """entrant_source 动态标的：distinct 代码按前缀过滤后进入请求."""
        table = _make_sync_table(db, db_engine)
        source = DataTable(workspace_id=1, name="标的清单")
        source.ensure_db_name()
        db.add(source)
        db.commit()
        db.refresh(source)
        field = DataField(table_id=source.id, name="代码", field_type="text", order=0)
        field.ensure_db_name()
        db.add(field)
        db.commit()
        db.refresh(source)
        ddl.create_table(db_engine, source)
        column = source.active_fields()[0].db_column_name
        metadata = MetaData()
        sa_source = ddl.build_sa_table(metadata, source)
        with db_engine.begin() as conn:
            conn.execute(sa_source.insert(), [{column: code} for code in ("sz000001", "item-a")])

        job = _make_job(
            db,
            table,
            entrant_keys=[],
            entrant_source={"table": "标的清单", "field": "代码", "prefix_in": ["item"]},
        )
        seen: list[FetchConfig] = []
        fetch = _capture_fetch(seen, {})

        execute_job(db, job, fetch=fetch, now=NOW)
        assert [item["sym"][0] for item in map(_query, seen)] == ["item-a"]


class TestStreamingMisc:
    def test_large_run_flushes_in_batches(self, db_engine, db):
        """10001 行跨 2 批落库：write 计数跨批累积（DEFAULT_BATCH_SIZE=10000）."""
        table = _make_sync_table(db, db_engine)
        job = _make_job(db, table, entrant_keys=["item-a"])
        rows = [{"日期": f"2026-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}", "close": float(i)} for i in range(10001)]
        # 同日期多次 upsert（幂等键合并），最终行数少但 fetched 计全量
        fetch = _capture_fetch([], {"item-a": rows})

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        assert execution.run.status == "success"
        assert execution.run.fetched == 10001
        assert execution.write is not None and execution.write.inserted + execution.write.updated > 0

    def test_lease_renewal_failure_aborts(self, db_engine, db):
        """租约易主（被他者抢占）→ 批间续期失败 → run 落 failed 且带原因."""
        table = _make_sync_table(db, db_engine)
        job = _make_job(db, table, entrant_keys=["item-a"])
        # 先让别人持有租约（本执行的 lease 句柄 owner 与之不符 → 续期必失败）
        acquire_lease(db, job.id, "someone-else", now=NOW)
        lease = LeaseHandle(job_id=job.id, owner="scheduler-me")
        fetch = _capture_fetch([], {"item-a": [{"日期": "2026-01-05", "close": 1.0}]})

        execution = execute_job(db, job, fetch=fetch, now=NOW, lease=lease)
        assert execution.run.status == "failed"
        assert "租约已易主" in (execution.run.error_message or "")

    def test_lease_renewal_ok_when_owner_matches(self, db_engine, db):
        """租约自持：批间续期成功，运行正常完成."""
        table = _make_sync_table(db, db_engine)
        job = _make_job(db, table, entrant_keys=["item-a"])
        lease = LeaseHandle(job_id=job.id, owner="scheduler-me")
        acquire_lease(db, job.id, "scheduler-me", now=NOW)
        fetch = _capture_fetch([], {"item-a": [{"日期": "2026-01-05", "close": 1.0}]})

        execution = execute_job(db, job, fetch=fetch, now=NOW, lease=lease)
        assert execution.run.status == "success"
        assert "租约" not in (execution.run.error_message or "")


def test_persist_rows_uses_light_mode(db_engine, db, monkeypatch):
    """同步落表走轻量模式（ADR 0035 D2）：upsert_rows 收到 light=True."""
    table = _make_sync_table(db, db_engine)
    job = _make_job(db, table, entrant_keys=["item-a"])
    captured: dict[str, object] = {}

    def fake_upsert(*_args, **kwargs):
        captured.update(kwargs)
        return runner.WriteOutcome(fetched=1, inserted=1)

    monkeypatch.setattr(runner, "upsert_rows", fake_upsert)
    runner._persist_rows(db, job, [{"日期": "2026-10-24", "收盘": 1.0}], user=None)
    assert captured["light"] is True
    assert captured["match_keys"] == ["代码", "日期"]


def test_streaming_state_not_leaked_into_llm_path(db_engine, db, monkeypatch):
    """llm_prompt 仍走全量路径：不注入 on_batch（回归保护）."""
    table = _make_sync_table(db, db_engine)
    job = _make_job(
        db,
        table,
        provider="llm_prompt",
        request_spec={"url_template": "https://api.example.com/w", "prompt": {"user_template": "x"}},
        cursor={"strategy": "none"},
    )
    seen: dict[str, object] = {}

    def fake_pipeline(_spec, **kwargs):
        seen["on_batch"] = kwargs.get("on_batch")
        return runner.PipelineOutcome(rows=[], plans=1, succeeded=1)

    monkeypatch.setattr(runner, "run_pipeline", fake_pipeline)
    execution = execute_job(db, job, now=NOW)
    assert execution.run.status == "success"
    assert seen["on_batch"] is None
