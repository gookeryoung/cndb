"""dashboard 批量取数端点与服务端聚合测试（ADR 0023 P2）.

覆盖：14 类 Dataset 装配、同表只扫描一次（多 widget 共享行集）、组件级过滤/排序/TopN、
缓存命中与 force、单 widget 失败隔离、全局筛选、非 dashboard 视图拒绝、updated_at 乐观并发。
"""

from __future__ import annotations

from typing import Any

import pytest

from cndb.core.cache import dashboard_cache
from cndb.core.events import invalidate_for_event
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core.dashboard_data import (
    _FieldInfo,
    build_boxplot_dataset,
    build_funnel_dataset,
    build_gauge_dataset,
    build_heatmap_dataset,
    build_histogram_dataset,
    build_pie_dataset,
    build_radar_dataset,
    build_scatter_dataset,
    build_treemap_dataset,
)
from cndb.plugins.tables.services.core.records import create_row
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

ROWS = [
    {"订单号": "A001", "商品类别": "数码", "销售额": 100, "数量": 2, "日期": "2026-01-10"},
    {"订单号": "A002", "商品类别": "家电", "销售额": 50, "数量": 1, "日期": "2026-02-11"},
    {"订单号": "A003", "商品类别": "数码", "销售额": 70, "数量": 3, "日期": "2026-02-12"},
    {"订单号": "A004", "商品类别": "食品", "销售额": 120, "数量": 4, "日期": "2026-03-12"},
    {"订单号": "A005", "商品类别": "家电", "销售额": 40, "数量": 5, "日期": "2026-03-13"},
    {"订单号": "A006", "商品类别": "数码", "销售额": 30, "数量": 6, "日期": "2026-01-20"},
]


@pytest.fixture
def owner(db) -> User:
    user = User(username="ddata_owner", nickname="Owner")
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def auth_owner(client, owner) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": owner.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def ws(db, owner) -> Workspace:
    workspace = Workspace(name="DDataWS", created_by_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(workspace)
    return workspace


@pytest.fixture
def table(db, ws) -> DataTable:
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="销售数据")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    specs = (
        ("订单号", "text"),
        ("商品类别", "text"),
        ("销售额", "number"),
        ("数量", "number"),
        ("日期", "date"),
    )
    for order, (name, field_type) in enumerate(specs):
        field = DataField(table_id=dt.id, name=name, field_type=field_type, order=order)
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    for values in ROWS:
        create_row(engine, dt, values, db=db)
    db.commit()
    return dt


WIDGETS: list[dict[str, Any]] = [
    {
        "id": "kpi",
        "type": "kpi",
        "layout": {"x": 0, "y": 0, "w": 3, "h": 4},
        "kpi": {"value": {"field": "销售额", "agg": "sum"}},
    },
    {
        "id": "bar",
        "type": "chart",
        "layout": {"x": 0, "y": 4, "w": 6, "h": 8},
        "chart": {"type": "bar", "x": "商品类别", "y": ["销售额"], "agg": "sum"},
    },
    {
        "id": "pie",
        "type": "chart",
        "layout": {"x": 6, "y": 0, "w": 3, "h": 6},
        "chart": {"type": "pie", "x": "商品类别", "y": ["销售额"], "agg": "sum"},
    },
    {
        "id": "scatter",
        "type": "chart",
        "layout": {"x": 0, "y": 12, "w": 6, "h": 6},
        "chart": {"type": "scatter", "x": "数量", "y": ["销售额"], "agg": "sum"},
    },
    {
        "id": "histogram",
        "type": "chart",
        "layout": {"x": 6, "y": 12, "w": 6, "h": 6},
        "chart": {"type": "histogram", "y": ["销售额"], "agg": "sum"},
    },
    {
        "id": "boxplot",
        "type": "chart",
        "layout": {"x": 0, "y": 18, "w": 6, "h": 6},
        "chart": {"type": "boxplot", "x": "商品类别", "y": ["销售额"], "agg": "sum"},
    },
    {
        "id": "radar",
        "type": "chart",
        "layout": {"x": 0, "y": 24, "w": 6, "h": 6},
        "chart": {"type": "radar", "x": "商品类别", "y": ["销售额", "数量"], "agg": "sum"},
    },
    {
        "id": "funnel",
        "type": "chart",
        "layout": {"x": 6, "y": 18, "w": 6, "h": 6},
        "chart": {"type": "funnel", "x": "商品类别", "y": ["销售额"], "agg": "sum"},
    },
    {
        "id": "gauge",
        "type": "chart",
        "layout": {"x": 6, "y": 24, "w": 3, "h": 4},
        "chart": {"type": "gauge", "y": ["销售额"], "agg": "sum"},
    },
    {
        "id": "heatmap",
        "type": "chart",
        "layout": {"x": 0, "y": 30, "w": 6, "h": 7},
        "chart": {"type": "heatmap", "x": "商品类别", "series": "日期", "y": ["销售额"], "agg": "sum"},
    },
    {
        "id": "treemap",
        "type": "chart",
        "layout": {"x": 6, "y": 30, "w": 6, "h": 7},
        "chart": {"type": "treemap", "x": "商品类别", "series": "日期", "y": ["销售额"], "agg": "sum"},
    },
    {
        "id": "detail",
        "type": "table",
        "layout": {"x": 0, "y": 38, "w": 12, "h": 8},
        "table": {"columns": ["订单号", "商品类别", "销售额"], "row_limit": 3},
    },
]

