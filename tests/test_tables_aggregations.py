"""聚合统计测试：分组聚合编译执行与视图聚合端点."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from cndb.tables import query, records, services
from cndb.tables.aggregations import InvalidAggregationError, fetch_aggregations, parse_aggregations
from cndb.tables.models import DataTable, DataView
from cndb.workspaces.models import Workspace


@pytest.fixture
def table(workspace: Workspace) -> DataTable:
    """含文本/数值/日期/布尔字段的测试表."""
    return services.create_table(
        workspace=workspace,
        name="销售表",
        field_defs=[
            {"name": "地区", "field_type": "text"},
            {"name": "金额", "field_type": "number", "config": {"precision": 10, "scale": 2}},
            {"name": "日期", "field_type": "date"},
            {"name": "成交", "field_type": "boolean"},
        ],
    )


@pytest.fixture
def rows(table: DataTable) -> None:
    """四行样本数据."""
    samples = [
        {"地区": "华东", "金额": 100.0, "日期": "2026-01-01", "成交": True},
        {"地区": "华东", "金额": 50.5, "日期": "2026-01-02", "成交": False},
        {"地区": "华北", "金额": 200.0, "日期": "2026-02-01", "成交": True},
        {"地区": None, "金额": None, "日期": None, "成交": True},
    ]
    for row in samples:
        records.insert_row(table, records.clean_row(table, row))


class TestParseAggregations:
    """聚合请求解析."""

    def test_valid(self, table: DataTable) -> None:
        """合法分组与聚合解析."""
        agg = parse_aggregations(table, {"group_by": "地区", "agg__金额": "sum"})
        assert agg.group_by == "地区"
        assert agg.aggs == {"金额": "sum"}

    def test_no_params(self, table: DataTable) -> None:
        """无参数返回空聚合（仅计数）."""
        agg = parse_aggregations(table, {})
        assert agg.group_by is None
        assert agg.aggs == {}

    def test_unknown_group_field(self, table: DataTable) -> None:
        """未知分组字段拒绝."""
        with pytest.raises(InvalidAggregationError, match="未知分组字段"):
            parse_aggregations(table, {"group_by": "不存在"})

    def test_group_by_id_rejected(self, table: DataTable) -> None:
        """分组字段不支持 id."""
        with pytest.raises(InvalidAggregationError, match="id"):
            parse_aggregations(table, {"group_by": "id"})

    def test_unknown_agg_field(self, table: DataTable) -> None:
        """未知聚合字段拒绝."""
        with pytest.raises(InvalidAggregationError, match="未知聚合字段"):
            parse_aggregations(table, {"agg__不存在": "sum"})

    def test_invalid_func(self, table: DataTable) -> None:
        """未知聚合函数拒绝."""
        with pytest.raises(InvalidAggregationError, match="聚合函数"):
            parse_aggregations(table, {"agg__金额": "median"})

    def test_type_not_allowed(self, table: DataTable) -> None:
        """布尔字段不支持 sum 聚合."""
        with pytest.raises(InvalidAggregationError, match="不支持"):
            parse_aggregations(table, {"agg__成交": "sum"})


class TestFetchAggregations:
    """聚合执行（服务层）."""

    def _fetch(self, table: DataTable, params: dict[str, Any], filters: list[Any] | None = None) -> dict[str, Any]:
        """按参数执行聚合（可选视图筛选）."""
        agg = parse_aggregations(table, params)
        where, where_params = query.compile_filters(table, filters or [])
        return fetch_aggregations(table, query.RowQuery(where=where, params=where_params), agg)

    def test_group_count_and_sum(self, table: DataTable, rows: None) -> None:
        """按地区分组计数与求和（NULL 组在前）."""
        result = self._fetch(table, {"group_by": "地区", "agg__金额": "sum"})
        assert result["group_by"] == "地区"
        groups = {str(group["value"]): group for group in result["results"]}
        assert groups["华东"]["count"] == 2
        assert groups["华东"]["aggregations"]["金额"] == Decimal("150.5")
        assert groups["华北"]["count"] == 1
        assert groups["华北"]["aggregations"]["金额"] == Decimal("200")
        assert groups["None"]["count"] == 1
        assert groups["None"]["aggregations"]["金额"] is None

    def test_overall_aggregation(self, table: DataTable, rows: None) -> None:
        """无分组整体聚合：count/avg/min/max."""
        result = self._fetch(table, {"agg__金额": "avg", "agg__日期": "min", "agg__地区": "max"})
        assert result["group_by"] is None
        assert len(result["results"]) == 1
        overall = result["results"][0]
        assert overall["count"] == 4
        avg = overall["aggregations"]["金额"]
        assert avg is not None
        assert abs(avg - Decimal("350.5") / 3) < Decimal("0.000001")
        assert overall["aggregations"]["日期"] == date(2026, 1, 1)
        assert overall["aggregations"]["地区"] == "华北"

    def test_count_only(self, table: DataTable, rows: None) -> None:
        """无聚合函数仅返回行数."""
        result = self._fetch(table, {})
        assert result["results"][0]["count"] == 4
        assert result["results"][0]["aggregations"] == {}

    def test_filters_applied(self, table: DataTable, rows: None) -> None:
        """聚合应用视图筛选条件."""
        result = self._fetch(
            table,
            {"group_by": "地区", "agg__金额": "sum"},
            filters=[{"field": "成交", "op": "eq", "value": True}],
        )
        groups = {str(group["value"]): group for group in result["results"]}
        assert groups["华东"]["count"] == 1
        assert groups["华东"]["aggregations"]["金额"] == Decimal("100")
        assert "华东" in groups and groups["华北"]["count"] == 1


class TestAggregationsAPI:
    """视图聚合端点."""

    def _url(self, workspace: Workspace, table: DataTable, view: DataView) -> str:
        """聚合端点地址."""
        return f"/api/workspaces/{workspace.pk}/tables/{table.pk}/views/{view.pk}/aggregations/"

    def test_group_aggregation(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable, rows: None
    ) -> None:
        """分组聚合返回各组计数与求和."""
        view = DataView.objects.create(table=table, name="聚合视图")
        response = auth_client.get(self._url(workspace, table, view), {"group_by": "地区", "agg__金额": "sum"})
        assert response.status_code == 200
        groups = {str(group["value"]): group for group in response.data["results"]}
        assert groups["华东"]["count"] == 2
        assert groups["华东"]["aggregations"]["金额"] == Decimal("150.5")

    def test_view_filters_applied(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable, rows: None
    ) -> None:
        """端点应用视图筛选."""
        view = DataView.objects.create(
            table=table,
            name="成交视图",
            filters=[{"field": "成交", "op": "eq", "value": True}],
        )
        response = auth_client.get(self._url(workspace, table, view), {"agg__金额": "sum"})
        assert response.status_code == 200
        assert response.data["results"][0]["count"] == 3
        assert response.data["results"][0]["aggregations"]["金额"] == Decimal("300")

    def test_invalid_params_returns_400(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """非法聚合参数返回 400."""
        view = DataView.objects.create(table=table, name="视图")
        response = auth_client.get(self._url(workspace, table, view), {"agg__成交": "sum"})
        assert response.status_code == 400
        response = auth_client.get(self._url(workspace, table, view), {"group_by": "不存在"})
        assert response.status_code == 400
