"""analytics M4：窗口函数接入模板 / 计算 / 推荐链路的集成测试."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from cndb.plugins.analytics.schemas import FormulaSpec, TemplateConfig
from cndb.plugins.analytics.services import compute as compute_service
from cndb.plugins.analytics.services import recommend as recommend_service
from cndb.plugins.analytics.services.templates import normalize_config
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl

FIELDS = ["symbol", "day", "close"]


class TestNormalizeConfig:
    def test_window_context_passthrough(self):
        config = TemplateConfig(
            formulas=[
                FormulaSpec(
                    key="ma3",
                    label="三日均线",
                    expr="round(ma([close], 3), 2)",
                    partition_by="symbol",
                    order_by="day",
                )
            ]
        )
        normalized = normalize_config(config, FIELDS)
        assert normalized["formulas"][0]["partition_by"] == "symbol"
        assert normalized["formulas"][0]["order_by"] == "day"
        assert "order_desc" not in normalized["formulas"][0]

    def test_order_desc_kept(self):
        config = TemplateConfig(
            formulas=[
                FormulaSpec(key="rk", expr="rank([close])", order_by="day", order_desc=True),
            ]
        )
        assert normalize_config(config, FIELDS)["formulas"][0]["order_desc"] is True

    def test_unknown_partition_field_rejected(self):
        config = TemplateConfig(
            formulas=[FormulaSpec(key="ma3", expr="ma([close], 3)", partition_by="nope")],
        )
        with pytest.raises(HTTPException) as exc:
            normalize_config(config, FIELDS)
        assert "分区字段不存在" in str(exc.value.detail)

    def test_unknown_order_field_rejected(self):
        config = TemplateConfig(
            formulas=[FormulaSpec(key="ma3", expr="ma([close], 3)", order_by="nope")],
        )
        with pytest.raises(HTTPException) as exc:
            normalize_config(config, FIELDS)
        assert "排序字段不存在" in str(exc.value.detail)

    def test_without_table_skips_field_check(self):
        config = TemplateConfig(
            formulas=[FormulaSpec(key="ma3", expr="ma([close], 3)", partition_by="whatever")],
        )
        assert normalize_config(config, None)["formulas"][0]["partition_by"] == "whatever"


def _make_table(session: Session, engine) -> DataTable:
    table = DataTable(workspace_id=1, name="行情日表")
    table.ensure_db_name()
    session.add(table)
    session.commit()
    session.refresh(table)
    for order, (name, field_type) in enumerate((("symbol", "text"), ("day", "date"), ("close", "float"))):
        field = DataField(table_id=table.id, name=name, field_type=field_type, order=order)
        field.ensure_db_name()
        session.add(field)
    session.commit()
    session.refresh(table)
    ddl.create_table(engine, table)
    return table


class TestComputeWithWindow:
    def test_compute_returns_partitioned_window_column(self, db_engine, db):
        from cndb.plugins.tables.services.core import records

        table = _make_table(db, db_engine)
        rows = [
            {"symbol": "A", "day": "2024-01-01", "close": 10},
            {"symbol": "A", "day": "2024-01-02", "close": 20},
            {"symbol": "A", "day": "2024-01-03", "close": 30},
            {"symbol": "B", "day": "2024-01-01", "close": 5},
            {"symbol": "B", "day": "2024-01-02", "close": 5},
        ]
        records.bulk_create(db_engine, table, rows, db=db)

        result = compute_service.compute(
            db,
            table,
            None,
            formulas=[
                {
                    "key": "ma2",
                    "label": "两日均线",
                    "expr": "round(ma([close], 2), 2)",
                    "partition_by": "symbol",
                    "order_by": "day",
                },
                {
                    "key": "mom",
                    "label": "环比",
                    "expr": "round(pct_change([close]) * 100, 2)",
                    "partition_by": "symbol",
                    "order_by": "day",
                },
            ],
            fields=["symbol", "day", "close"],
            limit=10,
        )
        by_symbol: dict[str, list[float | None]] = {}
        for row in result["rows"]:
            by_symbol.setdefault(str(row["symbol"]), []).append(row["ma2"])
        assert by_symbol["A"] == [None, 15.0, 25.0]
        assert by_symbol["B"] == [None, 5.0]

        moments = [row["mom"] for row in result["rows"] if row["symbol"] == "A"]
        assert moments == [None, 100.0, 50.0]

        stats = {col["key"]: col for col in result["columns"]}
        assert stats["ma2"]["kind"] == "formula"
        assert stats["ma2"]["count"] == 3

    def test_compute_without_window_context_still_works(self, db_engine, db):
        from cndb.plugins.tables.services.core import records

        table = _make_table(db, db_engine)
        records.bulk_create(db_engine, table, [{"symbol": "A", "day": "2024-01-01", "close": 10}], db=db)
        result = compute_service.compute(
            db,
            table,
            None,
            formulas=[{"key": "double", "expr": "[close] * 2"}],
            limit=10,
        )
        assert result["rows"][0]["double"] == 20.0


class TestRecommendPartition:
    def _fields(self) -> list[DataField]:
        return [
            DataField(name="symbol", field_type="text"),
            DataField(name="day", field_type="date"),
            DataField(name="close", field_type="float"),
        ]

    def test_symbol_marked_as_partition_dimension(self):
        rows = [
            {"symbol": "A", "day": "2024-01-01", "close": 10},
            {"symbol": "B", "day": "2024-01-01", "close": 20},
        ]
        profiles = recommend_service.profile_fields(self._fields(), rows)
        roles = {p["name"]: p["role"] for p in profiles}
        assert roles["symbol"] == "partition_dimension"
        assert roles["day"] == "time"
        assert roles["close"] == "metric"
        symbol = next(p for p in profiles if p["name"] == "symbol")
        assert "分区键" in str(symbol["reason"])

    def test_no_time_field_keeps_dimension(self):
        rows = [{"symbol": "A", "close": 10}]
        profiles = recommend_service.profile_fields(
            [DataField(name="symbol", field_type="text"), DataField(name="close", field_type="float")],
            rows,
        )
        assert {p["name"]: p["role"] for p in profiles}["symbol"] != "partition_dimension"

    def test_trend_example_uses_partition_and_ma(self):
        rows = [
            {"symbol": "A", "day": "2024-01-01", "close": 10},
            {"symbol": "A", "day": "2024-01-02", "close": 20},
        ]
        profiles = recommend_service.profile_fields(self._fields(), rows)
        examples = {e["id"]: e for e in recommend_service.build_examples(profiles)}

        trend = examples["trend"]
        assert trend["chart"]["series"] == "symbol"
        assert trend["formulas"][0]["partition_by"] == "symbol"
        assert trend["formulas"][0]["order_by"] == "day"
        assert "ma(" in trend["formulas"][0]["expr"]

        change = examples["period_change"]
        assert change["chart"]["y"] == "mom"
        assert {f["key"] for f in change["formulas"]} == {"mom", "ma3"}
        assert all(f["partition_by"] == "symbol" for f in change["formulas"])

    def test_trend_without_partition_has_no_series(self):
        rows = [
            {"product": "甲", "day": "2024-01-01", "close": 10},
            {"product": "乙", "day": "2024-01-02", "close": 20},
        ]
        profiles = recommend_service.profile_fields(
            [
                DataField(name="product", field_type="text"),
                DataField(name="day", field_type="date"),
                DataField(name="close", field_type="float"),
            ],
            rows,
        )
        examples = {e["id"]: e for e in recommend_service.build_examples(profiles)}
        assert examples["trend"]["chart"]["series"] is None
        assert examples["trend"]["formulas"] == []
        # 无分区列时环比仍按时间排序，只是不分区
        assert examples["period_change"]["formulas"][0]["order_by"] == "day"
        assert "partition_by" not in examples["period_change"]["formulas"][0]
