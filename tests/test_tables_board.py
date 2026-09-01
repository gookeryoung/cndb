"""看板/日历视图测试：分组读行与日期范围过滤."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from rest_framework.test import APIClient

from cndb.tables import records as table_records
from cndb.tables import services
from cndb.tables.models import DataTable, DataView, TablePermission
from cndb.workspaces.models import Workspace


@pytest.fixture
def table(workspace: Workspace) -> DataTable:
    """带状态/截止日期/标题字段的看板日历测试表."""
    return services.create_table(
        workspace=workspace,  # type: ignore[arg-type]
        name="看板表",
        field_defs=[
            {"name": "标题", "field_type": "text"},
            {"name": "状态", "field_type": "single_select", "config": {"choices": ["待办", "进行中", "完成"]}},
            {"name": "截止", "field_type": "date"},
        ],
    )


def _insert(table: DataTable, rows: list[dict[str, Any]]) -> list[int]:
    """校验并插入行，返回主键列表."""
    cleaned = [table_records.clean_row(table, row, partial=True) for row in rows]
    return table_records.insert_rows(table, cleaned)


def _view_url(workspace: Workspace, table: DataTable, view: DataView, suffix: str) -> str:
    """构造视图端点地址."""
    return f"/api/workspaces/{workspace.pk}/tables/{table.pk}/views/{view.pk}/{suffix}/"


class TestKanban:
    """看板：按单选字段分桶，选项顺序输出，空值入未分组桶."""

    def test_groups_by_choices(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """按选项顺序返回分组，每桶含 count 与行."""
        _insert(
            table,
            [
                {"标题": "甲", "状态": "待办"},
                {"标题": "乙", "状态": "完成"},
                {"标题": "丙", "状态": "待办"},
            ],
        )
        view = DataView.objects.create(table=table, name="看板")
        response = auth_client.get(_view_url(workspace, table, view, "kanban"), {"group_by": "状态"})
        assert response.status_code == 200
        groups = response.data["groups"]
        assert [group["value"] for group in groups] == ["待办", "进行中", "完成"]
        assert [group["count"] for group in groups] == [2, 0, 1]
        assert [row["标题"] for row in groups[0]["rows"]] == ["甲", "丙"]
        assert response.data["ungrouped"]["count"] == 0

    def test_ungrouped_bucket(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """空值与越界值行入未分组桶."""
        _insert(table, [{"标题": "无状态", "状态": None}])
        view = DataView.objects.create(table=table, name="看板2")
        response = auth_client.get(_view_url(workspace, table, view, "kanban"), {"group_by": "状态"})
        assert response.status_code == 200
        assert all(group["count"] == 0 for group in response.data["groups"])
        assert response.data["ungrouped"]["count"] == 1
        assert response.data["ungrouped"]["rows"][0]["标题"] == "无状态"

    def test_per_group_limit(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """per_group 截断每桶行数但 count 保留全量."""
        _insert(table, [{"标题": f"任务{i}", "状态": "待办"} for i in range(3)])
        view = DataView.objects.create(table=table, name="看板3")
        response = auth_client.get(_view_url(workspace, table, view, "kanban"), {"group_by": "状态", "per_group": 2})
        assert response.status_code == 200
        group = response.data["groups"][0]
        assert group["count"] == 3
        assert len(group["rows"]) == 2

    def test_view_filters_applied(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """视图筛选规则对看板生效."""
        _insert(
            table,
            [
                {"标题": "正式-甲", "状态": "待办"},
                {"标题": "试用-乙", "状态": "待办"},
            ],
        )
        view = DataView.objects.create(
            table=table, name="看板4", filters=[{"field": "标题", "op": "contains", "value": "正式"}]
        )
        response = auth_client.get(_view_url(workspace, table, view, "kanban"), {"group_by": "状态"})
        assert response.status_code == 200
        assert response.data["groups"][0]["count"] == 1

    def test_invalid_group_field(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """group_by 非单选字段或缺失返回 400."""
        view = DataView.objects.create(table=table, name="看板5")
        base = _view_url(workspace, table, view, "kanban")
        assert auth_client.get(base).status_code == 400
        assert auth_client.get(base, {"group_by": "标题"}).status_code == 400
        assert auth_client.get(base, {"group_by": "不存在"}).status_code == 400

    def test_hidden_group_field_rejected(self, api: APIClient, workspace: Workspace, table: DataTable) -> None:
        """分组字段对低角色隐藏时返回 400."""
        from cndb.accounts.models import User
        from cndb.workspaces.models import WorkspaceMember

        TablePermission.objects.create(table=table, hidden_fields={"状态": "admin"})
        editor = User.objects.create_user(username="board-editor", password="Str0ng-Pass-42")
        WorkspaceMember.objects.create(workspace=workspace, user=editor, role=WorkspaceMember.Role.EDITOR)
        api.force_authenticate(user=editor)
        view = DataView.objects.create(table=table, name="看板6")
        response = api.get(_view_url(workspace, table, view, "kanban"), {"group_by": "状态"})
        assert response.status_code == 400
        assert "不可见" in response.data["detail"]


class TestCalendar:
    """日历：按 date 字段范围过滤，闭区间，start/end 均可选."""

    def test_range_filter(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """start/end 闭区间过滤."""
        _insert(
            table,
            [
                {"标题": "早", "截止": date(2026, 8, 15)},
                {"标题": "中", "截止": date(2026, 9, 1)},
                {"标题": "晚", "截止": date(2026, 10, 1)},
            ],
        )
        view = DataView.objects.create(table=table, name="日历")
        response = auth_client.get(
            _view_url(workspace, table, view, "calendar"),
            {"date_field": "截止", "start": "2026-09-01", "end": "2026-09-30"},
        )
        assert response.status_code == 200
        assert response.data["date_field"] == "截止"
        assert [row["标题"] for row in response.data["results"]] == ["中"]

    def test_open_ended(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """仅 start 或仅 end 时另一端不限."""
        _insert(
            table,
            [
                {"标题": "早", "截止": date(2026, 8, 15)},
                {"标题": "晚", "截止": date(2026, 10, 1)},
            ],
        )
        view = DataView.objects.create(table=table, name="日历2")
        base = _view_url(workspace, table, view, "calendar")
        response = auth_client.get(base, {"date_field": "截止", "start": "2026-09-01"})
        assert response.status_code == 200
        assert [row["标题"] for row in response.data["results"]] == ["晚"]
        response = auth_client.get(base, {"date_field": "截止", "end": "2026-09-01"})
        assert response.status_code == 200
        assert [row["标题"] for row in response.data["results"]] == ["早"]

    def test_null_date_excluded_when_start(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """空日期行不落入任何范围."""
        _insert(table, [{"标题": "无日期", "截止": None}])
        view = DataView.objects.create(table=table, name="日历3")
        response = auth_client.get(
            _view_url(workspace, table, view, "calendar"), {"date_field": "截止", "start": "2000-01-01"}
        )
        assert response.status_code == 200
        assert response.data["results"] == []

    def test_invalid_params(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """date_field 缺失/非 date 类型/坏日期格式返回 400."""
        view = DataView.objects.create(table=table, name="日历4")
        base = _view_url(workspace, table, view, "calendar")
        assert auth_client.get(base).status_code == 400
        assert auth_client.get(base, {"date_field": "标题"}).status_code == 400
        assert auth_client.get(base, {"date_field": "截止", "start": "不是日期"}).status_code == 400

    def test_row_scope_applied(self, api: APIClient, workspace: Workspace, table: DataTable) -> None:
        """行级范围对日历生效：低角色仅见范围内行."""
        from cndb.accounts.models import User
        from cndb.workspaces.models import WorkspaceMember

        _insert(
            table,
            [
                {"标题": "正式-甲", "截止": date(2026, 9, 1)},
                {"标题": "试用-乙", "截止": date(2026, 9, 2)},
            ],
        )
        TablePermission.objects.create(table=table, row_filters=[{"field": "标题", "op": "contains", "value": "正式"}])
        editor = User.objects.create_user(username="cal-editor", password="Str0ng-Pass-42")
        WorkspaceMember.objects.create(workspace=workspace, user=editor, role=WorkspaceMember.Role.EDITOR)
        api.force_authenticate(user=editor)
        view = DataView.objects.create(table=table, name="日历5")
        response = api.get(_view_url(workspace, table, view, "calendar"), {"date_field": "截止"})
        assert response.status_code == 200
        assert [row["标题"] for row in response.data["results"]] == ["正式-甲"]
