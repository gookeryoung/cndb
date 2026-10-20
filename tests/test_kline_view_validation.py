"""视图后端校验：``kline`` 字段引用 + 语义校验（router 与 seed 两处同口径）.

覆盖：全字段配置通过 / 只配最少字段 / 周月默认周期可由日线派生 /
缺 symbol_field / 无序列字段 / 默认复权缺对应列 / 未知字段引用 /
filters 引用校验 / 非 kline 视图不做语义限制 / 两处实现判定一致。
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from cndb.cli.seed.views import _validate_view_fields as seed_validate
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.routers.views import _validate_view_fields as router_validate
from cndb.plugins.tables.schemas.models import ViewCreate

FIELDS = (
    "股票代码",
    "股票名称",
    "市场",
    "是否自选",
    "最新价",
    "涨跌幅",
    "成交量",
    "成交额",
    "最新交易日",
    "日线前复权",
    "日线后复权",
    "日线不复权",
    "周线前复权",
    "月线前复权",
)

FULL_OPTIONS: dict[str, str] = {
    "symbol_field": "股票代码",
    "name_field": "股票名称",
    "price_field": "最新价",
    "change_pct_field": "涨跌幅",
    "volume_field": "成交量",
    "amount_field": "成交额",
    "date_field": "最新交易日",
    "day_qfq_field": "日线前复权",
    "day_hfq_field": "日线后复权",
    "day_none_field": "日线不复权",
    "week_qfq_field": "周线前复权",
    "month_qfq_field": "月线前复权",
    "default_period": "day",
    "default_adjust": "qfq",
}

# (用例名, view_options, 期望通过)
CASES: list[tuple[str, dict[str, object], bool]] = [
    ("full", dict(FULL_OPTIONS), True),
    ("minimal_day_qfq", {"symbol_field": "股票代码", "day_qfq_field": "日线前复权"}, True),
    (
        "week_default_derived_from_day",
        {"symbol_field": "股票代码", "day_qfq_field": "日线前复权", "default_period": "week"},
        True,
    ),
    (
        "month_default_derived_from_day",
        {"symbol_field": "股票代码", "day_qfq_field": "日线前复权", "default_period": "month"},
        True,
    ),
    (
        "week_default_without_any_qfq",
        {
            "symbol_field": "股票代码",
            "day_hfq_field": "日线后复权",
            "default_adjust": "hfq",
            "default_period": "week",
        },
        False,
    ),
    ("missing_symbol", {"day_qfq_field": "日线前复权"}, False),
    ("no_series_field", {"symbol_field": "股票代码"}, False),
    (
        "hfq_default_without_hfq_column",
        {"symbol_field": "股票代码", "day_qfq_field": "日线前复权", "default_adjust": "hfq"},
        False,
    ),
    (
        "none_default_without_none_column",
        {"symbol_field": "股票代码", "day_qfq_field": "日线前复权", "default_adjust": "none"},
        False,
    ),
    (
        "hfq_default_with_hfq_column",
        {"symbol_field": "股票代码", "day_hfq_field": "日线后复权", "default_adjust": "hfq"},
        True,
    ),
    ("unknown_series_field", {"symbol_field": "股票代码", "day_qfq_field": "不存在"}, False),
    (
        "unknown_quote_field",
        {"symbol_field": "股票代码", "day_qfq_field": "日线前复权", "price_field": "不存在"},
        False,
    ),
]


@pytest.fixture
def table(db: Session) -> DataTable:
    dt = DataTable(workspace_id=1, name="自选股")
    dt.ensure_db_name()
    db.add(dt)
    db.commit()
    db.refresh(dt)
    for order, name in enumerate(FIELDS):
        field = DataField(table_id=dt.id, name=name, field_type="text", order=order)
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(dt)
    return dt


def _router_ok(db: Session, table: DataTable, options: dict[str, object], **kwargs: object) -> tuple[bool, str | None]:
    payload: dict[str, object] = {"name": "K线", "view_type": "kline", "view_options": options}
    payload.update(kwargs)
    vc = ViewCreate(**payload)  # type: ignore[arg-type]
    return router_validate(vc, table.id, db)


def _seed_ok(options: dict[str, object], **kwargs: object) -> bool:
    vc: dict[str, object] = {"name": "K线", "view_type": "kline", "view_options": options}
    vc.update(kwargs)
    return seed_validate(vc, set(FIELDS), "工作区-数据源示例", "自选股")


class TestRouterValidation:
    @pytest.mark.parametrize(("case", "options", "expected"), CASES, ids=[c[0] for c in CASES])
    def test_cases(self, db: Session, table: DataTable, case: str, options: dict[str, object], expected: bool):
        ok, _err = _router_ok(db, table, options)
        assert ok is expected

    @pytest.mark.parametrize(("case", "options", "expected"), CASES, ids=[c[0] for c in CASES])
    def test_seed_cases(self, case: str, options: dict[str, object], expected: bool):
        assert _seed_ok(options) is expected

    def test_router_and_seed_agree(self, db: Session, table: DataTable):
        for case, options, _expected in CASES:
            router_result, _err = _router_ok(db, table, options)
            assert router_result is _seed_ok(options), f"两处校验口径不一致: {case}"

    def test_error_message_points_to_missing_option(self, db: Session, table: DataTable):
        ok, err = _router_ok(db, table, {"day_qfq_field": "日线前复权"})
        assert ok is False
        assert err is not None and "symbol_field" in err

        ok, err = _router_ok(db, table, {"symbol_field": "股票代码", "day_qfq_field": "不存在"})
        assert ok is False
        assert err is not None and "day_qfq_field" in err

    def test_filters_and_sortings_references_checked(self, db: Session, table: DataTable):
        ok, _err = _router_ok(
            db,
            table,
            dict(FULL_OPTIONS),
            filters=[{"field_name": "是否自选", "operator": "eq", "value": "true"}],
            sortings=[{"field_name": "涨跌幅", "direction": "desc"}],
        )
        assert ok is True

        ok, err = _router_ok(db, table, dict(FULL_OPTIONS), filters=[{"field_name": "不存在"}])
        assert ok is False
        assert err is not None and "filter" in err

    def test_non_kline_view_has_no_semantic_requirement(self, db: Session, table: DataTable):
        # 不新增 view_type 枚举限制：未知视图类型不触发 kline 语义校验
        payload = ViewCreate(name="自定义", view_type="custom-kline", view_options={})
        ok, err = router_validate(payload, table.id, db)
        assert ok is True and err is None

    def test_kline_option_fields_checked_even_for_other_view_types(self, db: Session, table: DataTable):
        # 字段引用校验对所有视图类型生效（只跳过语义校验）
        payload = ViewCreate(name="grid", view_type="grid", view_options={"price_field": "不存在"})
        ok, err = router_validate(payload, table.id, db)
        assert ok is False
        assert err is not None and "price_field" in err


class TestSeedValidation:
    def test_filters_and_sortings_references_checked(self):
        assert _seed_ok(
            dict(FULL_OPTIONS),
            filters=[{"field_name": "是否自选", "operator": "eq", "value": "true"}],
            sortings=[{"field_name": "涨跌幅", "direction": "desc"}],
        )
        assert _seed_ok(dict(FULL_OPTIONS), filters=[{"field_name": "不存在"}]) is False

    def test_non_kline_view_has_no_semantic_requirement(self):
        assert seed_validate({"name": "自定义", "view_type": "custom", "view_options": {}}, set(FIELDS), "ws", "t")

    def test_unknown_field_in_any_view_type_rejected(self):
        vc = {"name": "grid", "view_type": "grid", "view_options": {"amount_field": "不存在"}}
        assert seed_validate(vc, set(FIELDS), "ws", "t") is False
