"""自选股 seed：CSV 聚合 / 周月派生 / 建表字段类型 / 幂等 / 示例配置一致性.

覆盖：元数据与 CSV 读取容错 / 日线涨跌额与涨跌幅补算 / 周月 resample 口径 /
行情快照字段 / 无 CSV 数据时的空序列 / 真实建表（json 列 + float decimals）/
重复调用幂等 / datasets 缺失降级 / 真实 examples 配置对表字段的引用合法性。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import MetaData, select
from sqlalchemy.orm import Session

from cndb.cli.seed.stock_quotes import (
    _STOCK_FIELDS,
    _build_rows,
    _load_daily_series,
    _load_meta,
    _market_from_code,
    _parse_date,
    _resample,
    _seed_stock_quotes,
    _to_float,
)
from cndb.plugins.tables.services.core import ddl

EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "examples" / "datasets" / "工作区-数据源示例"
EXAMPLES_ROOT = EXAMPLE_DIR.parent  # seed 接受的 datasets 根目录（内部再拼工作区文件夹）

# 2026-07-01 周三；07-01~07-03 同一 ISO 周，07-06/07 下一周
DAILY_CSV = """股票代码,股票名称,交易日,开盘价,最高价,最低价,收盘价,成交量,成交额
sh600519,贵州茅台,2026-07-01,10,12,9,11,100,1100
sh600519,贵州茅台,2026-07-02,11,13,10,12,200,2400
sh600519,贵州茅台,2026-07-03,12,14,11,13,300,3900
sh600519,贵州茅台,2026-07-06,13,15,12,14,400,5600
sh600519,贵州茅台,2026-07-07,14,16,13,15,500,7500
sz000001,平安银行,2026-07-01,100,110,90,105,10,1050
"""


def _make_datasets_dir(tmp_path: Path, *, meta: Any = None, csv_text: str | None = DAILY_CSV) -> Path:
    folder = tmp_path / "datasets" / "工作区-数据源示例"
    folder.mkdir(parents=True)
    if meta is not None:
        (folder / "自选股.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if csv_text is not None:
        (folder / "股市日线.csv").write_text(csv_text, encoding="utf-8-sig")
    return tmp_path / "datasets"


def _read_rows(engine: Any, dt: Any) -> list[dict[str, Any]]:
    metadata = MetaData()
    sa_table = ddl.build_sa_table(metadata, dt)
    fields = [f for f in dt.active_fields() if f.db_column_name]
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


class TestSmallHelpers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("1,234.5", 1234.5), (" 3.5 ", 3.5), (None, None), ("", None), ("abc", None)],
    )
    def test_to_float(self, raw, expected):
        assert _to_float(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2026-07-01", date(2026, 7, 1)),
            ("2026-07-01T09:30:00", date(2026, 7, 1)),
            (None, None),
            ("2026/07/01", None),
        ],
    )
    def test_parse_date(self, raw, expected):
        assert _parse_date(raw) == expected

    @pytest.mark.parametrize(
        ("code", "expected"),
        [("sh600519", "A股"), ("SZ000001", "A股"), ("hk00700", "港股"), ("usAAPL", "美股"), ("00700", "其他")],
    )
    def test_market_from_code(self, code, expected):
        assert _market_from_code(code) == expected


class TestLoaders:
    def test_load_meta_list_and_dict_wrappers(self, tmp_path: Path):
        items = [{"股票代码": "sh600519"}]
        path = tmp_path / "meta.json"
        path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        assert _load_meta(path) == items

        path.write_text(json.dumps({"symbols": items}), encoding="utf-8")
        assert _load_meta(path) == items
        path.write_text(json.dumps({"stocks": items}), encoding="utf-8")
        assert _load_meta(path) == items

    def test_load_meta_missing_or_invalid(self, tmp_path: Path):
        assert _load_meta(tmp_path / "missing.json") == []
        bad = tmp_path / "bad.json"
        bad.write_text("{not-json", encoding="utf-8")
        assert _load_meta(bad) == []
        bad.write_text(json.dumps({"other": 1}), encoding="utf-8")
        assert _load_meta(bad) == []

    def test_load_daily_series_sorted_and_enriched(self, tmp_path: Path):
        csv_path = tmp_path / "d.csv"
        csv_path.write_text(DAILY_CSV, encoding="utf-8-sig")
        grouped = _load_daily_series(csv_path)
        assert set(grouped) == {"sh600519", "sz000001"}
        points = grouped["sh600519"]
        assert [p["date"] for p in points] == [
            "2026-07-01",
            "2026-07-02",
            "2026-07-03",
            "2026-07-06",
            "2026-07-07",
        ]
        assert points[0]["pct_change"] is None  # 首日无前收
        assert points[1]["change"] == 1.0
        assert points[1]["pct_change"] == pytest.approx(9.0909, abs=1e-4)

    def test_load_daily_series_skips_bad_rows_and_missing_file(self, tmp_path: Path):
        csv_path = tmp_path / "d.csv"
        csv_path.write_text(
            "股票代码,交易日,收盘价\n,2026-07-01,1\nsh600519,,2\nsh600519,2026-07-01,3\n",
            encoding="utf-8",
        )
        grouped = _load_daily_series(csv_path)
        assert list(grouped) == ["sh600519"]
        assert len(grouped["sh600519"]) == 1
        assert _load_daily_series(tmp_path / "missing.csv") == {}


class TestResample:
    def _points(self) -> list[dict[str, Any]]:
        return [
            {
                "date": "2026-07-01",
                "open": 10.0,
                "close": 11.0,
                "high": 12.0,
                "low": 9.0,
                "volume": 100.0,
                "amount": 1100.0,
            },
            {
                "date": "2026-07-02",
                "open": 11.0,
                "close": 12.0,
                "high": 13.0,
                "low": 10.0,
                "volume": 200.0,
                "amount": 2400.0,
            },
            {
                "date": "2026-07-03",
                "open": 12.0,
                "close": 13.0,
                "high": 14.0,
                "low": 11.0,
                "volume": 300.0,
                "amount": 3900.0,
            },
            {
                "date": "2026-07-06",
                "open": 13.0,
                "close": 14.0,
                "high": 15.0,
                "low": 12.0,
                "volume": 400.0,
                "amount": 5600.0,
            },
            {
                "date": "2026-07-07",
                "open": 14.0,
                "close": 15.0,
                "high": 16.0,
                "low": 13.0,
                "volume": 500.0,
                "amount": 7500.0,
            },
        ]

    def test_week_aggregation(self):
        weeks = _resample(self._points(), "week")
        assert len(weeks) == 2
        first, second = weeks
        assert first["date"] == "2026-07-03"  # 组内最后一天
        assert (first["open"], first["close"], first["high"], first["low"]) == (10.0, 13.0, 14.0, 9.0)
        assert (first["volume"], first["amount"]) == (600.0, 7400.0)
        assert first["change"] is None and first["pct_change"] is None  # 首周无前收
        assert second["open"] == 13.0 and second["close"] == 15.0
        assert second["change"] == 2.0
        assert second["pct_change"] == pytest.approx(15.3846, abs=1e-4)

    def test_month_aggregation(self):
        months = _resample(self._points(), "month")
        assert len(months) == 1
        month = months[0]
        assert month["date"] == "2026-07-07"
        assert (month["open"], month["close"], month["high"], month["low"]) == (10.0, 15.0, 16.0, 9.0)
        assert (month["volume"], month["amount"]) == (1500.0, 20500.0)

    def test_empty_and_invalid_dates(self):
        assert _resample([], "week") == []
        assert _resample([{"date": "bad", "open": 1}], "month") == []


class TestBuildRows:
    META = [
        {"股票代码": "sh600519", "股票名称": "贵州茅台", "市场": "A股", "行业": "食品饮料", "是否自选": True},
    ]

    def test_row_shape_and_latest_quote(self):
        series = {  # 简化：直接用两日序列
            "sh600519": [
                {
                    "date": "2026-07-01",
                    "open": 10.0,
                    "close": 11.0,
                    "high": 12.0,
                    "low": 9.0,
                    "volume": 100.0,
                    "amount": 1100.0,
                    "pct_change": None,
                    "change": None,
                },
                {
                    "date": "2026-07-02",
                    "open": 11.0,
                    "close": 12.5,
                    "high": 13.0,
                    "low": 10.0,
                    "volume": 200.0,
                    "amount": 2400.0,
                    "pct_change": 13.6364,
                    "change": 1.5,
                },
            ]
        }
        rows = _build_rows(self.META, series)
        assert len(rows) == 1
        row = rows[0]
        assert row["股票代码"] == "sh600519"
        assert row["股票名称"] == "贵州茅台"
        assert row["市场"] == "A股"
        assert row["行业"] == "食品饮料"
        assert row["是否自选"] is True
        assert row["最新价"] == 12.5
        assert row["涨跌幅"] == 13.6364
        assert row["最新交易日"] == date(2026, 7, 2)
        assert (row["成交量"], row["成交额"]) == (200.0, 2400.0)
        assert len(row["日线前复权"]) == 2
        assert row["日线后复权"] is None and row["日线不复权"] is None
        assert len(row["周线前复权"]) == 1
        assert len(row["月线前复权"]) == 1

    def test_csv_only_code_gets_placeholder_name(self):
        series = {"sz000001": [{"date": "2026-07-01", "open": 1.0, "close": 1.0, "high": 1.0, "low": 1.0}]}
        rows = _build_rows([], series)
        assert len(rows) == 1
        assert rows[0]["股票代码"] == "sz000001"
        assert rows[0]["股票名称"] == "sz000001"
        assert rows[0]["市场"] == "A股"
        assert rows[0]["最新交易日"] == date(2026, 7, 1)

    def test_meta_without_series_has_empty_kline(self):
        rows = _build_rows(self.META, {})
        row = rows[0]
        assert row["最新价"] is None
        assert row["最新交易日"] is None
        assert row["日线前复权"] is None
        assert row["周线前复权"] is None and row["月线前复权"] is None

    def test_duplicate_meta_codes_are_deduped(self):
        meta = [*self.META, dict(self.META[0])]
        rows = _build_rows(meta, {})
        assert len(rows) == 1


class TestSeedTable:
    def _seed(self, db: Session, engine: Any, datasets_dir: Path):
        from cndb.plugins.accounts.models import User
        from cndb.plugins.workspaces.models import Workspace

        user = User(username="kline_seed", email="kline_seed@example.com", nickname="K线种子测试")
        user.set_password("pass1234")
        db.add(user)
        db.commit()
        db.refresh(user)

        ws = Workspace(name="数据源示例", description="K线 seed 测试", created_by_id=user.id)
        db.add(ws)
        db.commit()
        db.refresh(ws)
        return _seed_stock_quotes(db, engine, ws, user.id, datasets_dir)

    def test_creates_table_with_typed_fields(self, db: Session, db_engine, tmp_path: Path):
        datasets_dir = _make_datasets_dir(
            tmp_path,
            meta=[
                {"股票代码": "sh600519", "股票名称": "贵州茅台", "市场": "A股", "行业": "食品饮料", "是否自选": True},
                {"股票代码": "hk00700", "股票名称": "腾讯控股", "市场": "港股", "行业": "互联网", "是否自选": True},
            ],
        )
        created, dt = self._seed(db, db_engine, datasets_dir)
        assert created == 1
        assert dt is not None and dt.name == "自选股"

        fields = {f.name: f for f in dt.active_fields()}
        for name in ("日线前复权", "日线后复权", "日线不复权", "周线前复权", "月线前复权"):
            assert fields[name].field_type == "json"
        assert fields["最新价"].config.get("decimals") == 2
        assert fields["涨跌幅"].config.get("decimals") == 2
        assert fields["最新交易日"].field_type == "date"
        assert fields["更新时间"].field_type == "datetime"
        assert fields["市场"].field_type == "select"
        assert fields["股票代码"].required and fields["股票代码"].is_unique

        rows = _read_rows(db_engine, dt)
        # 2 只来自元数据 + CSV 中多出的 sz000001 自动补行
        assert len(rows) == 3
        by_code = {r["股票代码"]: r for r in rows}
        maotai = by_code["sh600519"]
        assert maotai["最新价"] == 15.0
        assert maotai["涨跌幅"] == pytest.approx(7.14)  # decimals=2
        assert maotai["最新交易日"] == date(2026, 7, 7)
        assert len(maotai["日线前复权"]) == 5
        assert len(maotai["周线前复权"]) == 2
        assert len(maotai["月线前复权"]) == 1
        assert maotai["是否自选"] is True
        # 只有 CSV 的代码也建行（无名称时用代码占位）
        pingan = by_code["sz000001"]
        assert pingan["股票名称"] == "sz000001"

    def test_creates_default_view(self, db: Session, db_engine, tmp_path: Path):
        from cndb.plugins.tables.models import DataView

        datasets_dir = _make_datasets_dir(tmp_path, meta=[{"股票代码": "sh600519", "股票名称": "贵州茅台"}])
        created, dt = self._seed(db, db_engine, datasets_dir)
        assert created == 1
        views = db.query(DataView).filter(DataView.table_id == dt.id).all()
        assert len(views) == 1
        assert views[0].is_default is True

    def test_selected_field_defaults_to_false_for_discovered_rows(self, db: Session, db_engine, tmp_path: Path):
        """全市场发现（eastmoney_symbols）只写代码/名称/市场时，新行的「是否自选」由默认值落 false."""
        from cndb.plugins.tables.services.core.records import bulk_create

        datasets_dir = _make_datasets_dir(
            tmp_path, meta=[{"股票代码": "sh600519", "股票名称": "贵州茅台"}], csv_text=None
        )
        created, dt = self._seed(db, db_engine, datasets_dir)
        assert created == 1
        fields = {f.name: f for f in dt.active_fields()}
        assert fields["是否自选"].default_value is False

        bulk_create(db_engine, dt, [{"股票代码": "sz300999", "股票名称": "新发现标的"}], db=db)
        rows = {r["股票代码"]: r for r in _read_rows(db_engine, dt)}
        # 新行落 false；已有自选行（seed 显式传 true）保持不变
        assert rows["sz300999"]["是否自选"] is False
        assert rows["sh600519"]["是否自选"] is True

    def test_idempotent_second_call(self, db: Session, db_engine, tmp_path: Path):
        datasets_dir = _make_datasets_dir(
            tmp_path, meta=[{"股票代码": "sh600519", "股票名称": "贵州茅台"}], csv_text=None
        )
        created, dt = self._seed(db, db_engine, datasets_dir)
        assert created == 1
        again, same = _seed_stock_quotes(db, db_engine, dt_ws(db, dt), None, datasets_dir)
        assert again == 0
        assert same is not None and same.id == dt.id
        assert len(_read_rows(db_engine, dt)) == 1

    def test_missing_datasets_dir_returns_zero(self, db: Session, db_engine):
        from cndb.plugins.workspaces.models import Workspace

        ws = Workspace(name="空工作区")
        db.add(ws)
        db.commit()
        db.refresh(ws)
        assert _seed_stock_quotes(db, db_engine, ws, None, None) == (0, None)
        assert _seed_stock_quotes(db, db_engine, ws, None, Path("不存在的目录")) == (0, None)


def dt_ws(db: Session, dt: Any) -> Any:
    from cndb.plugins.workspaces.models import Workspace

    ws = db.get(Workspace, dt.workspace_id)
    assert ws is not None
    return ws


class TestRealExamples:
    def test_symbol_meta_matches_daily_sample(self):
        meta = json.loads((EXAMPLE_DIR / "自选股.json").read_text(encoding="utf-8-sig"))
        assert len(meta) == 10
        codes = {item["股票代码"] for item in meta}
        assert codes == {
            "sh600519",
            "sz000858",
            "sz000001",
            "sh600036",
            "sh601318",
            "sz300750",
            "sz002594",
            "sh601899",
            "sh600900",
            "sz000651",
        }
        # 三源示例只覆盖 A 股，自选股表的标的集合与日线表一致
        assert {item["市场"] for item in meta} == {"A股"}
        # 留一只非自选（格力电器）验证 kline 视图的「是否自选」筛选
        assert sum(1 for item in meta if item.get("是否自选") is True) == 9

    def test_views_json_kline_options_reference_existing_fields(self):
        views = json.loads((EXAMPLE_DIR / "views.json").read_text(encoding="utf-8-sig"))
        kline_views = [v for v in views["自选股"] if v.get("view_type") == "kline"]
        assert len(kline_views) == 1
        view = kline_views[0]
        field_names = {name for name, _ft, _cfg, _req, _uniq in _STOCK_FIELDS}
        options = view["view_options"]
        for key in (
            "symbol_field",
            "name_field",
            "price_field",
            "change_pct_field",
            "volume_field",
            "amount_field",
            "date_field",
            "day_qfq_field",
            "day_hfq_field",
            "day_none_field",
            "week_qfq_field",
            "month_qfq_field",
        ):
            assert options[key] in field_names, f"{key} 引用了不存在的字段 {options[key]}"
        assert [f["field_name"] for f in view["filters"]] == ["是否自选"]
        assert view["is_default"] is True

    def test_real_kline_view_created_as_sole_default(self, db: Session, db_engine):
        """真实 views.json：自选股 kline 视图通过校验并取代自动「全部」视图成为默认."""
        from cndb.cli.seed import views as seed_views
        from cndb.plugins.accounts.models import User
        from cndb.plugins.tables.models import DataView
        from cndb.plugins.workspaces.models import Workspace

        user = User(username="kline_view_seed", email="kline_view_seed@example.com", nickname="K线视图种子")
        user.set_password("pass1234")
        db.add(user)
        db.commit()
        db.refresh(user)

        ws = Workspace(name="数据源示例", created_by_id=user.id)
        db.add(ws)
        db.commit()
        db.refresh(ws)

        created, dt = _seed_stock_quotes(db, db_engine, ws, user.id, EXAMPLES_ROOT)
        assert created == 1
        assert seed_views._seed_views(db, user, {"数据源示例": {"自选股": dt}}, EXAMPLES_ROOT) == 1

        views = db.query(DataView).filter(DataView.table_id == dt.id).all()
        kline_views = [v for v in views if v.view_type == "kline"]
        assert len(kline_views) == 1
        assert kline_views[0].view_options["symbol_field"] == "股票代码"
        # 每张表只保留一个默认视图
        assert [v.name for v in views if v.is_default] == [kline_views[0].name]

        rows = _read_rows(db_engine, dt)
        assert len(rows) == 10
        with_series = [r for r in rows if r["日线前复权"]]
        assert with_series  # 示例 CSV 至少覆盖 A 股标的
        assert all(r["周线前复权"] and r["月线前复权"] for r in with_series)
        assert all(r["最新交易日"] is not None for r in with_series)
