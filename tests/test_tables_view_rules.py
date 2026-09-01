"""视图规则测试：规则校验归一化、结构化过滤/排序编译与视图 API 行为."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from cndb.accounts.models import User
from cndb.tables import query, records, services
from cndb.tables.models import DataTable, DataView
from cndb.tables.view_rules import InvalidViewError, ViewRules, normalize_view
from cndb.workspaces.models import Workspace


@pytest.fixture
def table(workspace: Workspace) -> DataTable:
    """含文本/数值/布尔字段的测试表."""
    return services.create_table(
        workspace=workspace,
        name="项目表",
        field_defs=[
            {"name": "名称", "field_type": "text", "required": True},
            {"name": "金额", "field_type": "number", "config": {"precision": 10, "scale": 2}},
            {"name": "完成", "field_type": "boolean"},
        ],
    )


@pytest.fixture
def rows(table: DataTable) -> list[int]:
    """三行样本数据."""
    samples = [
        {"名称": "项目甲", "金额": 10.5, "完成": True},
        {"名称": "项目乙", "金额": 20.0, "完成": False},
        {"名称": "任务丙", "金额": 30.25, "完成": True},
    ]
    return [records.insert_row(table, records.clean_row(table, row)) for row in samples]


class TestNormalizeView:
    """视图规则校验归一化."""

    def test_valid_config_normalized(self, table: DataTable) -> None:
        """合法配置归一化：字段选项补全默认值."""
        normalized = normalize_view(
            table,
            ViewRules(
                filters=[{"field": "名称", "op": "contains", "value": "项目"}],
                sortings=[{"field": "金额", "desc": True}],
                field_options={"名称": {"hidden": True}},
            ),
        )
        assert normalized["filters"] == [{"field": "名称", "op": "contains", "value": "项目"}]
        assert normalized["sortings"] == [{"field": "金额", "desc": True}]
        assert normalized["field_options"]["名称"] == {"hidden": True, "width": 200, "order": 0}

    def test_empty_defaults(self, table: DataTable) -> None:
        """空配置归一化为空结构与表单默认文案."""
        normalized = normalize_view(table, ViewRules())
        assert normalized == {
            "filters": [],
            "sortings": [],
            "field_options": {},
            "form_options": {"title": "", "description": "", "submit_text": "提交", "fields": {}},
        }

    def test_unknown_filter_field_rejected(self, table: DataTable) -> None:
        """筛选引用未知字段拒绝."""
        with pytest.raises(InvalidViewError, match="未知字段"):
            normalize_view(
                table,
                ViewRules(filters=[{"field": "不存在", "op": "eq", "value": 1}]),
            )

    def test_invalid_filter_value_rejected(self, table: DataTable) -> None:
        """筛选值类型非法在保存期即拒绝（dry-run 预检）."""
        with pytest.raises(InvalidViewError, match="过滤值非法"):
            normalize_view(
                table,
                ViewRules(filters=[{"field": "金额", "op": "eq", "value": "不是数字"}]),
            )

    def test_field_option_bounds(self, table: DataTable) -> None:
        """字段选项：未知字段、width 越界、hidden 非布尔均拒绝."""
        with pytest.raises(InvalidViewError, match="未知字段"):
            normalize_view(table, ViewRules(field_options={"不存在": {}}))
        with pytest.raises(InvalidViewError, match="width"):
            normalize_view(table, ViewRules(field_options={"名称": {"width": 10}}))
        with pytest.raises(InvalidViewError, match="hidden"):
            normalize_view(table, ViewRules(field_options={"名称": {"hidden": "yes"}}))

    def test_structure_rejections(self, table: DataTable) -> None:
        """结构与类型非法输入的全量拒绝矩阵."""
        cases: list[tuple[ViewRules, str]] = [
            (ViewRules(filters={}), "filters 必须是数组"),
            (ViewRules(filters=["x"]), "每条筛选规则必须是对象"),
            (ViewRules(filters=[{"op": "eq", "value": 1}]), "筛选规则缺少字段名"),
            (ViewRules(filters=[{"field": "名称", "op": "regex", "value": 1}]), "不支持的过滤操作符"),
            (ViewRules(sortings={}), "sortings 必须是数组"),
            (ViewRules(sortings=["x"]), "每条排序规则必须是对象"),
            (ViewRules(sortings=[{"desc": True}]), "排序规则缺少字段名"),
            (ViewRules(field_options=[]), "field_options 必须是对象"),
            (ViewRules(field_options={"名称": "x"}), "的选项必须是对象"),
            (ViewRules(field_options={"名称": {"order": "一"}}), "order 必须是整数"),
            (ViewRules(view_type="tree"), "未知视图形态"),
            (ViewRules(filter_type="XOR"), "条件组合方式"),
        ]
        for rules, message in cases:
            with pytest.raises(InvalidViewError, match=message):
                normalize_view(table, rules)


class TestCompileFilters:
    """结构化过滤编译（AND/OR）."""

    def _rows(self, table: DataTable, filters: list[dict[str, Any]], match: str) -> list[int]:
        """按结构化规则编译并读取行 id."""
        where, params = query.compile_filters(table, filters, match)
        order = query.compile_sortings(table, [])
        rows = records.fetch_rows(table, query.RowQuery(where=where, params=params, order=order))
        return [row["id"] for row in rows]

    def test_and_match(self, table: DataTable, rows: list[int]) -> None:
        """AND 组合：全部满足."""
        filters = [{"field": "完成", "op": "eq", "value": "true"}, {"field": "金额", "op": "gte", "value": "20"}]
        assert self._rows(table, filters, "AND") == [rows[2]]

    def test_or_match(self, table: DataTable, rows: list[int]) -> None:
        """OR 组合：任一满足."""
        filters = [{"field": "金额", "op": "lt", "value": "15"}, {"field": "完成", "op": "eq", "value": "false"}]
        assert self._rows(table, filters, "OR") == [rows[0], rows[1]]

    def test_compile_sortings(self, table: DataTable, rows: list[int]) -> None:
        """结构化排序：金额降序."""
        order = query.compile_sortings(table, [{"field": "金额", "desc": True}])
        result = records.fetch_rows(table, query.RowQuery(order=order))
        assert [row["id"] for row in result] == [rows[2], rows[1], rows[0]]

    def test_invalid_match_rejected(self, table: DataTable) -> None:
        """非法组合方式拒绝."""
        with pytest.raises(query.InvalidQueryError, match="条件组合"):
            query.compile_filters(table, [{"field": "名称", "op": "eq", "value": "x"}], "XOR")


class TestViewAPI:
    """视图 API."""

    def _url(self, workspace: Workspace, table: DataTable, suffix: str = "") -> str:
        """视图地址."""
        return f"/api/workspaces/{workspace.pk}/tables/{table.pk}/views/{suffix}"

    def test_create_table_creates_default_view(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """建表自动附带默认视图."""
        response = auth_client.get(self._url(workspace, table))
        assert response.status_code == 200
        views = response.data["results"]
        assert isinstance(views, list) and len(views) == 1
        assert views[0]["name"] == "全部"
        assert views[0]["view_type"] == "grid"

    def test_create_view(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """创建带规则的视图，规则归一化返回."""
        response = auth_client.post(
            self._url(workspace, table),
            {
                "name": "大额项目",
                "view_type": "grid",
                "filter_type": "AND",
                "filters": [{"field": "金额", "op": "gte", "value": 20}],
                "sortings": [{"field": "金额", "desc": True}],
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.data["filters"] == [{"field": "金额", "op": "gte", "value": 20}]
        assert response.data["field_options"] == {}

    def test_create_view_invalid_rules_rejected(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """非法规则（未知字段）创建返回 400."""
        response = auth_client.post(
            self._url(workspace, table),
            {"name": "坏视图", "filters": [{"field": "不存在", "op": "eq", "value": 1}]},
            format="json",
        )
        assert response.status_code == 400

    def test_create_view_duplicate_name_rejected(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """同名视图重复创建返回 400 而非 500."""
        response = auth_client.post(self._url(workspace, table), {"name": "全部"}, format="json")
        assert response.status_code == 400
        assert "已存在" in response.data["detail"]

    def test_update_view(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """局部更新视图规则."""
        view = table.views.first()
        assert view is not None
        response = auth_client.patch(
            self._url(workspace, table, f"{view.pk}/"),
            {"filters": [{"field": "完成", "op": "eq", "value": True}]},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["filters"] == [{"field": "完成", "op": "eq", "value": True}]

    def test_update_view_invalid_rules_rejected(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """非法规则更新返回 400 且不落库."""
        view = table.views.first()
        assert view is not None
        response = auth_client.patch(
            self._url(workspace, table, f"{view.pk}/"),
            {"sortings": [{"field": "不存在"}]},
            format="json",
        )
        assert response.status_code == 400
        view.refresh_from_db()
        assert view.sortings == []

    def test_delete_view(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """删除视图返回 204."""
        view = table.views.first()
        assert view is not None
        response = auth_client.delete(self._url(workspace, table, f"{view.pk}/"))
        assert response.status_code == 204
        assert not DataView.objects.filter(pk=view.pk).exists()

    def test_viewer_cannot_create_view(
        self, api: APIClient, viewer: User, workspace: Workspace, table: DataTable
    ) -> None:
        """只读成员建视图返回 403."""
        api.force_authenticate(user=viewer)
        response = api.post(self._url(workspace, table), {"name": "只读视图"}, format="json")
        assert response.status_code == 403


class TestViewRowsAPI:
    """视图行查询 API."""

    def _url(self, workspace: Workspace, table: DataTable, view: DataView) -> str:
        """视图行地址."""
        return f"/api/workspaces/{workspace.pk}/tables/{table.pk}/views/{view.pk}/rows/"

    def _make_view(self, table: DataTable, **kwargs: Any) -> DataView:
        """创建带规则的视图."""
        return DataView.objects.create(table=table, name="查询视图", **kwargs)

    def test_rows_apply_filters_and_sortings(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable, rows: list[int]
    ) -> None:
        """视图行查询应用筛选与排序."""
        view = self._make_view(
            table,
            filters=[{"field": "完成", "op": "eq", "value": True}],
            sortings=[{"field": "金额", "desc": True}],
        )
        response = auth_client.get(self._url(workspace, table, view))
        assert response.status_code == 200
        assert response.data["count"] == 2
        assert [row["id"] for row in response.data["results"]] == [rows[2], rows[0]]

    def test_rows_or_match(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable, rows: list[int]
    ) -> None:
        """OR 组合筛选."""
        view = self._make_view(
            table,
            filter_type="OR",
            filters=[
                {"field": "金额", "op": "lt", "value": 15},
                {"field": "完成", "op": "eq", "value": False},
            ],
        )
        response = auth_client.get(self._url(workspace, table, view))
        assert response.status_code == 200
        assert {row["id"] for row in response.data["results"]} == {rows[0], rows[1]}

    def test_rows_pagination_and_field_options(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable, rows: list[int]
    ) -> None:
        """分页与字段选项一并返回."""
        view = self._make_view(table, field_options={"名称": {"hidden": True, "width": 300}})
        response = auth_client.get(self._url(workspace, table, view), {"page_size": 2})
        assert response.status_code == 200
        assert response.data["count"] == 3
        assert len(response.data["results"]) == 2
        assert response.data["next"] is not None
        assert response.data["field_options"]["名称"] == {"hidden": True, "width": 300, "order": 0}

    def test_rows_value_roundtrip(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable, rows: list[int]
    ) -> None:
        """视图行返回的值与直接读取一致（类型完整往返）."""
        view = self._make_view(table)
        response = auth_client.get(self._url(workspace, table, view))
        assert response.status_code == 200
        assert response.data["results"][0]["金额"] == Decimal("10.5")
        assert response.data["results"][0]["完成"] is True
