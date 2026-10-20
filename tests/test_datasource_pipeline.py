"""datasource M1：http_json 请求展开 / 解析 / 抓取管线 / 幂等落表单测."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import MetaData, func, select
from sqlalchemy.orm import Session

from cndb.plugins.datasource.providers.base import (
    FieldTransform,
    PagingSpec,
    ProviderError,
    RequestSpec,
    SyncJobSpec,
    TimeWindowSpec,
)
from cndb.plugins.datasource.providers.http_json import HttpJsonProvider, iter_pages, iter_windows
from cndb.plugins.datasource.providers.registry import (
    PROVIDERS,
    get_provider,
    list_providers,
    register_builtins,
    register_provider,
)
from cndb.plugins.datasource.services.pipeline import run_pipeline
from cndb.plugins.datasource.services.write import upsert_rows
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.importing.api_fetch import FetchConfig

PROVIDER = HttpJsonProvider()


def _job(**overrides: object) -> SyncJobSpec:
    """构造一个最小可用 job，测试按需覆盖字段."""
    base: dict[str, object] = {
        "request": RequestSpec(url_template="https://api.example.com/v1/items"),
    }
    base.update(overrides)
    return SyncJobSpec(**base)  # type: ignore[arg-type]


# ── 请求展开 ──────────────────────────────────────


class TestBuildRequests:
    def test_single_request_without_entrant_or_window(self):
        plans = PROVIDER.build_requests(_job())
        assert len(plans) == 1
        assert plans[0].config.url == "https://api.example.com/v1/items"
        assert plans[0].label == "single"
        assert plans[0].page is None

    def test_entrant_and_window_and_paging(self):
        spec = RequestSpec(
            url_template="https://api.example.com/w?city={city}&from={start}&to={end}&p={page}",
            params_template={"city": "{city}", "size": "{page_size}"},
            time_window=TimeWindowSpec(
                mode="range",
                start="2024-01-01",
                end="2024-01-03",
                chunk_days=1,
                start_param="from",
                end_param="to",
            ),
            paging=PagingSpec(mode="page", start_page=1, max_pages=2, page_size=10),
        )
        job = _job(request=spec, entrant_param="city", entrant_values=("北京", "上海"))
        plans = PROVIDER.build_requests(job)
        # 2 个标的 × 3 天窗口 × 2 页
        assert len(plans) == 12
        first = plans[0]
        assert first.config.url == "https://api.example.com/w?city=北京&from=2024-01-01&to=2024-01-01&p=1"
        assert first.config.params == {"city": "北京", "size": "10"}
        assert first.label == "city=北京 2024-01-01~2024-01-01 page=1"
        assert (first.entrant, first.page, first.window_start) == ("北京", 1, "2024-01-01")
        assert plans[-1].config.url.endswith("city=上海&from=2024-01-03&to=2024-01-03&p=2")

    def test_offset_mode_injects_offset_not_page_number(self):
        spec = RequestSpec(
            url_template="https://api.example.com/list?offset={offset}&limit={limit}",
            paging=PagingSpec(mode="offset", page_param="offset", size_param="limit", page_size=50, max_pages=2),
        )
        plans = PROVIDER.build_requests(_job(request=spec))
        assert plans[0].config.url.endswith("offset=0&limit=50")
        assert plans[1].config.url.endswith("offset=50&limit=50")

    def test_method_headers_and_body_templates_rendered(self):
        spec = RequestSpec(
            url_template="https://api.example.com/q?k={k}",
            method="POST",
            headers_template={"X-Key": "{k}", "Accept": "application/json"},
            body_template={"query": "{k}", "n": 1},
        )
        plans = PROVIDER.build_requests(_job(request=spec, entrant_param="k", entrant_values=("abc",)))
        config = plans[0].config
        assert config.method == "POST"
        assert config.headers["X-Key"] == "abc"
        assert config.body == {"query": "abc", "n": 1}

    def test_missing_placeholder_surfaces_at_build_time(self):
        spec = RequestSpec(url_template="https://api.example.com/q?k={k}")
        with pytest.raises(ProviderError, match="模板变量缺失"):
            PROVIDER.build_requests(_job(request=spec))


class TestWindowAndPageExpansion:
    def test_no_window_is_single_none_pair(self):
        assert iter_windows(TimeWindowSpec()) == [(None, None)]

    def test_window_without_chunk_is_single_pair(self):
        spec = TimeWindowSpec(mode="range", start="2024-01-01", end="2024-01-31")
        assert iter_windows(spec) == [("2024-01-01", "2024-01-31")]

    def test_chunk_days_splits_inclusive(self):
        spec = TimeWindowSpec(mode="range", start="2024-01-01", end="2024-01-05", chunk_days=2)
        assert iter_windows(spec) == [
            ("2024-01-01", "2024-01-02"),
            ("2024-01-03", "2024-01-04"),
            ("2024-01-05", "2024-01-05"),
        ]

    def test_custom_date_format(self):
        spec = TimeWindowSpec(mode="range", start="2024-01-01", end="2024-01-01", date_format="%Y%m%d")
        assert iter_windows(spec) == [("20240101", "20240101")]

    def test_reversed_window_raises(self):
        spec = TimeWindowSpec(mode="range", start="2024-02-01", end="2024-01-01")
        with pytest.raises(ProviderError, match="早于"):
            iter_windows(spec)

    def test_bad_date_raises(self):
        spec = TimeWindowSpec(mode="range", start="2024/01/01", end="2024-02-01")
        with pytest.raises(ProviderError, match="ISO 日期"):
            iter_windows(spec)

    def test_pages_none(self):
        assert iter_pages(PagingSpec()) == [None]

    def test_pages_range(self):
        assert iter_pages(PagingSpec(mode="page", start_page=2, max_pages=3)) == [2, 3, 4]


class TestParse:
    def test_plain_array(self):
        rows = PROVIDER.parse('[{"a": 1}, {"a": 2}]', _job())
        assert rows == [{"a": 1}, {"a": 2}]

    def test_candidate_key(self):
        rows = PROVIDER.parse('{"data": [{"a": 1}]}', _job())
        assert rows == [{"a": 1}]

    def test_explicit_data_path(self):
        spec = RequestSpec(url_template="https://api.example.com", data_path="result.items")
        payload = json.dumps({"result": {"items": [{"a": 7}]}})
        assert PROVIDER.parse(payload, _job(request=spec)) == [{"a": 7}]

    def test_empty_array_is_not_an_error(self):
        assert PROVIDER.parse('{"data": []}', _job()) == []

    def test_invalid_json_raises(self):
        with pytest.raises(ProviderError, match="不是合法 JSON"):
            PROVIDER.parse("<html>oops</html>", _job())

    def test_single_object_wrapped_as_row(self):
        assert PROVIDER.parse('{"a": 1}', _job()) == [{"a": 1}]


# ── 管线 ─────────────────────────────────────────


def _fetcher(pages: dict[str, list[dict[str, object]]]) -> object:
    """按 URL 返回预置行的假抓取函数（记录调用顺序）."""

    def fetch(config: FetchConfig) -> list[dict[str, object]]:
        fetch.calls.append(config.url)  # type: ignore[attr-defined]
        if config.url not in pages:
            raise ValueError("HTTP 500: 模拟源故障")
        return pages[config.url]

    fetch.calls = []  # type: ignore[attr-defined]
    return fetch


class TestRunPipeline:
    def test_single_request_normalized(self):
        spec = RequestSpec(url_template="https://api.example.com/w")
        job = _job(request=spec, field_mapping={"t": FieldTransform(name="temp", field_type="float")})
        fetch = _fetcher({"https://api.example.com/w": [{"t": "21.5", "city": "北京"}]})
        outcome = run_pipeline(job, provider=PROVIDER, fetch=fetch)  # type: ignore[arg-type]
        assert outcome.status == "success"
        assert outcome.rows == [{"temp": 21.5, "city": "北京"}]
        assert (outcome.plans, outcome.succeeded, outcome.failed) == (1, 1, 0)

    def test_paging_stops_after_empty_page(self):
        spec = RequestSpec(
            url_template="https://api.example.com/list?p={page}",
            paging=PagingSpec(mode="page", start_page=1, max_pages=5),
        )
        fetch = _fetcher(
            {
                "https://api.example.com/list?p=1": [{"a": 1}],
                "https://api.example.com/list?p=2": [{"a": 2}],
                "https://api.example.com/list?p=3": [],
            }
        )
        outcome = run_pipeline(_job(request=spec), provider=PROVIDER, fetch=fetch)  # type: ignore[arg-type]
        # 第 3 页为空 → 第 4、5 页不再请求
        assert fetch.calls == [  # type: ignore[attr-defined]
            "https://api.example.com/list?p=1",
            "https://api.example.com/list?p=2",
            "https://api.example.com/list?p=3",
        ]
        assert len(outcome.rows) == 2
        assert outcome.status == "success"

    def test_single_failure_is_partial(self):
        spec = RequestSpec(
            url_template="https://api.example.com/w?city={city}",
            paging=PagingSpec(),
        )
        job = _job(request=spec, entrant_param="city", entrant_values=("北京", "缺失城市"))
        fetch = _fetcher({"https://api.example.com/w?city=北京": [{"city": "北京"}]})
        outcome = run_pipeline(job, provider=PROVIDER, fetch=fetch)  # type: ignore[arg-type]
        assert outcome.status == "partial"
        assert len(outcome.rows) == 1
        assert outcome.failures[0].entrant == "缺失城市"
        assert "模拟源故障" in outcome.failures[0].error

    def test_all_failures_is_failed(self):
        job = _job(request=RequestSpec(url_template="https://api.example.com/down"))
        outcome = run_pipeline(job, provider=PROVIDER, fetch=_fetcher({}))  # type: ignore[arg-type]
        assert outcome.status == "failed"
        assert outcome.rows == []
        assert outcome.normalize is not None

    def test_empty_plans_is_success(self):
        job = _job()
        outcome = run_pipeline(job, provider=_NoPlanProvider(), fetch=_fetcher({}))  # type: ignore[arg-type]
        assert outcome.plans == 0
        assert outcome.status == "success"


class _NoPlanProvider(HttpJsonProvider):
    """无请求的 provider（覆盖 plans=0 分支）."""

    def build_requests(self, job: SyncJobSpec) -> list:
        return []


# ── 注册表 ───────────────────────────────────────


class TestRegistry:
    def test_builtin_registered(self):
        assert "http_json" in PROVIDERS
        assert get_provider().name == "http_json"

    def test_default_and_unknown(self):
        assert get_provider(None).name == "http_json"
        with pytest.raises(ProviderError, match="未知 provider"):
            get_provider("nope")

    def test_list_providers_metadata(self):
        entries = {item["name"]: item for item in list_providers()}
        assert entries["http_json"]["supports_paging"] is True
        assert entries["http_json"]["default_cursor"] == "date"
        assert "fields" in entries["http_json"]["params_schema"]

    def test_duplicate_registration_rejected(self):
        with pytest.raises(ProviderError, match="已注册"):
            register_provider(HttpJsonProvider())
        register_provider(HttpJsonProvider(), replace=True)
        register_builtins()  # 幂等：重复登记不报错

    def test_register_rejects_empty_name(self):
        class _Nameless(HttpJsonProvider):
            name = ""

        with pytest.raises(ProviderError, match="不能为空"):
            register_provider(_Nameless())


# ── 落表 ─────────────────────────────────────────


def _make_table(session: Session, engine, *, workspace_id: int = 1) -> DataTable:
    dt = DataTable(workspace_id=workspace_id, name="同步目标表")
    dt.ensure_db_name()
    session.add(dt)
    session.commit()
    session.refresh(dt)
    return dt


def _add_field(session: Session, table: DataTable, name: str, field_type: str, order: int) -> None:
    field = DataField(table_id=table.id, name=name, field_type=field_type, order=order)
    field.ensure_db_name()
    session.add(field)
    session.flush()


def _row_count(engine, table: DataTable) -> int:
    metadata = MetaData()
    sa_table = ddl.build_sa_table(metadata, table)
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(sa_table)).scalar_one())


class TestUpsertRows:
    def _table(self, session: Session, engine) -> DataTable:
        table = _make_table(session, engine)
        _add_field(session, table, "symbol", "text", 0)
        _add_field(session, table, "trade_date", "date", 1)
        _add_field(session, table, "close", "float", 2)
        session.commit()
        session.refresh(table)
        ddl.create_table(engine, table)
        return table

    def test_empty_rows_is_noop(self, db_engine, db):
        table = self._table(db, db_engine)
        outcome = upsert_rows(db_engine, db, table, [], match_keys=["symbol", "trade_date"])
        assert (outcome.fetched, outcome.inserted, outcome.updated) == (0, 0, 0)

    def test_insert_then_update_same_keys(self, db_engine, db):
        table = self._table(db, db_engine)
        rows = [{"symbol": "sh600519", "trade_date": "2024-01-02", "close": 1680.0}]
        first = upsert_rows(db_engine, db, table, rows, match_keys=["symbol", "trade_date"])
        assert first.inserted == 1
        assert first.updated == 0
        assert first.changed == 1

        second = upsert_rows(
            db_engine,
            db,
            table,
            [{"symbol": "sh600519", "trade_date": "2024-01-02", "close": 1700.0}],
            match_keys=["symbol", "trade_date"],
        )
        assert second.inserted == 0
        assert second.updated == 1
        # 幂等：同一幂等键只留一行
        assert _row_count(db_engine, table) == 1

    def test_without_match_keys_appends(self, db_engine, db):
        table = self._table(db, db_engine)
        rows = [{"symbol": "sh600519", "trade_date": "2024-01-02", "close": 1.0}]
        upsert_rows(db_engine, db, table, rows)
        upsert_rows(db_engine, db, table, rows)
        assert _row_count(db_engine, table) == 2
