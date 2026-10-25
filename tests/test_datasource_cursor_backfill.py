"""datasource ADR 0034：backfill_date 游标纯函数 + 水位表读写 + 标的动态来源单测.

覆盖：

- ``backfill_anchor`` / ``backfill_advance`` / ``min_field_value`` 的边界
  （无水位、水位 − 1 天、截断到 backfill_start、只向更早前移）；
- ``datasource_entrant_cursor`` 读写（roundtrip、只向更早前移的 DB 层防御）；
- ``resolve_entrant_values``（动态 distinct + 静态并集、prefix_in 过滤、坏配置报错）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import MetaData
from sqlalchemy.orm import Session

from cndb.plugins.datasource.models import DatasourceEntrantCursor
from cndb.plugins.datasource.providers.base import ProviderError
from cndb.plugins.datasource.services.cursor import (
    CursorConfig,
    backfill_advance,
    backfill_anchor,
    min_field_value,
)
from cndb.plugins.datasource.services.entrant_state import (
    load_backfill_cursors,
    resolve_entrant_values,
    save_backfill_cursor,
)
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl


class TestCursorConfigBackfill:
    def test_requires_field(self):
        with pytest.raises(ProviderError, match="field"):
            CursorConfig(strategy="backfill_date", backfill_start="2016-01-01")

    def test_requires_backfill_start(self):
        with pytest.raises(ProviderError, match="backfill_start"):
            CursorConfig(strategy="backfill_date", field="日期")

    def test_flags(self):
        config = CursorConfig(strategy="backfill_date", field="日期", backfill_start="2016-01-01")
        assert config.is_backfill is True
        assert config.is_windowed is False
        assert CursorConfig(strategy="date", field="day").is_backfill is False


class TestBackfillAnchor:
    def test_no_watermark_anchors_today(self):
        assert backfill_anchor(None, backfill_start="2016-01-01", today="2026-10-25") == "2026-10-25"

    def test_watermark_minus_one_day(self):
        # 闰年边界：2020-03-01 的前一天是 2020-02-29
        assert backfill_anchor("2020-03-01", backfill_start="2016-01-01", today="2026-10-25") == "2020-02-29"

    def test_anchor_equal_backfill_start_kept(self):
        # 锚点 == backfill_start 仍要拉最后一根（< 才跳过）
        assert backfill_anchor("2016-01-02", backfill_start="2016-01-01", today="2026-10-25") == "2016-01-01"

    def test_anchor_before_backfill_start_skips(self):
        assert backfill_anchor("2016-01-01", backfill_start="2016-01-01", today="2026-10-25") is None

    def test_invalid_watermark_raises(self):
        with pytest.raises(ProviderError, match="ISO"):
            backfill_anchor("2020/03/01", backfill_start="2016-01-01", today="2026-10-25")


class TestBackfillAdvance:
    ROWS = [{"日期": "2020-03-15"}, {"日期": "2019-06-01"}, {"日期": "2021-01-01"}]

    def test_empty_rows_keep_watermark(self):
        assert backfill_advance("2020-01-01", [], field="日期", backfill_start="2016-01-01") == "2020-01-01"

    def test_no_watermark_takes_earliest(self):
        assert backfill_advance(None, self.ROWS, field="日期", backfill_start="2016-01-01") == "2019-06-01"

    def test_truncates_to_backfill_start(self):
        rows = [{"日期": "2010-01-01"}, {"日期": "2012-06-01"}]
        assert backfill_advance(None, rows, field="日期", backfill_start="2016-01-01") == "2016-01-01"

    def test_never_moves_later(self):
        rows = [{"日期": "2021-05-01"}]
        assert backfill_advance("2020-01-01", rows, field="日期", backfill_start="2016-01-01") == "2020-01-01"

    def test_moves_earlier(self):
        rows = [{"日期": "2018-01-01"}]
        assert backfill_advance("2020-01-01", rows, field="日期", backfill_start="2016-01-01") == "2018-01-01"

    def test_all_bad_dates_keep_watermark(self):
        rows = [{"日期": "休市"}, {"日期": None}]
        assert backfill_advance("2020-01-01", rows, field="日期", backfill_start="2016-01-01") == "2020-01-01"


class TestMinFieldValue:
    def test_takes_earliest(self):
        rows = [{"日期": "2024-03-05"}, {"日期": "2024-02-01"}, {"日期": "2024-12-30"}]
        assert min_field_value(rows, "日期") == "2024-02-01"

    def test_ignores_bad_values(self):
        rows = [{"日期": "bad"}, {"日期": None}, {"日期": ""}, {"日期": "2024-02-01"}]
        assert min_field_value(rows, "日期") == "2024-02-01"

    def test_all_bad_returns_none(self):
        assert min_field_value([{"日期": "bad"}, {"收盘": 1.0}], "日期") is None


class TestEntrantCursorStore:
    def test_save_then_load_roundtrip(self, db_engine, db):
        save_backfill_cursor(db, 101, "sh600519", "2020-01-01")
        save_backfill_cursor(db, 101, "sz000001", "2019-01-01")
        db.commit()
        assert load_backfill_cursors(db, 101) == {"sh600519": "2020-01-01", "sz000001": "2019-01-01"}
        assert load_backfill_cursors(db, 102) == {}

    def test_save_only_moves_earlier(self, db_engine, db):
        save_backfill_cursor(db, 101, "sh600519", "2020-01-01")
        db.commit()
        save_backfill_cursor(db, 101, "sh600519", "2021-01-01")  # 更晚 → 不覆盖
        db.commit()
        assert load_backfill_cursors(db, 101) == {"sh600519": "2020-01-01"}
        save_backfill_cursor(db, 101, "sh600519", "2019-01-01")  # 更早 → 覆盖
        db.commit()
        assert load_backfill_cursors(db, 101) == {"sh600519": "2019-01-01"}

    def test_save_equal_watermark_no_duplicate(self, db_engine, db):
        save_backfill_cursor(db, 101, "sh600519", "2020-01-01")
        db.commit()
        save_backfill_cursor(db, 101, "sh600519", "2020-01-01")  # 相等 → 不覆盖
        db.commit()
        assert db.query(DatasourceEntrantCursor).count() == 1


def _make_source_table(session: Session, engine) -> DataTable:
    """建「股票清单」表（单 text 字段「代码」）并落物理 DDL."""
    table = DataTable(workspace_id=1, name="股票清单")
    table.ensure_db_name()
    session.add(table)
    session.commit()
    session.refresh(table)
    field = DataField(table_id=table.id, name="代码", field_type="text", order=0)
    field.ensure_db_name()
    session.add(field)
    session.commit()
    session.refresh(table)
    ddl.create_table(engine, table)
    return table


def _insert_codes(engine, table: DataTable, codes: list[str]) -> None:
    column = table.active_fields()[0].db_column_name
    metadata = MetaData()
    sa_table = ddl.build_sa_table(metadata, table)
    with engine.begin() as conn:
        conn.execute(sa_table.insert(), [{column: code} for code in codes])


class TestResolveEntrantValues:
    def test_static_only_without_source(self, db_engine, db):
        from cndb.plugins.datasource.models import DatasourceSyncJob

        job = DatasourceSyncJob(workspace_id=1, name="j", provider="http_json", entrant_keys=["sh600519"])
        db.add(job)
        db.commit()
        assert resolve_entrant_values(db, job) == ("sh600519",)

    def test_dynamic_union_static_and_prefix_filter(self, db_engine, db):
        from cndb.plugins.datasource.models import DatasourceSyncJob

        table = _make_source_table(db, db_engine)
        _insert_codes(db_engine, table, ["sh600519", "sh688001", "sz000001", "sh600519", ""])
        job = DatasourceSyncJob(
            workspace_id=1,
            name="j",
            provider="http_json",
            entrant_keys=["sh601318"],
            entrant_source={"table": "股票清单", "field": "代码", "prefix_in": ["sh60"]},
        )
        db.add(job)
        db.commit()
        # 动态 distinct（sh688001 / sz000001 不满足 prefix_in）+ 静态键并集；空值剔除
        assert resolve_entrant_values(db, job) == ("sh601318", "sh600519")

    def test_empty_source_table_is_allowed(self, db_engine, db):
        from cndb.plugins.datasource.models import DatasourceSyncJob

        table = _make_source_table(db, db_engine)
        assert table.active_fields()[0].name == "代码"
        job = DatasourceSyncJob(
            workspace_id=1,
            name="j",
            provider="http_json",
            entrant_source={"table": "股票清单", "field": "代码"},
        )
        db.add(job)
        db.commit()
        assert resolve_entrant_values(db, job) == ()

    def test_missing_table_raises(self, db_engine, db):
        from cndb.plugins.datasource.models import DatasourceSyncJob

        job = DatasourceSyncJob(
            workspace_id=1,
            name="j",
            provider="http_json",
            entrant_source={"table": "不存在", "field": "代码"},
        )
        db.add(job)
        db.commit()
        with pytest.raises(ValueError, match="不存在"):
            resolve_entrant_values(db, job)

    def test_missing_field_raises(self, db_engine, db):
        from cndb.plugins.datasource.models import DatasourceSyncJob

        table = _make_source_table(db, db_engine)
        assert table.active_fields()[0].name == "代码"
        job = DatasourceSyncJob(
            workspace_id=1,
            name="j",
            provider="http_json",
            entrant_source={"table": "股票清单", "field": "没有这列"},
        )
        db.add(job)
        db.commit()
        with pytest.raises(ValueError, match="字段不存在"):
            resolve_entrant_values(db, job)
