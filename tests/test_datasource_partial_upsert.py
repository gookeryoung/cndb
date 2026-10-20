"""datasource：部分列 upsert（``partial`` 语义）落表单测.

多 job 分列写同一行（日线前复权 / 周线前复权 / 日线后复权）时，
``upsert_rows`` 只更新本次 job 实际提供的列，未提供的列保持原值；
同时固化它与旧 gap-filling 语义的差异（旧语义会把兄弟列清空），避免回退。

覆盖：三 job 分列不互相覆盖 / 二次更新只动提供的列 / 新行未提供列为 NULL /
必填列由其他 job 负责时不报错 / 已提供的非法值仍被拒绝 / 旧语义对照。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import MetaData, select
from sqlalchemy.orm import Session

from cndb.plugins.datasource.services.write import upsert_rows
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.importing.importer import Importer

SYMBOL = "sh600519"
KLINE_FIELDS = ("日线前复权", "日线后复权", "周线前复权", "月线前复权")
DAY_QFQ = [{"date": "2024-01-02", "open": 1680.0, "close": 1700.0}]
DAY_HFQ = [{"date": "2024-01-02", "open": 2680.0, "close": 2700.0}]
WEEK_QFQ = [{"date": "2024-01-05", "open": 1680.0, "close": 1690.0}]
MONTH_QFQ = [{"date": "2024-01-31", "open": 1680.0, "close": 1720.0}]


def _make_table(session: Session, engine: Any, *, required_kline: str | None = None) -> DataTable:
    """建一张「自选股」形态的表：代码必填 + 5 个 K 线 JSON 列 + 最新行情列."""
    table = DataTable(workspace_id=1, name="自选股（部分列 upsert）")
    table.ensure_db_name()
    session.add(table)
    session.commit()
    session.refresh(table)

    specs: list[tuple[str, str, bool]] = [("股票代码", "text", True)]
    specs += [(name, "json", name == required_kline) for name in KLINE_FIELDS]
    specs += [("最新价", "float", False)]
    for order, (name, field_type, required) in enumerate(specs):
        config = {"decimals": 2} if field_type == "float" else {}
        field = DataField(
            table_id=table.id,
            name=name,
            field_type=field_type,
            order=order,
            required=required,
            config=config,
        )
        field.ensure_db_name()
        session.add(field)
    session.commit()
    session.refresh(table)
    ddl.create_table(engine, table)
    return table


def _read_rows(engine: Any, table: DataTable) -> list[dict[str, Any]]:
    """读回物理表内容，键为逻辑字段名（json 列反序列化，便于断言）."""
    metadata = MetaData()
    sa_table = ddl.build_sa_table(metadata, table)
    fields = [f for f in table.active_fields() if f.db_column_name]
    with engine.connect() as conn:
        raw = conn.execute(select(*[sa_table.c[f.db_column_name] for f in fields])).all()

    rows: list[dict[str, Any]] = []
    for raw_row in raw:
        item: dict[str, Any] = {}
        for field, value in zip(fields, raw_row, strict=True):
            if field.field_type == "json" and isinstance(value, str):
                item[field.name] = json.loads(value)
            else:
                item[field.name] = value
        rows.append(item)
    return rows


class TestSiblingColumnsPreserved:
    def test_three_jobs_share_one_row_without_overwrite(self, db: Session, db_engine):
        """日线 qfq → 周线 qfq → 日线 hfq：三列都保留，互不覆盖."""
        table = _make_table(db, db_engine)

        first = upsert_rows(
            db_engine, db, table, [{"股票代码": SYMBOL, "日线前复权": DAY_QFQ}], match_keys=["股票代码"]
        )
        assert (first.inserted, first.updated, first.failed_rows) == (1, 0, 0)

        second = upsert_rows(
            db_engine, db, table, [{"股票代码": SYMBOL, "周线前复权": WEEK_QFQ}], match_keys=["股票代码"]
        )
        assert (second.inserted, second.updated, second.failed_rows) == (0, 1, 0)

        third = upsert_rows(
            db_engine, db, table, [{"股票代码": SYMBOL, "日线后复权": DAY_HFQ}], match_keys=["股票代码"]
        )
        assert (third.inserted, third.updated, third.failed_rows) == (0, 1, 0)

        rows = _read_rows(db_engine, table)
        assert len(rows) == 1  # 幂等：同一代码只留一行
        assert rows[0]["日线前复权"] == DAY_QFQ
        assert rows[0]["周线前复权"] == WEEK_QFQ
        assert rows[0]["日线后复权"] == DAY_HFQ
        assert rows[0]["月线前复权"] is None

    def test_second_write_only_touches_provided_columns(self, db: Session, db_engine):
        table = _make_table(db, db_engine)
        upsert_rows(
            db_engine,
            db,
            table,
            [
                {
                    "股票代码": SYMBOL,
                    "日线前复权": DAY_QFQ,
                    "周线前复权": WEEK_QFQ,
                    "月线前复权": MONTH_QFQ,
                    "最新价": 21.5,
                }
            ],
            match_keys=["股票代码"],
        )

        outcome = upsert_rows(
            db_engine, db, table, [{"股票代码": SYMBOL, "日线前复权": DAY_HFQ}], match_keys=["股票代码"]
        )
        assert (outcome.inserted, outcome.updated) == (0, 1)

        row = _read_rows(db_engine, table)[0]
        assert row["日线前复权"] == DAY_HFQ  # 本次提供的列被覆盖
        assert row["周线前复权"] == WEEK_QFQ  # 未提供 → 保留
        assert row["月线前复权"] == MONTH_QFQ
        assert row["最新价"] == 21.5
        assert row["日线后复权"] is None

    def test_new_row_keeps_absent_columns_null(self, db: Session, db_engine):
        table = _make_table(db, db_engine)
        outcome = upsert_rows(
            db_engine, db, table, [{"股票代码": SYMBOL, "月线前复权": MONTH_QFQ}], match_keys=["股票代码"]
        )
        assert outcome.inserted == 1
        row = _read_rows(db_engine, table)[0]
        assert row["月线前复权"] == MONTH_QFQ
        assert row["日线前复权"] is None
        assert row["周线前复权"] is None
        assert row["最新价"] is None


class TestRequiredAndValidation:
    def test_required_kline_field_left_to_other_job(self, db: Session, db_engine):
        """必填的日线列由日线 job 负责；周线 job 不提供该列也不应报必填错误."""
        table = _make_table(db, db_engine, required_kline="日线前复权")

        day = upsert_rows(db_engine, db, table, [{"股票代码": SYMBOL, "日线前复权": DAY_QFQ}], match_keys=["股票代码"])
        assert (day.inserted, day.failed_rows) == (1, 0)

        week = upsert_rows(
            db_engine, db, table, [{"股票代码": SYMBOL, "周线前复权": WEEK_QFQ}], match_keys=["股票代码"]
        )
        assert (week.inserted, week.updated, week.failed_rows) == (0, 1, 0)

        row = _read_rows(db_engine, table)[0]
        assert row["日线前复权"] == DAY_QFQ
        assert row["周线前复权"] == WEEK_QFQ

    def test_required_symbol_still_enforced(self, db: Session, db_engine):
        """partial 只豁免「未提供」的字段；完全不提供必填代码的行仍失败."""
        table = _make_table(db, db_engine)
        outcome = upsert_rows(db_engine, db, table, [{"日线前复权": DAY_QFQ}], match_keys=["股票代码"])
        assert outcome.inserted == 0
        assert outcome.failed_rows == 1
        assert _read_rows(db_engine, table) == []

    def test_invalid_json_in_provided_column_rejected(self, db: Session, db_engine):
        table = _make_table(db, db_engine)
        outcome = upsert_rows(
            db_engine, db, table, [{"股票代码": SYMBOL, "日线前复权": "not-a-json"}], match_keys=["股票代码"]
        )
        assert outcome.inserted == 0
        assert outcome.failed_rows == 1
        assert _read_rows(db_engine, table) == []

    def test_invalid_float_in_provided_column_rejected(self, db: Session, db_engine):
        table = _make_table(db, db_engine)
        outcome = upsert_rows(
            db_engine,
            db,
            table,
            [{"股票代码": SYMBOL, "日线前复权": DAY_QFQ, "最新价": "abc"}],
            match_keys=["股票代码"],
        )
        assert outcome.inserted == 0
        assert outcome.failed_rows == 1
        assert _read_rows(db_engine, table) == []


class TestLegacyGapFillingContrast:
    def test_default_importer_clears_absent_columns(self, db: Session, db_engine):
        """对照：partial=False（默认导入语义）会把未提供的列填 None，更新时清空兄弟列."""
        table = _make_table(db, db_engine)
        upsert_rows(db_engine, db, table, [{"股票代码": SYMBOL, "日线前复权": DAY_QFQ}], match_keys=["股票代码"])

        importer = Importer(db_engine, db, table)  # partial 默认 False
        analysis = importer.analyze("", rows=[{"股票代码": SYMBOL, "周线前复权": WEEK_QFQ}], match_keys=["股票代码"])
        importer.execute(analysis=analysis, match_keys=["股票代码"])

        row = _read_rows(db_engine, table)[0]
        assert row["周线前复权"] == WEEK_QFQ
        # 旧语义下日线列被 gap filling 填 None 后写入 → 清空；这正是 partial 要解决的问题
        assert row["日线前复权"] is None
