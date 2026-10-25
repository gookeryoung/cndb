"""datasource ADR 0034：runner 流式落表端到端单测（execute_job 级）.

覆盖：

- backfill_date 首轮锚点（today）、水位落 ``datasource_entrant_cursor``；
- 次轮锚点 = 水位 − 1 天；达 ``backfill_start`` 的标的零请求（剔除出标的集合）；
- 水位只向更早前移（断点续跑：本轮无更早数据不回退）；
- ``entrant_source`` 动态标的解析进入请求；
- 批间租约续期（易主即终止，run 落 failed）；
- 大批量分批落库（write 计数跨批累积）。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import MetaData, func, select
from sqlalchemy.orm import Session

from cndb.plugins.datasource.models import DatasourceEntrantCursor, DatasourceSyncJob
from cndb.plugins.datasource.services import runner
from cndb.plugins.datasource.services.runner import execute_job, preview_job
from cndb.plugins.datasource.services.scheduler import LeaseHandle, acquire_lease
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.importing.api_fetch import FetchConfig

UTC = dt.UTC
NOW = dt.datetime(2026, 10, 25, 16, 0, tzinfo=UTC)
TODAY = "2026-10-25"


def _make_kline_table(session: Session, engine) -> DataTable:
    """「股市日线」表：代码 / 日期 / 收盘 三列."""
    table = DataTable(workspace_id=1, name="股市日线")
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


def _make_backfill_job(db: Session, table: DataTable, **overrides: object) -> DatasourceSyncJob:
    payload: dict[str, object] = {
        "workspace_id": 1,
        "name": "日线回补",
        "provider": "http_json",
        "table_id": table.id,
        "request_spec": {"url_template": "https://api.example.com/k?sym={symbol}&end={end}"},
        "parser": "json",
        "entrant_param": "symbol",
        "entrant_keys": ["sh600519"],
        "match_keys": ["代码", "日期"],
        "field_mapping": {
            # 与真实种子一致：标的源键 symbol 映射到目标列（归一后行内无 symbol 键）
            "symbol": {"name": "代码", "field_type": "text"},
            "日期": {"name": "日期", "field_type": "date"},
            "close": {"name": "收盘", "field_type": "float"},
        },
        "cursor": {"strategy": "backfill_date", "field": "日期", "backfill_start": "2016-01-01"},
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


def _capture_fetch(seen: list[str], rows_by_symbol: dict[str, list[dict[str, object]]]):
    """记录请求 URL 并按 sym 参数返回对应行."""

    def fetch(config: FetchConfig) -> list[dict[str, object]]:
        seen.append(config.url)
        symbol = config.url.split("sym=")[1].split("&")[0]
        return [dict(row) for row in rows_by_symbol.get(symbol, [])]

    return fetch


def _row_count(engine, table: DataTable) -> int:
    metadata = MetaData()
    sa_table = ddl.build_sa_table(metadata, table)
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(sa_table)).scalar_one())


class TestBackfillExecution:
    def test_first_run_anchors_today_and_saves_watermarks(self, db_engine, db):
        table = _make_kline_table(db, db_engine)
        job = _make_backfill_job(db, table, entrant_keys=["sh600519", "sz000001"])
        seen: list[str] = []
        fetch = _capture_fetch(
            seen,
            {
                "sh600519": [{"日期": "2026-09-01", "close": 1500.0}],
                "sz000001": [{"日期": "2026-08-15", "close": 11.0}],
            },
        )

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        assert execution.run.status == "success"
        # 首轮无水位 → 锚点 = today
        assert all(f"end={TODAY}" in url for url in seen)
        assert len(seen) == 2
        # 水位按标的落库（各自本轮最早日期）
        assert execution.run.inserted == 2
        watermarks = {
            cursor.entrant: cursor.cursor_value
            for cursor in db.query(DatasourceEntrantCursor).filter_by(job_id=job.id).all()
        }
        assert watermarks == {"sh600519": "2026-09-01", "sz000001": "2026-08-15"}
        assert _row_count(db_engine, table) == 2

    def test_second_run_anchors_watermark_minus_one_day(self, db_engine, db):
        table = _make_kline_table(db, db_engine)
        job = _make_backfill_job(db, table, entrant_keys=["sh600519"])
        seen: list[str] = []
        fetch = _capture_fetch(seen, {"sh600519": [{"日期": "2020-06-30", "close": 1400.0}]})

        execute_job(db, job, fetch=fetch, now=NOW)  # 首轮：水位 2020-06-30
        seen.clear()
        execute_job(db, job, fetch=fetch, now=NOW)  # 次轮：锚点 = 2020-06-29
        assert all("end=2020-06-29" in url for url in seen)
        watermarks = {
            cursor.entrant: cursor.cursor_value
            for cursor in db.query(DatasourceEntrantCursor).filter_by(job_id=job.id).all()
        }
        assert watermarks == {"sh600519": "2020-06-30"}

    def test_preview_injects_watermark_anchor(self, db_engine, db):
        """预览与执行同口径：按标的水位注入 end 锚点（只读，不写水位）."""
        table = _make_kline_table(db, db_engine)
        job = _make_backfill_job(db, table, entrant_keys=["sh600519"])
        db.add(DatasourceEntrantCursor(job_id=job.id, entrant="sh600519", cursor_value="2020-06-30"))
        db.commit()
        seen: list[str] = []
        fetch = _capture_fetch(seen, {"sh600519": [{"日期": "2020-06-29", "close": 1400.0}]})

        preview = preview_job(job, db=db, fetch=fetch, now=NOW)
        assert preview.status == "success"
        assert seen == ["https://api.example.com/k?sym=sh600519&end=2020-06-29"]

    def test_finished_entrant_makes_zero_requests(self, db_engine, db):
        """水位已达 backfill_start 的标的剔除出标的集合 → 零请求."""
        table = _make_kline_table(db, db_engine)
        job = _make_backfill_job(db, table, entrant_keys=["sh600519", "sz000001"])
        # sh600519 已回补到位；sz000001 还有待补区间
        db.add(DatasourceEntrantCursor(job_id=job.id, entrant="sh600519", cursor_value="2016-01-01"))
        db.commit()
        seen: list[str] = []
        fetch = _capture_fetch(seen, {"sz000001": [{"日期": "2018-01-01", "close": 10.0}]})

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        assert execution.run.status == "success"
        # sh600519 已达标零请求；sz000001 无水位 → 首轮锚点 today
        assert seen == [f"https://api.example.com/k?sym=sz000001&end={TODAY}"]
        watermarks = {
            cursor.entrant: cursor.cursor_value
            for cursor in db.query(DatasourceEntrantCursor).filter_by(job_id=job.id).all()
        }
        assert watermarks == {"sh600519": "2016-01-01", "sz000001": "2018-01-01"}

    def test_watermark_truncated_to_backfill_start(self, db_engine, db):
        """响应最早日期早于 backfill_start → 水位截断到 backfill_start（下一轮即达标）."""
        table = _make_kline_table(db, db_engine)
        job = _make_backfill_job(db, table, entrant_keys=["sh600519"])
        seen: list[str] = []
        fetch = _capture_fetch(seen, {"sh600519": [{"日期": "2010-01-01", "close": 100.0}]})

        execute_job(db, job, fetch=fetch, now=NOW)
        seen.clear()
        execution = execute_job(db, job, fetch=fetch, now=NOW)  # 截断后达标 → 零请求
        assert seen == []
        # 达标后标的集合为空：整轮零请求且落 success（不得退回空标的伪请求而失败）
        assert execution.run.status == "success"
        assert execution.outcome is not None and execution.outcome.plans == 0
        cursor = db.query(DatasourceEntrantCursor).filter_by(job_id=job.id, entrant="sh600519").one()
        assert cursor.cursor_value == "2016-01-01"

    def test_watermark_never_moves_later(self, db_engine, db):
        """断点续跑：本轮最早日期不比现水位更早 → 水位不动（乱序 / 重叠窗口安全）."""
        table = _make_kline_table(db, db_engine)
        job = _make_backfill_job(db, table, entrant_keys=["sh600519"])
        db.add(DatasourceEntrantCursor(job_id=job.id, entrant="sh600519", cursor_value="2015-06-01"))
        db.commit()
        seen: list[str] = []
        fetch = _capture_fetch(seen, {"sh600519": [{"日期": "2024-01-01", "close": 1700.0}]})

        execute_job(db, job, fetch=fetch, now=NOW)
        cursor = db.query(DatasourceEntrantCursor).filter_by(job_id=job.id, entrant="sh600519").one()
        assert cursor.cursor_value == "2015-06-01"

    def test_missing_entrant_param_fails(self, db_engine, db):
        """backfill 任务未声明 entrant_param → 无法按标的推进水位，落 failed."""
        table = _make_kline_table(db, db_engine)
        job = _make_backfill_job(db, table, entrant_param=None)
        fetch = _capture_fetch([], {"sh600519": [{"日期": "2024-01-01", "close": 1.0}]})

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        assert execution.run.status == "failed"
        assert "entrant_param" in (execution.run.error_message or "")

    def test_entrant_source_dynamic_values(self, db_engine, db):
        """entrant_source 动态标的 + backfill 锚点组合：distinct 代码进请求."""
        table = _make_kline_table(db, db_engine)
        # 另建清单表并插入代码
        source = DataTable(workspace_id=1, name="股票清单")
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
            conn.execute(sa_source.insert(), [{column: code} for code in ("sz000001", "sh600519")])

        job = _make_backfill_job(
            db,
            table,
            entrant_keys=[],
            entrant_source={"table": "股票清单", "field": "代码", "prefix_in": ["sh6"]},
        )
        seen: list[str] = []
        fetch = _capture_fetch(seen, {})

        execute_job(db, job, fetch=fetch, now=NOW)
        assert seen == [f"https://api.example.com/k?sym=sh600519&end={TODAY}"]


class TestStreamingMisc:
    def test_large_run_flushes_in_batches(self, db_engine, db):
        """5001 行跨 2 批落库：write 计数跨批累积（DEFAULT_BATCH_SIZE=5000）."""
        table = _make_kline_table(db, db_engine)
        job = _make_backfill_job(db, table, entrant_keys=["sh600519"])
        rows = [{"日期": f"2026-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}", "close": float(i)} for i in range(5001)]
        # 同日期多次 upsert（幂等键合并），最终行数少但 fetched 计全量
        fetch = _capture_fetch([], {"sh600519": rows})

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        assert execution.run.status == "success"
        assert execution.run.fetched == 5001
        assert execution.write is not None and execution.write.inserted + execution.write.updated > 0

    def test_lease_renewal_failure_aborts(self, db_engine, db):
        """租约易主（被他者抢占）→ 批间续期失败 → run 落 failed 且带原因."""
        table = _make_kline_table(db, db_engine)
        job = _make_backfill_job(db, table, entrant_keys=["sh600519"])
        # 先让别人持有租约（本执行的 lease 句柄 owner 与之不符 → 续期必失败）
        acquire_lease(db, job.id, "someone-else", now=NOW)
        lease = LeaseHandle(job_id=job.id, owner="scheduler-me")
        fetch = _capture_fetch([], {"sh600519": [{"日期": "2026-01-05", "close": 1.0}]})

        execution = execute_job(db, job, fetch=fetch, now=NOW, lease=lease)
        assert execution.run.status == "failed"
        assert "租约已易主" in (execution.run.error_message or "")

    def test_lease_renewal_ok_when_owner_matches(self, db_engine, db):
        """租约自持：批间续期成功，运行正常完成."""
        table = _make_kline_table(db, db_engine)
        job = _make_backfill_job(db, table, entrant_keys=["sh600519"])
        lease = LeaseHandle(job_id=job.id, owner="scheduler-me")
        acquire_lease(db, job.id, "scheduler-me", now=NOW)
        fetch = _capture_fetch([], {"sh600519": [{"日期": "2026-01-05", "close": 1.0}]})

        execution = execute_job(db, job, fetch=fetch, now=NOW, lease=lease)
        assert execution.run.status == "success"
        assert "租约" not in (execution.run.error_message or "")

    def test_run_detail_records_filtered(self, db_engine, db):
        """row_filter 剔除数进 run.detail（快照零值行可观测）."""
        table = _make_kline_table(db, db_engine)
        payload: dict[str, object] = {
            "url_template": "https://api.example.com/k?sym={symbol}",
            # row_filter 字段是归一后的目标字段名（field_mapping 先行）
            "row_filter": {"field": "收盘", "op": ">", "value": 0},
        }
        job = _make_backfill_job(db, table, request_spec=payload, cursor={"strategy": "none"})
        fetch = _capture_fetch(
            [],
            {"sh600519": [{"日期": "2026-01-05", "close": 0.0}, {"日期": "2026-01-06", "close": 5.0}]},
        )

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        assert execution.run.status == "success"
        assert (execution.run.detail or {}).get("filtered") == 1
        assert execution.run.inserted == 1


class TestRunnerInternals:
    def test_inject_backfill_ends_filters_and_anchors(self, db_engine, db):
        """_inject_backfill_ends：达标标的剔除 + 未达标注入水位 − 1 天锚点."""
        from cndb.plugins.datasource.services.cursor import CursorConfig
        from cndb.plugins.datasource.services.runner import _inject_backfill_ends, build_job_spec

        table = _make_kline_table(db, db_engine)
        job = _make_backfill_job(db, table, entrant_keys=["sh600519", "sz000001", "sh601318"])
        db.add(DatasourceEntrantCursor(job_id=job.id, entrant="sh600519", cursor_value="2016-01-01"))
        db.add(DatasourceEntrantCursor(job_id=job.id, entrant="sz000001", cursor_value="2020-06-01"))
        db.commit()

        cursor_config = CursorConfig.from_dict(job.cursor)
        spec = build_job_spec(job, cursor_from="", today=TODAY, session=None, db=db)
        injected = _inject_backfill_ends(db, job, spec, cursor_config, today=TODAY)
        assert injected.entrant_values == ("sz000001", "sh601318")
        assert injected.entrant_ends == {"sz000001": "2020-05-31", "sh601318": TODAY}


def test_persist_rows_uses_light_mode(db_engine, db, monkeypatch):
    """同步落表走轻量模式（ADR 0035 D2）：upsert_rows 收到 light=True."""
    table = _make_kline_table(db, db_engine)
    job = _make_backfill_job(db, table, entrant_keys=["sh600519"])
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
    table = _make_kline_table(db, db_engine)
    job = _make_backfill_job(
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
