"""datasource ADR 0039：落库写吞吐优化的等价性 / 固定开销单测.

覆盖：

- 批大小 10,000 与 5,000 分片写入结果等价（行集合与插入计数一致）；
- ``ensure_match_keys_index`` 进程内只执行一次 DDL 与提交，索引真实存在；
- ``_advance_backfill`` 不自行提交（水位与进度同批一次提交）；
- 落库失败时不推进水位（断点续跑口径不变）。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import MetaData, select, text
from sqlalchemy.orm import Session

from cndb.plugins.datasource.models import DatasourceEntrantCursor, DatasourceSyncJob, DatasourceSyncRun
from cndb.plugins.datasource.services import runner, write
from cndb.plugins.datasource.services.cursor import CursorConfig
from cndb.plugins.datasource.services.runner import _StreamingState
from cndb.plugins.datasource.services.write import upsert_rows
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl

UTC = dt.UTC
NOW = dt.datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
BACKFILL = {"strategy": "backfill_date", "field": "日期", "backfill_start": "2016-01-01"}


def _make_kline_table(session: Session, engine: Any, name: str = "股市日线") -> DataTable:
    """「股市日线」表：代码 / 日期 / 收盘 三列（幂等键 = 代码 + 日期）."""
    table = DataTable(workspace_id=1, name=name)
    table.ensure_db_name()
    session.add(table)
    session.commit()
    session.refresh(table)
    for order, (field_name, field_type) in enumerate((("代码", "text"), ("日期", "date"), ("收盘", "float"))):
        field = DataField(table_id=table.id, name=field_name, field_type=field_type, order=order)
        field.ensure_db_name()
        session.add(field)
    session.commit()
    session.refresh(table)
    ddl.create_table(engine, table)
    return table


def _read_rows(engine: Any, table: DataTable) -> list[dict[str, Any]]:
    """读回物理表内容（按代码、日期排序便于比较）."""
    metadata = MetaData()
    sa_table = ddl.build_sa_table(metadata, table)
    fields = [item for item in table.active_fields() if item.db_column_name]
    columns = [sa_table.c[item.db_column_name] for item in fields]
    with engine.connect() as conn:
        raw = conn.execute(select(*columns).order_by(*columns[:2])).all()
    return [{item.name: value for item, value in zip(fields, row, strict=True)} for row in raw]


def _daily_rows(count: int) -> list[dict[str, Any]]:
    """构造 count 行日线（代码轮换 4 个、日期逐日递增，保证幂等键唯一）."""
    rows: list[dict[str, Any]] = []
    start = dt.date(2026, 1, 1)
    for index in range(count):
        rows.append(
            {
                "代码": f"sh6005{index % 4:02d}",
                "日期": (start + dt.timedelta(days=index // 4)).isoformat(),
                "收盘": 1500.0 + index,
            }
        )
    return rows


class TestBatchSizeEquivalence:
    def test_single_batch_matches_split_batches(self, db: Session, db_engine):
        """一次 2,000 行 vs 4 批 500 行：行集合与写入计数等价（ADR 0039 D4 / I1）."""
        rows = _daily_rows(2000)
        keys = ["代码", "日期"]

        whole_table = _make_kline_table(db, db_engine, name="股市日线（整批）")
        whole = upsert_rows(db_engine, db, whole_table, rows, match_keys=keys, light=True)

        split_table = _make_kline_table(db, db_engine, name="股市日线（分片）")
        inserted = updated = 0
        for offset in range(0, len(rows), 500):
            outcome = upsert_rows(db_engine, db, split_table, rows[offset : offset + 500], match_keys=keys, light=True)
            inserted += outcome.inserted
            updated += outcome.updated

        assert (whole.inserted, whole.updated) == (2000, 0)
        assert (inserted, updated) == (whole.inserted, whole.updated)
        assert _read_rows(db_engine, whole_table) == _read_rows(db_engine, split_table)
        assert len(_read_rows(db_engine, split_table)) == 2000


class TestMatchKeysIndexCached:
    def test_repeated_calls_create_index_once(self, db: Session, db_engine, monkeypatch):
        """同表同键连续调用只执行一次 DDL 与提交，且索引真实存在（ADR 0039 D5）."""
        table = _make_kline_table(db, db_engine, name="股市日线（索引缓存）")
        monkeypatch.setattr(write, "_INDEXED_KEY_SETS", set())

        statements: list[str] = []
        commits: list[int] = []
        original_execute = db.execute
        original_commit = db.commit

        def spy_execute(statement: Any, *args: Any, **kwargs: Any):
            statements.append(str(statement))
            return original_execute(statement, *args, **kwargs)

        def spy_commit(*args: Any, **kwargs: Any):
            commits.append(1)
            return original_commit(*args, **kwargs)

        monkeypatch.setattr(db, "execute", spy_execute)
        monkeypatch.setattr(db, "commit", spy_commit)

        write.ensure_match_keys_index(db, table, ["代码", "日期"])
        write.ensure_match_keys_index(db, table, ["代码", "日期"])
        write.ensure_match_keys_index(db, table, ["代码", "日期"])

        ddl_calls = [statement for statement in statements if "CREATE INDEX" in statement]
        assert len(ddl_calls) == 1
        assert len(commits) == 1

        with db_engine.connect() as conn:
            index_names = {row[1] for row in conn.execute(text(f'PRAGMA index_list("{table.db_table_name}")'))}
        assert f"ix_{table.db_table_name}_match" in index_names

    def test_upsert_after_cached_index_still_writes(self, db: Session, db_engine, monkeypatch):
        """索引命中缓存后落表照常工作（不因跳过 DDL 影响幂等匹配）."""
        table = _make_kline_table(db, db_engine, name="股市日线（缓存后落表）")
        monkeypatch.setattr(write, "_INDEXED_KEY_SETS", set())

        first = upsert_rows(db_engine, db, table, _daily_rows(10), match_keys=["代码", "日期"], light=True)
        second = upsert_rows(db_engine, db, table, _daily_rows(10), match_keys=["代码", "日期"], light=True)

        assert (first.inserted, first.updated) == (10, 0)
        assert (second.inserted, second.updated) == (0, 10)


def _make_job(db: Session, table: DataTable) -> DatasourceSyncJob:
    job = DatasourceSyncJob(
        workspace_id=1,
        name="日线回补",
        provider="http_json",
        table_id=table.id,
        request_spec={"url_template": "https://api.example.com/k?sym={symbol}&end={end}"},
        parser="json",
        entrant_param="symbol",
        entrant_keys=["sh600519"],
        match_keys=["代码", "日期"],
        field_mapping={
            "symbol": {"name": "代码", "field_type": "text"},
            "日期": {"name": "日期", "field_type": "date"},
            "close": {"name": "收盘", "field_type": "float"},
        },
        cursor=dict(BACKFILL),
        schedule={"mode": "manual"},
        enabled=True,
        last_status="",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _make_run(db: Session, job: DatasourceSyncJob) -> DatasourceSyncRun:
    run = DatasourceSyncRun(job_id=job.id, status="running", trigger="manual", started_at=NOW)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _state(db: Session, job: DatasourceSyncJob, run: DatasourceSyncRun) -> _StreamingState:
    return _StreamingState(
        db,
        job,
        CursorConfig(**BACKFILL),
        user=None,
        lease=None,
        run=run,
    )


class TestBatchCommitAggregation:
    def test_advance_backfill_does_not_commit(self, db: Session, db_engine, monkeypatch):
        """水位只写 session，不自行提交（由进度写入口统一提交，ADR 0039 D5）."""
        table = _make_kline_table(db, db_engine, name="股市日线（水位提交）")
        job = _make_job(db, table)
        state = _state(db, job, _make_run(db, job))

        commits: list[int] = []
        original_commit = db.commit

        def spy_commit(*args: Any, **kwargs: Any):
            commits.append(1)
            return original_commit(*args, **kwargs)

        monkeypatch.setattr(db, "commit", spy_commit)
        state._advance_backfill([{"代码": "sh600519", "日期": "2026-09-01", "收盘": 1500.0}])

        assert commits == []
        assert state._watermarks == {"sh600519": "2026-09-01"}

        # 进度写入口一次性提交：水位随之落库，且计数一并回写
        state._publish_progress()
        assert len(commits) == 1
        cursors = {
            item.entrant: item.cursor_value for item in db.query(DatasourceEntrantCursor).filter_by(job_id=job.id).all()
        }
        assert cursors == {"sh600519": "2026-09-01"}

    def test_on_batch_persists_counts_and_watermark_in_one_commit(self, db: Session, db_engine):
        """整批：落库计数与水位在同一批内落库，用一次进度提交串起来."""
        table = _make_kline_table(db, db_engine, name="股市日线（整批提交）")
        job = _make_job(db, table)
        run = _make_run(db, job)
        state = _state(db, job, run)

        state.on_batch([{"代码": "sh600519", "日期": "2026-09-01", "收盘": 1500.0}])

        db.expire_all()
        persisted = db.get(DatasourceSyncRun, run.id)
        assert persisted is not None
        assert (persisted.fetched, persisted.inserted, persisted.skipped) == (1, 1, 0)
        cursors = {
            item.entrant: item.cursor_value for item in db.query(DatasourceEntrantCursor).filter_by(job_id=job.id).all()
        }
        assert cursors == {"sh600519": "2026-09-01"}

    def test_failed_persist_does_not_advance_watermark(self, db: Session, db_engine, monkeypatch):
        """落库抛错时 on_batch 外抛且水位不推进（断点续跑口径不变，ADR 0039 I3）."""
        table = _make_kline_table(db, db_engine, name="股市日线（落库失败）")
        job = _make_job(db, table)
        state = _state(db, job, _make_run(db, job))

        def boom(*args: Any, **kwargs: Any):
            raise RuntimeError("落库失败")

        monkeypatch.setattr(runner, "_persist_rows", boom)
        with pytest.raises(RuntimeError, match="落库失败"):
            state.on_batch([{"代码": "sh600519", "日期": "2026-09-01", "收盘": 1500.0}])

        assert db.query(DatasourceEntrantCursor).filter_by(job_id=job.id).count() == 0
