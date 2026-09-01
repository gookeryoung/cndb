"""行数据测试：读写往返、校验规则与 API 行为."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from cndb.accounts.models import User
from cndb.tables import query, records, services
from cndb.tables.models import DataTable
from cndb.workspaces.models import Workspace


@pytest.fixture
def table(workspace: Workspace) -> DataTable:
    """含各类字段的测试表."""
    return services.create_table(
        workspace=workspace,
        name="项目表",
        field_defs=[
            {"name": "名称", "field_type": "text", "config": {"max_length": 50}, "required": True},
            {"name": "金额", "field_type": "number", "config": {"precision": 10, "scale": 2}},
            {"name": "完成", "field_type": "boolean"},
            {"name": "截止日", "field_type": "date"},
            {"name": "标签", "field_type": "multi_select", "config": {"choices": ["红", "绿", "蓝"]}},
        ],
    )


ROW = {
    "名称": "项目甲",
    "金额": 12.34,
    "完成": True,
    "截止日": "2026-09-01",
    "标签": ["红", "蓝"],
}


class TestRecordsService:
    """行数据访问层."""

    def test_insert_and_fetch_roundtrip(self, table: DataTable) -> None:
        """插入后读取，各类型值完整往返."""
        row_id = records.insert_row(table, records.clean_row(table, ROW))
        row = records.fetch_row(table, row_id)
        assert row is not None
        assert row["名称"] == "项目甲"
        assert row["金额"] == Decimal("12.34")
        assert row["完成"] is True
        assert row["截止日"] == date(2026, 9, 1)
        assert row["标签"] == ["红", "蓝"]
        assert row["id"] == row_id
        assert "created_on" in row and "updated_on" in row

    def test_fetch_rows_ordered_by_id(self, table: DataTable) -> None:
        """多行按 id 升序返回."""
        for index in range(3):
            records.insert_row(table, records.clean_row(table, {**ROW, "名称": f"行{index}"}))
        rows = records.fetch_rows(table, query.RowQuery())
        assert [row["id"] for row in rows] == sorted(row["id"] for row in rows)
        assert len(rows) == 3

    def test_update_row_partial(self, table: DataTable) -> None:
        """局部更新仅改变指定列并刷新 updated_on."""
        row_id = records.insert_row(table, records.clean_row(table, ROW))
        records.update_row(table, row_id, records.clean_row(table, {"金额": 99.99}, partial=True))
        row = records.fetch_row(table, row_id)
        assert row is not None
        assert row["金额"] == Decimal("99.99")
        assert row["名称"] == "项目甲"

    def test_update_missing_row_returns_false(self, table: DataTable) -> None:
        """更新不存在的行返回 False."""
        cleaned = records.clean_row(table, {"金额": 1}, partial=True)
        assert records.update_row(table, 99999, cleaned) is False

    def test_delete_row(self, table: DataTable) -> None:
        """删除行后不可再读."""
        row_id = records.insert_row(table, records.clean_row(table, ROW))
        assert records.delete_row(table, row_id) is True
        assert records.fetch_row(table, row_id) is None
        assert records.delete_row(table, row_id) is False

    def test_clean_row_unknown_field(self, table: DataTable) -> None:
        """未知字段报错."""
        with pytest.raises(records.InvalidRowError, match="未知字段"):
            records.clean_row(table, {"不存在": 1})

    def test_clean_row_invalid_value(self, table: DataTable) -> None:
        """值校验失败报错并携带字段名."""
        with pytest.raises(records.InvalidRowError, match="名称"):
            records.clean_row(table, {"名称": 123})

    def test_clean_row_required_missing(self, table: DataTable) -> None:
        """必填字段缺失报错."""
        with pytest.raises(records.InvalidRowError, match="必填字段缺失"):
            records.clean_row(table, {"金额": 1})

    def test_clean_row_partial_skips_required(self, table: DataTable) -> None:
        """局部更新允许只出现非必填字段."""
        cleaned = records.clean_row(table, {"金额": 1}, partial=True)
        assert len(cleaned) == 1

    def test_insert_empty_row_into_optional_table(self, workspace: Workspace) -> None:
        """全可选字段的表允许空行创建."""
        table = services.create_table(
            workspace=workspace, name="空值表", field_defs=[{"name": "备注", "field_type": "long_text"}]
        )
        row_id = records.insert_row(table, records.clean_row(table, {}))
        row = records.fetch_row(table, row_id)
        assert row is not None
        assert row["备注"] is None


class TestRecordsAPI:
    """行数据接口."""

    def _url(self, workspace: Workspace, table: DataTable, row_id: int | None = None) -> str:
        """拼行接口地址."""
        base = f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/"
        return base if row_id is None else f"{base}{row_id}/"

    def test_create_and_get_row(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """创建行返回 201 且响应含归一化值，单行读取一致."""
        response = auth_client.post(self._url(workspace, table), ROW, format="json")
        assert response.status_code == 201
        assert response.data["名称"] == "项目甲"
        assert float(response.data["金额"]) == 12.34
        detail = auth_client.get(self._url(workspace, table, response.data["id"]))
        assert detail.status_code == 200
        assert detail.data["标签"] == ["红", "蓝"]

    def test_create_row_invalid_returns_400(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """非法值返回 400."""
        response = auth_client.post(self._url(workspace, table), {"名称": 42}, format="json")
        assert response.status_code == 400

    def test_create_row_unknown_field_returns_400(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """未知字段返回 400."""
        response = auth_client.post(self._url(workspace, table), {"不存在": 1}, format="json")
        assert response.status_code == 400

    def test_list_rows(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """列表返回全部行."""
        records.insert_row(table, records.clean_row(table, ROW))
        response = auth_client.get(self._url(workspace, table))
        assert response.status_code == 200
        assert len(response.data["results"]) == 1

    def test_patch_row(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """局部更新行."""
        row_id = records.insert_row(table, records.clean_row(table, ROW))
        response = auth_client.patch(self._url(workspace, table, row_id), {"金额": 55.5}, format="json")
        assert response.status_code == 200
        assert float(response.data["金额"]) == 55.5

    def test_delete_row(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """删除行返回 204，再读 404."""
        row_id = records.insert_row(table, records.clean_row(table, ROW))
        response = auth_client.delete(self._url(workspace, table, row_id))
        assert response.status_code == 204
        response = auth_client.get(self._url(workspace, table, row_id))
        assert response.status_code == 404

    def test_missing_row_returns_404(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """读取不存在的行返回 404."""
        response = auth_client.get(self._url(workspace, table, 999999))
        assert response.status_code == 404

    def test_viewer_cannot_create_row(
        self, api: APIClient, viewer: User, workspace: Workspace, table: DataTable
    ) -> None:
        """只读成员可读行但不可写行."""
        url = self._url(workspace, table)
        api.force_authenticate(user=viewer)
        assert api.get(url).status_code == 200
        assert api.post(url, ROW, format="json").status_code == 403

    def test_non_json_body_returns_400(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """请求体不是对象返回 400."""
        response = auth_client.post(self._url(workspace, table), [1, 2, 3], format="json")
        assert response.status_code == 400
