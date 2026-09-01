"""查询编译测试：过滤/排序/分页参数到 SQL 的安全编译与接口行为."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from cndb.tables import query, records, services
from cndb.tables.models import DataTable
from cndb.tables.query import InvalidQueryError
from cndb.workspaces.models import Workspace


@pytest.fixture
def table(workspace: Workspace) -> DataTable:
    """含文本/数值/日期/布尔字段的测试表."""
    return services.create_table(
        workspace=workspace,
        name="项目表",
        field_defs=[
            {"name": "名称", "field_type": "text", "required": True},
            {"name": "金额", "field_type": "number", "config": {"precision": 10, "scale": 2}},
            {"name": "截止日", "field_type": "date"},
            {"name": "完成", "field_type": "boolean"},
        ],
    )


@pytest.fixture
def rows(table: DataTable) -> list[int]:
    """插入三行样本数据，返回行 id 列表."""
    samples = [
        {"名称": "项目甲", "金额": 10.5, "截止日": "2026-01-01", "完成": True},
        {"名称": "项目乙", "金额": 20.0, "截止日": "2026-02-01", "完成": False},
        {"名称": "任务丙", "金额": 30.25, "截止日": None, "完成": True},
    ]
    return [records.insert_row(table, records.clean_row(table, row)) for row in samples]


def _fetch(table: DataTable, params: dict[str, Any]) -> list[dict[str, Any]]:
    """按查询参数读取行（服务层组合）."""
    where, sql_params = query.parse_filters(table, params)
    order = query.parse_order_by(table, params.get("order_by"))
    return records.fetch_rows(table, query.RowQuery(where=where, params=sql_params, order=order))


class TestFilterCompile:
    """过滤编译."""

    def test_eq_text(self, table: DataTable, rows: list[int]) -> None:
        """文本等值过滤."""
        result = _fetch(table, {"filter__名称__eq": "项目甲"})
        assert [row["id"] for row in result] == [rows[0]]

    def test_gt_number(self, table: DataTable, rows: list[int]) -> None:
        """数值大于过滤."""
        result = _fetch(table, {"filter__金额__gt": 15})
        assert {row["id"] for row in result} == {rows[1], rows[2]}

    def test_contains_text(self, table: DataTable, rows: list[int]) -> None:
        """文本包含过滤."""
        result = _fetch(table, {"filter__名称__contains": "项目"})
        assert len(result) == 2

    def test_is_null(self, table: DataTable, rows: list[int]) -> None:
        """空值过滤：截止日为空的是第三行."""
        result = _fetch(table, {"filter__截止日__is_null": "true"})
        assert [row["id"] for row in result] == [rows[2]]
        result = _fetch(table, {"filter__截止日__is_null": "false"})
        assert len(result) == 2

    def test_multiple_filters_and(self, table: DataTable, rows: list[int]) -> None:
        """多条件 AND 组合."""
        result = _fetch(table, {"filter__金额__gte": 10, "filter__完成__eq": "false"})
        assert [row["id"] for row in result] == [rows[1]]

    def test_lte_date(self, table: DataTable, rows: list[int]) -> None:
        """日期小于等于过滤."""
        result = _fetch(table, {"filter__截止日__lte": "2026-01-15"})
        assert [row["id"] for row in result] == [rows[0]]

    def test_unknown_field_rejected(self, table: DataTable) -> None:
        """未知字段拒绝."""
        with pytest.raises(InvalidQueryError, match="未知字段"):
            query.parse_filters(table, {"filter__不存在__eq": 1})

    def test_unknown_op_rejected(self, table: DataTable) -> None:
        """未知操作符拒绝."""
        with pytest.raises(InvalidQueryError, match="不支持的过滤操作符"):
            query.parse_filters(table, {"filter__名称__regex": ".*"})

    def test_contains_non_text_rejected(self, table: DataTable) -> None:
        """非文本字段使用 contains 拒绝."""
        with pytest.raises(InvalidQueryError, match="文本类字段"):
            query.parse_filters(table, {"filter__金额__contains": 1})

    def test_invalid_value_rejected(self, table: DataTable) -> None:
        """过滤值类型非法拒绝."""
        with pytest.raises(InvalidQueryError, match="过滤值非法"):
            query.parse_filters(table, {"filter__金额__eq": "不是数字"})

    def test_malformed_param_rejected(self, table: DataTable) -> None:
        """格式错误的过滤参数拒绝."""
        with pytest.raises(InvalidQueryError, match="非法过滤参数"):
            query.parse_filters(table, {"filter__名称": "x"})

    def test_no_filters_returns_empty_where(self, table: DataTable) -> None:
        """无过滤参数返回空 WHERE."""
        where, params = query.parse_filters(table, {"page": "2"})
        assert where == "" and params == []


class TestOrderCompile:
    """排序编译."""

    def test_order_by_field_desc(self, table: DataTable, rows: list[int]) -> None:
        """按金额降序."""
        result = _fetch(table, {"order_by": "-金额"})
        assert [row["id"] for row in result] == [rows[2], rows[1], rows[0]]

    def test_order_by_multiple_fields(self, table: DataTable, rows: list[int]) -> None:
        """按完成升序 + 金额降序组合排序（未完成的乙在前）."""
        result = _fetch(table, {"order_by": "完成,-金额"})
        assert [row["id"] for row in result] == [rows[1], rows[2], rows[0]]

    def test_default_order_by_id(self, table: DataTable, rows: list[int]) -> None:
        """默认按 id 升序."""
        result = _fetch(table, {})
        assert [row["id"] for row in result] == rows

    def test_unknown_order_field_rejected(self, table: DataTable) -> None:
        """未知排序字段拒绝."""
        with pytest.raises(InvalidQueryError, match="未知排序字段"):
            query.parse_order_by(table, "不存在")


class TestQueryAPI:
    """查询接口."""

    def _url(self, workspace: Workspace, table: DataTable) -> str:
        """行列表地址."""
        return f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/"

    def test_filter_and_order(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable, rows: list[int]
    ) -> None:
        """过滤 + 排序组合查询."""
        response = auth_client.get(self._url(workspace, table), {"filter__完成__eq": "true", "order_by": "-金额"})
        assert response.status_code == 200
        assert response.data["count"] == 2
        assert [row["id"] for row in response.data["results"]] == [rows[2], rows[0]]

    def test_pagination(self, auth_client: APIClient, workspace: Workspace, table: DataTable, rows: list[int]) -> None:
        """分页返回 count/next/previous."""
        first = auth_client.get(self._url(workspace, table), {"page_size": 2})
        assert first.status_code == 200
        assert first.data["count"] == 3
        assert len(first.data["results"]) == 2
        assert first.data["next"] is not None
        assert first.data["previous"] is None
        second = auth_client.get(self._url(workspace, table), {"page_size": 2, "page": 2})
        assert len(second.data["results"]) == 1
        assert second.data["next"] is None
        assert second.data["previous"] is not None

    def test_invalid_filter_returns_400(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """非法过滤参数返回 400."""
        response = auth_client.get(self._url(workspace, table), {"filter__不存在__eq": 1})
        assert response.status_code == 400

    def test_invalid_page_returns_400(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """非法分页参数返回 400."""
        response = auth_client.get(self._url(workspace, table), {"page": 0})
        assert response.status_code == 400
        response = auth_client.get(self._url(workspace, table), {"page_size": 999})
        assert response.status_code == 400
