"""analytics 取数范围（filters）与扫描上限配置（ADR 0006 M5 遗留项 ①）."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.plugins.analytics.services import compute as compute_service
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl, records


def _make_table(session: Session, engine) -> DataTable:
    table = DataTable(workspace_id=1, name="区间行情")
    table.ensure_db_name()
    session.add(table)
    session.commit()
    session.refresh(table)
    for order, (name, field_type) in enumerate(
        (("symbol", "text"), ("day", "date"), ("close", "float")),
    ):
        field = DataField(table_id=table.id, name=name, field_type=field_type, order=order)
        field.ensure_db_name()
        session.add(field)
    session.commit()
    session.refresh(table)
    ddl.create_table(engine, table)
    return table


ROWS = [
    {"symbol": "A", "day": "2024-01-01", "close": 10},
    {"symbol": "A", "day": "2024-01-02", "close": 20},
    {"symbol": "A", "day": "2024-01-03", "close": 30},
    {"symbol": "B", "day": "2024-01-02", "close": 5},
    {"symbol": "B", "day": "2024-01-03", "close": 7},
]


@pytest.fixture
def table(db_engine, db):
    tbl = _make_table(db, db_engine)
    records.bulk_create(db_engine, tbl, ROWS, db=db)
    return tbl


def _compute(db: Session, table: DataTable, **kwargs):
    return compute_service.compute(db, table, None, formulas=[], fields=["symbol", "day", "close"], **kwargs)


class TestScanLimit:
    def test_default_matches_constant(self):
        assert compute_service.scan_limit() == compute_service.MAX_SCAN_ROWS

    def test_reads_setting(self, monkeypatch):
        monkeypatch.setattr(settings, "ANALYTICS_MAX_SCAN_ROWS", 123)
        assert compute_service.scan_limit() == 123

    def test_non_positive_falls_back(self, monkeypatch):
        monkeypatch.setattr(settings, "ANALYTICS_MAX_SCAN_ROWS", 0)
        assert compute_service.scan_limit() == compute_service.MAX_SCAN_ROWS
        monkeypatch.setattr(settings, "ANALYTICS_MAX_SCAN_ROWS", -5)
        assert compute_service.scan_limit() == compute_service.MAX_SCAN_ROWS

    def test_truncates_at_limit(self, db, table, monkeypatch):
        monkeypatch.setattr(settings, "ANALYTICS_MAX_SCAN_ROWS", 2)
        result = _compute(db, table, limit=10)
        assert len(result["rows"]) == 2
        assert result["truncated"] is True
        assert result["total"] == 5


class TestFilters:
    def test_time_range_scopes_rows_and_stats(self, db, table):
        """时间区间过滤：行、总量、统计口径全部只看区间内的数据."""
        result = _compute(
            db,
            table,
            limit=10,
            filters=[{"field_name": "day", "op": ">=", "value": "2024-01-02"}],
        )
        assert result["total"] == 4
        assert result["truncated"] is False
        # date 字段读回来是 datetime.date，比较前统一成字符串
        assert {str(row["day"]) for row in result["rows"]} == {"2024-01-02", "2024-01-03"}
        close = next(col for col in result["columns"] if col["key"] == "close")
        assert close["count"] == 4
        assert close["max"] == 30

    def test_partition_equality(self, db, table):
        result = _compute(db, table, limit=10, filters=[{"field_name": "symbol", "op": "=", "value": "B"}])
        assert result["total"] == 2
        assert {row["symbol"] for row in result["rows"]} == {"B"}

    def test_combined_and(self, db, table):
        result = _compute(
            db,
            table,
            limit=10,
            filters=[
                {"field_name": "symbol", "op": "=", "value": "A"},
                {"field_name": "day", "op": ">=", "value": "2024-01-02"},
            ],
        )
        assert result["total"] == 2
        assert [row["close"] for row in result["rows"]] == [20, 30]

    def test_or_logic(self, db, table):
        result = _compute(
            db,
            table,
            limit=10,
            filters=[
                {"field_name": "symbol", "op": "=", "value": "A"},
                {"field_name": "close", "op": ">=", "value": 7},
            ],
            filter_logic="OR",
        )
        # A 三行 + B 的 7（>=7）→ 4 行
        assert result["total"] == 4

    def test_summary_uses_filtered_rows(self, db, table):
        from cndb.plugins.analytics.schemas import SummarySpec

        result = _compute(
            db,
            table,
            limit=10,
            filters=[{"field_name": "symbol", "op": "=", "value": "A"}],
            summary=SummarySpec(group_by="symbol", metrics=[{"field": "close", "agg": "sum"}]),
        )
        assert result["summary"]["rows"] == [{"group": "A", "sum(close)": 60.0}]

    def test_filter_on_window_formula(self, db, table):
        """区间过滤后再按分区算窗口：第一行没有前值（不会把区间外的行算进来）."""
        result = compute_service.compute(
            db,
            table,
            None,
            formulas=[
                {
                    "key": "prev_close",
                    "label": "前收",
                    "expr": "prev([close])",
                    "partition_by": "symbol",
                    "order_by": "day",
                }
            ],
            fields=["symbol", "day", "close"],
            limit=10,
            filters=[{"field_name": "day", "op": ">=", "value": "2024-01-02"}],
        )
        by_symbol: dict[str, list[float | None]] = {}
        for row in result["rows"]:
            by_symbol.setdefault(str(row["symbol"]), []).append(row["prev_close"])
        assert by_symbol["A"] == [None, 20.0]
        assert by_symbol["B"] == [None, 5.0]

    def test_empty_filter_list_is_noop(self, db, table):
        result = _compute(db, table, limit=10, filters=[])
        assert result["total"] == 5

    def test_unknown_field_filter_raises(self, db, table):
        """未知字段必须报错：列表接口会静默跳过，那等于退化回全表扫描."""
        from cndb.plugins.analytics.services.formula import FormulaError

        with pytest.raises(FormulaError) as excinfo:
            _compute(db, table, limit=10, filters=[{"field_name": "nope", "op": "=", "value": 1}])
        assert "过滤字段不存在" in str(excinfo.value)

    def test_filter_without_field_name_raises(self, db, table):
        from cndb.plugins.analytics.services.formula import FormulaError

        with pytest.raises(FormulaError):
            _compute(db, table, limit=10, filters=[{"op": "=", "value": 1}])
