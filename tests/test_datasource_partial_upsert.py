"""datasource：部分列 upsert（``partial`` 语义）落表单测.

多 job 分列写同一行（日快照 / 周快照 / 季快照）时，
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

DEVICE = "dev-001"
DAY_SNAP_V2 = [{"ts": "2024-01-03", "reading": 1700.0}]
JSON_FIELDS = ("日快照", "周快照", "月快照", "季快照")
DAY_SNAP = [{"ts": "2024-01-02", "reading": 1680.0}]
WEEK_SNAP = [{"ts": "2024-01-05", "reading": 1690.0}]
MONTH_SNAP = [{"ts": "2024-01-31", "reading": 1720.0}]
QUARTER_SNAP = [{"ts": "2024-03-31", "reading": 1720.0}]


def _make_table(session: Session, engine: Any, *, required_json: str | None = None) -> DataTable:
    """建一张「设备读数」形态的表：编号必填 + 4 个 JSON 快照列 + 最新读数列."""
    table = DataTable(workspace_id=1, name="设备（部分列 upsert）")
    table.ensure_db_name()
    session.add(table)
    session.commit()
    session.refresh(table)

    specs: list[tuple[str, str, bool]] = [("设备编号", "text", True)]
    specs += [(name, "json", name == required_json) for name in JSON_FIELDS]
    specs += [("最新读数", "float", False)]
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
        """日快照 → 周快照 → 季快照：三列都保留，互不覆盖."""
        table = _make_table(db, db_engine)

        first = upsert_rows(db_engine, db, table, [{"设备编号": DEVICE, "日快照": DAY_SNAP}], match_keys=["设备编号"])
        assert (first.inserted, first.updated, first.failed_rows) == (1, 0, 0)

        second = upsert_rows(db_engine, db, table, [{"设备编号": DEVICE, "周快照": WEEK_SNAP}], match_keys=["设备编号"])
        assert (second.inserted, second.updated, second.failed_rows) == (0, 1, 0)

        third = upsert_rows(
            db_engine, db, table, [{"设备编号": DEVICE, "季快照": DAY_SNAP_V2}], match_keys=["设备编号"]
        )
        assert (third.inserted, third.updated, third.failed_rows) == (0, 1, 0)

        rows = _read_rows(db_engine, table)
        assert len(rows) == 1  # 幂等：同一代码只留一行
        assert rows[0]["日快照"] == DAY_SNAP
        assert rows[0]["周快照"] == WEEK_SNAP
        assert rows[0]["季快照"] == DAY_SNAP_V2
        assert rows[0]["月快照"] is None

    def test_second_write_only_touches_provided_columns(self, db: Session, db_engine):
        table = _make_table(db, db_engine)
        upsert_rows(
            db_engine,
            db,
            table,
            [
                {
                    "设备编号": DEVICE,
                    "日快照": DAY_SNAP,
                    "周快照": WEEK_SNAP,
                    "月快照": MONTH_SNAP,
                    "最新读数": 21.5,
                }
            ],
            match_keys=["设备编号"],
        )

        outcome = upsert_rows(
            db_engine, db, table, [{"设备编号": DEVICE, "日快照": DAY_SNAP_V2}], match_keys=["设备编号"]
        )
        assert (outcome.inserted, outcome.updated) == (0, 1)

        row = _read_rows(db_engine, table)[0]
        assert row["日快照"] == DAY_SNAP_V2  # 本次提供的列被覆盖
        assert row["周快照"] == WEEK_SNAP  # 未提供 → 保留
        assert row["月快照"] == MONTH_SNAP
        assert row["最新读数"] == 21.5
        assert row["季快照"] is None

    def test_new_row_keeps_absent_columns_null(self, db: Session, db_engine):
        table = _make_table(db, db_engine)
        outcome = upsert_rows(
            db_engine, db, table, [{"设备编号": DEVICE, "月快照": MONTH_SNAP}], match_keys=["设备编号"]
        )
        assert outcome.inserted == 1
        row = _read_rows(db_engine, table)[0]
        assert row["月快照"] == MONTH_SNAP
        assert row["日快照"] is None
        assert row["周快照"] is None
        assert row["最新读数"] is None


class TestRequiredAndValidation:
    def test_required_json_field_left_to_other_job(self, db: Session, db_engine):
        """必填的日快照列由日快照 job 负责；周快照 job 不提供该列也不应报必填错误."""
        table = _make_table(db, db_engine, required_json="日快照")

        day = upsert_rows(db_engine, db, table, [{"设备编号": DEVICE, "日快照": DAY_SNAP}], match_keys=["设备编号"])
        assert (day.inserted, day.failed_rows) == (1, 0)

        week = upsert_rows(db_engine, db, table, [{"设备编号": DEVICE, "周快照": WEEK_SNAP}], match_keys=["设备编号"])
        assert (week.inserted, week.updated, week.failed_rows) == (0, 1, 0)

        row = _read_rows(db_engine, table)[0]
        assert row["日快照"] == DAY_SNAP
        assert row["周快照"] == WEEK_SNAP

    def test_required_symbol_still_enforced(self, db: Session, db_engine):
        """partial 只豁免「未提供」的字段；完全不提供必填代码的行仍失败."""
        table = _make_table(db, db_engine)
        outcome = upsert_rows(db_engine, db, table, [{"日快照": DAY_SNAP}], match_keys=["设备编号"])
        assert outcome.inserted == 0
        assert outcome.failed_rows == 1
        assert _read_rows(db_engine, table) == []

    def test_invalid_json_in_provided_column_rejected(self, db: Session, db_engine):
        table = _make_table(db, db_engine)
        outcome = upsert_rows(
            db_engine, db, table, [{"设备编号": DEVICE, "日快照": "not-a-json"}], match_keys=["设备编号"]
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
            [{"设备编号": DEVICE, "日快照": DAY_SNAP, "最新读数": "abc"}],
            match_keys=["设备编号"],
        )
        assert outcome.inserted == 0
        assert outcome.failed_rows == 1
        assert _read_rows(db_engine, table) == []


class TestLegacyGapFillingContrast:
    def test_default_importer_clears_absent_columns(self, db: Session, db_engine):
        """对照：partial=False（默认导入语义）会把未提供的列填 None，更新时清空兄弟列."""
        table = _make_table(db, db_engine)
        upsert_rows(db_engine, db, table, [{"设备编号": DEVICE, "日快照": DAY_SNAP}], match_keys=["设备编号"])

        importer = Importer(db_engine, db, table)  # partial 默认 False
        analysis = importer.analyze("", rows=[{"设备编号": DEVICE, "周快照": WEEK_SNAP}], match_keys=["设备编号"])
        importer.execute(analysis=analysis, match_keys=["设备编号"])

        row = _read_rows(db_engine, table)[0]
        assert row["周快照"] == WEEK_SNAP
        # 旧语义下日快照列被 gap filling 填 None 后写入 → 清空；这正是 partial 要解决的问题
        assert row["日快照"] is None
