"""datasource ADR 0053 D2/D3：单轮翻页回补（cursor.page_to_start）端到端单测.

覆盖：

- 一轮内按标的水位反复翻页：短页即停、水位逐 pass 前推、多 pass 请求数累计；
- 空响应 / 水位不前移（失败）即剔除该标的；其余标的继续；
- 达 ``backfill_start`` 自然收敛（不依赖多轮 run）；
- 达到 pass 上限按 ``partial`` 留痕（不静默成功）；
- 未声明 ``page_to_start`` 时保持「一轮一页」（I4 兼容）。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import MetaData, func, select
from sqlalchemy.orm import Session

from cndb.plugins.datasource.models import DatasourceEntrantCursor, DatasourceSyncJob
from cndb.plugins.datasource.services import runner
from cndb.plugins.datasource.services.runner import execute_job
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.importing.api_fetch import FetchConfig

UTC = dt.UTC
NOW = dt.datetime(2026, 10, 25, 16, 0, tzinfo=UTC)
TODAY = "2026-10-25"


def _make_kline_table(session: Session, engine) -> DataTable:
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


def _make_job(db: Session, table: DataTable, **overrides: object) -> DatasourceSyncJob:
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
            "symbol": {"name": "代码", "field_type": "text"},
            "日期": {"name": "日期", "field_type": "date"},
            "close": {"name": "收盘", "field_type": "float"},
        },
        "cursor": {
            "strategy": "backfill_date",
            "field": "日期",
            "backfill_start": "2016-01-01",
            "page_to_start": True,
            "page_size": 2,
        },
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


def _watermarks(db: Session, job: DatasourceSyncJob) -> dict[str, str]:
    return {
        cursor.entrant: cursor.cursor_value for cursor in db.query(DatasourceEntrantCursor).filter_by(job_id=job.id)
    }


def _row_count(engine, table: DataTable) -> int:
    metadata = MetaData()
    sa_table = ddl.build_sa_table(metadata, table)
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(sa_table)).scalar_one())


def _symbol(config: FetchConfig) -> str:
    return config.url.split("sym=")[1].split("&")[0]


def _end(config: FetchConfig) -> str:
    return config.url.split("end=")[1]


class TestSingleRunPaging:
    def test_pages_until_short_page(self, db_engine, db):
        """pass1/pass2 取满页（2 行），pass3 只有 1 行（短页）→ 本轮即停，水位到最早日期."""
        table = _make_kline_table(db, db_engine)
        job = _make_job(db, table)
        pages = {
            TODAY: [{"日期": "2026-09-01", "close": 1.0}, {"日期": "2026-08-01", "close": 2.0}],
            "2026-07-31": [{"日期": "2026-06-01", "close": 3.0}, {"日期": "2026-05-01", "close": 4.0}],
            "2026-04-30": [{"日期": "2016-01-05", "close": 5.0}],
        }
        seen: list[str] = []

        def fetch(config: FetchConfig) -> list[dict[str, object]]:
            seen.append(f"{_symbol(config)}@{_end(config)}")
            assert _symbol(config) == "sh600519"
            return [dict(row) for row in pages[_end(config)]]

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        assert execution.run.status == "success"
        # 三轮请求，锚点逐轮前移（today → 水位−1 天 → 再前移）
        assert seen == ["sh600519@2026-10-25", "sh600519@2026-07-31", "sh600519@2026-04-30"]
        assert execution.outcome is not None
        assert execution.outcome.passes == 3
        assert execution.run.inserted == 5
        assert _watermarks(db, job) == {"sh600519": "2016-01-05"}
        assert _row_count(db_engine, table) == 5

    def test_empty_response_finishes_in_one_pass(self, db_engine, db):
        table = _make_kline_table(db, db_engine)
        job = _make_job(db, table)
        seen: list[str] = []

        def fetch(config: FetchConfig) -> list[dict[str, object]]:
            seen.append(_end(config))
            return []

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        assert execution.run.status == "success"
        assert seen == [TODAY]
        assert execution.outcome is not None and execution.outcome.passes == 1
        assert _watermarks(db, job) == {}

    def test_stops_when_reaching_backfill_start(self, db_engine, db):
        """每页都满页（不触发短页），水位被截断到 backfill_start 后自然收敛."""
        table = _make_kline_table(db, db_engine)
        job = _make_job(
            db,
            table,
            cursor={
                "strategy": "backfill_date",
                "field": "日期",
                "backfill_start": "2016-01-01",
                "page_to_start": True,
            },
        )
        seen: list[str] = []

        def fetch(config: FetchConfig) -> list[dict[str, object]]:
            seen.append(_end(config))
            # 每次都比 backfill_start 更早 → 水位截断到 2016-01-01，下一 pass 即达标
            return [{"日期": "2010-01-01", "close": 1.0}, {"日期": "2010-01-02", "close": 2.0}]

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        assert execution.run.status == "success"
        # 第 1 pass 水位即被截断到 backfill_start；第 2 pass 无可补标的（零请求），循环退出
        assert seen == [TODAY]
        assert execution.outcome is not None and execution.outcome.passes == 1
        assert _watermarks(db, job) == {"sh600519": "2016-01-01"}

    def test_failure_stops_only_that_entrant(self, db_engine, db):
        """单标的请求失败：该标的本轮剔除，另一标的继续翻页；运行落 partial."""
        table = _make_kline_table(db, db_engine)
        job = _make_job(db, table, entrant_keys=["sh600519", "sz000001"])
        calls: list[str] = []

        def fetch(config: FetchConfig) -> list[dict[str, object]]:
            symbol = _symbol(config)
            calls.append(f"{symbol}@{_end(config)}")
            if symbol == "sh600519":
                raise RuntimeError("boom")
            # 该标的每页都满页，第 2 页短页结束
            if len([call for call in calls if call.startswith("sz000001")]) == 1:
                return [{"日期": "2026-09-01", "close": 1.0}, {"日期": "2026-08-01", "close": 2.0}]
            return [{"日期": "2016-02-01", "close": 3.0}]

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        assert execution.run.status == "partial"
        assert [call for call in calls if call.startswith("sh600519")] == ["sh600519@2026-10-25"]
        assert _watermarks(db, job) == {"sz000001": "2016-02-01"}
        assert execution.outcome is not None
        assert [failure.entrant for failure in execution.outcome.failures] == ["sh600519"]

    def test_pass_cap_marks_partial(self, db_engine, db, monkeypatch):
        table = _make_kline_table(db, db_engine)
        job = _make_job(
            db,
            table,
            cursor={
                "strategy": "backfill_date",
                "field": "日期",
                "backfill_start": "2016-01-01",
                "page_to_start": True,
                "page_size": 1,
            },
        )
        monkeypatch.setattr(runner, "MAX_BACKFILL_PASSES", 3)
        calls: list[str] = []

        def fetch(config: FetchConfig) -> list[dict[str, object]]:
            calls.append(_end(config))
            # 每页满页、水位每次前移一天 → 3 个 pass 仍未到头，触碰上限
            day = dt.date(2026, 1, 1) - dt.timedelta(days=len(calls) - 1)
            return [{"日期": day.isoformat(), "close": 1.0}]

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        assert len(calls) == 3
        assert execution.run.status == "partial"
        assert execution.run.detail["passes"] == 3
        assert execution.run.detail["truncated"] is True

    def test_default_single_pass_without_page_to_start(self, db_engine, db):
        """未声明 page_to_start：保持一轮一页（I4 兼容）."""
        table = _make_kline_table(db, db_engine)
        job = _make_job(
            db, table, cursor={"strategy": "backfill_date", "field": "日期", "backfill_start": "2016-01-01"}
        )
        seen: list[str] = []

        def fetch(config: FetchConfig) -> list[dict[str, object]]:
            seen.append(_end(config))
            return [{"日期": "2026-09-01", "close": 1.0}, {"日期": "2026-08-01", "close": 2.0}]

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        assert seen == [TODAY]
        assert execution.outcome is not None and execution.outcome.passes == 1

    def test_progress_total_accumulates_over_passes(self, db_engine, db):
        table = _make_kline_table(db, db_engine)
        job = _make_job(db, table, entrant_keys=["sh600519", "sz000001"])
        page_counts: dict[str, int] = {}

        def fetch(config: FetchConfig) -> list[dict[str, object]]:
            symbol = _symbol(config)
            page_counts[symbol] = page_counts.get(symbol, 0) + 1
            if page_counts[symbol] == 1:
                return [{"日期": "2026-09-01", "close": 1.0}, {"日期": "2026-08-01", "close": 2.0}]
            return []

        execution = execute_job(db, job, fetch=fetch, now=NOW)
        # 2 标的 × 2 pass = 4 个请求，进度总数按整轮累计（而非最后一个 pass）
        assert execution.run.progress_total == 4
        assert execution.run.progress_done == 4