GLOBAL_DATE = [{"id": "range", "kind": "date_range", "field": "日期"}]

#: 纯函数测试用的字段信息（与 fixture 表同构）
INFOS = {
    name: _FieldInfo(name, field_type, {})
    for name, field_type in (
        ("订单号", "text"),
        ("商品类别", "text"),
        ("销售额", "number"),
        ("数量", "number"),
        ("日期", "date"),
    )
}

CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "widgets": WIDGETS,
    "global_filters": GLOBAL_DATE,
    "settings": {"refresh_interval": 0, "theme": "inherit"},
}


def _url(ws: Workspace, table: DataTable) -> str:
    return f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views"


@pytest.fixture
def dashboard_view(client, ws, table, auth_owner) -> dict[str, Any]:
    dashboard_cache.clear()
    r = client.post(
        _url(ws, table),
        json={"name": "取数画布", "view_type": "dashboard", "view_options": CONFIG},
        headers=auth_owner,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _data(client, ws, table, view, auth, body: dict[str, Any] | None = None):
    return client.post(f"{_url(ws, table)}/{view['id']}/dashboard/data", json=body or {}, headers=auth)


# ── 服务端聚合（纯函数）────────────────────────────────


def test_category_and_pie_aggregate_by_dimension() -> None:
    rows = [dict(r) for r in ROWS]
    bar = build_pie_dataset(rows, INFOS, {"type": "pie", "x": "商品类别", "y": ["销售额"], "agg": "sum"})
    values = {item["name"]: item["value"] for item in bar["items"]}
    assert values == {"数码": 200, "家电": 90, "食品": 120}


def test_scatter_skips_non_numeric() -> None:
    rows = [{"数量": 2, "销售额": 100, "id": 1}, {"数量": None, "销售额": 50, "id": 2}]
    data = build_scatter_dataset(rows, {"x": "数量", "y": ["销售额"]})
    assert data["points"] == [[2.0, 100.0]]
    assert data["rowIds"] == [1]


def test_histogram_bins_cover_all_values() -> None:
    rows = [{"销售额": v} for v in (30, 40, 50, 70, 100, 120)]
    data = build_histogram_dataset(rows, {"y": ["销售额"]})
    assert sum(bin_["count"] for bin_ in data["bins"]) == 6
    assert data["bins"][0]["from"] == 30
    assert data["bins"][-1]["to"] == 120


def test_boxplot_quantiles_and_outliers() -> None:
    rows = [{"商品类别": "数码", "销售额": v} for v in (30, 60, 100, 500)]
    data = build_boxplot_dataset(rows, INFOS, {"x": "商品类别", "y": ["销售额"]})
    assert data["categories"] == ["数码"]
    assert data["boxes"][0][0] == 30
    assert data["boxes"][0][-1] == 500
    assert [point[1] for point in data["outliers"]] == [500]


def test_radar_funnel_gauge_treemap_heatmap_shapes() -> None:
    rows = [dict(r) for r in ROWS]
    radar = build_radar_dataset(rows, INFOS, {"x": "商品类别", "y": ["销售额", "数量"], "agg": "sum"})
    assert radar["indicators"][0]["name"] == "销售额"
    assert {s["name"] for s in radar["series"]} == {"数码", "家电", "食品"}

    funnel = build_funnel_dataset(rows, INFOS, {"x": "商品类别", "y": ["销售额"], "agg": "sum"})
    assert [item["value"] for item in funnel["items"]] == [200, 120, 90]

    gauge = build_gauge_dataset(rows, {"y": ["销售额"], "agg": "sum", "target": 500})
    assert gauge["value"] == 410
    assert gauge["target"] == 500

    treemap = build_treemap_dataset(
        rows,
        INFOS,
        {"x": "商品类别", "series": "日期", "y": ["销售额"], "agg": "sum"},
    )
    assert treemap["nodes"][0]["name"] == "数码"
    assert treemap["nodes"][0]["value"] == 200

    heatmap = build_heatmap_dataset(
        rows,
        INFOS,
        {"x": "商品类别", "series": "日期", "y": ["销售额"], "agg": "sum"},
    )
    assert heatmap["x"] == ["家电", "数码", "食品"]
    # 日期维度按月分桶（与客户端 dimKey 同口径）：数码在 2026-01 合计 100+30=130
    assert heatmap["y"] == ["2026-01", "2026-02", "2026-03"]
    assert len(heatmap["values"]) == len(heatmap["x"]) * len(heatmap["y"])
    assert heatmap["max"] == 130


# ── API 层 ─────────────────────────────────────────────


class TestDashboardDataAPI:
    def test_returns_datasets_for_all_kinds(self, client, ws, table, dashboard_view, auth_owner):
        r = _data(client, ws, table, dashboard_view, auth_owner)
        assert r.status_code == 200, r.text
        body = r.json()
        datasets = {item["widget_id"]: item["dataset"] for item in body["items"]}
        assert body["errors"] == []
        assert set(datasets) == {w["id"] for w in WIDGETS}
        assert datasets["kpi"] == {"kind": "kpi", "field": "销售额", "agg": "sum", "value": 410}
        assert datasets["bar"]["kind"] == "category"
        assert datasets["bar"]["categories"] == ["家电", "数码", "食品"]
        assert datasets["bar"]["series"][0]["data"] == [90, 200, 120]
        assert {item["name"]: item["value"] for item in datasets["pie"]["items"]} == {
            "家电": 90,
            "数码": 200,
            "食品": 120,
        }
        assert datasets["scatter"]["rowIds"] == [1, 2, 3, 4, 5, 6]
        assert datasets["gauge"]["value"] == 410
        assert datasets["detail"]["columns"] == ["订单号", "商品类别", "销售额"]
        assert datasets["detail"]["total"] == 6
        assert len(datasets["detail"]["rows"]) == 3
        assert all(item["meta"]["total"] == 6 for item in body["items"])

    def test_subset_widget_ids_only(self, client, ws, table, dashboard_view, auth_owner):
        r = _data(client, ws, table, dashboard_view, auth_owner, {"widget_ids": ["bar", "kpi"]})
        assert r.status_code == 200
        assert [item["widget_id"] for item in r.json()["items"]] == ["bar", "kpi"]

    def test_unknown_widget_id_is_isolated(self, client, ws, table, dashboard_view, auth_owner):
        r = _data(client, ws, table, dashboard_view, auth_owner, {"widget_ids": ["missing", "bar"]})
        assert r.status_code == 200
        assert r.json()["errors"][0]["widget_id"] == "missing"
        assert [item["widget_id"] for item in r.json()["items"]] == ["bar"]

    def test_cache_hit_and_force(self, client, ws, table, dashboard_view, auth_owner):
        first = _data(client, ws, table, dashboard_view, auth_owner).json()
        assert first["items"][0]["meta"]["cached"] is False
        second = _data(client, ws, table, dashboard_view, auth_owner).json()
        assert second["items"][0]["meta"]["cached"] is True
        forced = _data(client, ws, table, dashboard_view, auth_owner, {"force": True}).json()
        assert forced["items"][0]["meta"]["cached"] is False

    def test_cache_invalidated_by_record_event(self, client, ws, table, dashboard_view, auth_owner):
        assert _data(client, ws, table, dashboard_view, auth_owner).json()["items"][0]["meta"]["cached"] is False
        assert _data(client, ws, table, dashboard_view, auth_owner).json()["items"][0]["meta"]["cached"] is True
        invalidate_for_event("record.update", ws.id)
        assert _data(client, ws, table, dashboard_view, auth_owner).json()["items"][0]["meta"]["cached"] is False

    def test_global_date_range_applied(self, client, ws, table, dashboard_view, auth_owner):
        r = _data(
            client,
            ws,
            table,
            dashboard_view,
            auth_owner,
            {"widget_ids": ["kpi"], "globals": {"range": ["2026-01-01", "2026-01-31"]}},
        )
        assert r.status_code == 200
        assert r.json()["items"][0]["dataset"]["value"] == 130
        assert r.json()["items"][0]["meta"]["scanned"] == 2

    def test_widget_query_filter_and_top_n(self, client, ws, table, auth_owner, db):
        options = {
            "widgets": [
                {
                    "id": "top",
                    "type": "chart",
                    "layout": {"x": 0, "y": 0, "w": 6, "h": 6},
                    "chart": {
                        "type": "bar",
                        "x": "商品类别",
                        "y": ["销售额"],
                        "agg": "sum",
                        "sort": "y_desc",
                        "top_n": 1,
                    },
                    "query": {"filters": [{"field_name": "销售额", "op": ">=", "value": 40}]},
                }
            ],
        }
        created = client.post(
            _url(ws, table),
            json={"name": "TopN", "view_type": "dashboard", "view_options": options},
            headers=auth_owner,
        )
        assert created.status_code == 201
        r = _data(client, ws, table, created.json(), auth_owner)
        assert r.status_code == 200
        dataset = r.json()["items"][0]["dataset"]
        assert dataset["categories"] == ["数码", "其他"]
        assert dataset["series"][0]["data"] == [170, 210]

    def test_non_dashboard_view_rejected(self, client, ws, table, auth_owner):
        created = client.post(
            _url(ws, table),
            json={"name": "普通表格", "view_type": "grid"},
            headers=auth_owner,
        )
        assert created.status_code == 201
        r = _data(client, ws, table, created.json(), auth_owner)
        assert r.status_code == 400
        assert "dashboard" in r.json()["detail"]

    def test_updated_at_conflict(self, client, ws, table, dashboard_view, auth_owner):
        url = f"{_url(ws, table)}/{dashboard_view['id']}"
        ok = client.patch(
            url, json={"name": "改名", "expected_updated_at": dashboard_view["updated_at"]}, headers=auth_owner
        )
        assert ok.status_code == 200
        stale = client.patch(
            url, json={"name": "旧时间", "expected_updated_at": dashboard_view["updated_at"]}, headers=auth_owner
        )
        assert stale.status_code == 409
        assert "刷新" in stale.json()["detail"]

    def test_updated_at_matching_allows_save(self, client, ws, table, dashboard_view, auth_owner):
        url = f"{_url(ws, table)}/{dashboard_view['id']}"
        r = client.patch(
            url, json={"name": "新名字", "expected_updated_at": dashboard_view["updated_at"]}, headers=auth_owner
        )
        assert r.status_code == 200
        assert r.json()["name"] == "新名字"
