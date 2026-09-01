"""批量操作测试：批量创建/更新/删除的服务层与接口行为."""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from cndb.accounts.models import User
from cndb.tables import query, records, services
from cndb.tables.models import DataTable
from cndb.workspaces.models import Workspace


@pytest.fixture
def table(workspace: Workspace) -> DataTable:
    """含必填文本与数值字段的测试表."""
    return services.create_table(
        workspace=workspace,
        name="库存表",
        field_defs=[
            {"name": "品名", "field_type": "text", "required": True},
            {"name": "数量", "field_type": "number", "config": {"precision": 10, "scale": 0}},
        ],
    )


class TestInsertRows:
    """批量插入（服务层）."""

    def test_mixed_columns_roundtrip(self, table: DataTable) -> None:
        """各行列集合不同：取并集，缺失列为 NULL."""
        cleaned = [
            records.clean_row(table, {"品名": "苹果", "数量": 10}),
            records.clean_row(table, {"品名": "梨"}),
        ]
        row_ids = records.insert_rows(table, cleaned)
        assert len(row_ids) == 2
        rows = records.fetch_rows_by_ids(table, row_ids)
        assert rows[0]["品名"] == "苹果"
        assert rows[0]["数量"] == Decimal("10")
        assert rows[1]["品名"] == "梨"
        assert rows[1]["数量"] is None

    def test_empty_input(self, table: DataTable) -> None:
        """空列表直接返回空."""
        assert records.insert_rows(table, []) == []

    def test_all_default_rows(self, table: DataTable) -> None:
        """全空行（无必填字段场景由 clean 保证可入库）退化为默认值插入.

        本表品名必填，此处直接构造已清洗的空行验证退化路径。
        """
        row_ids = records.insert_rows(table, [{}, {}])
        assert len(row_ids) == 2


class TestUpdateRows:
    """批量更新（服务层）."""

    def test_update_multiple(self, table: DataTable) -> None:
        """批量更新命中全部行."""
        ids = [
            records.insert_row(table, records.clean_row(table, {"品名": "甲", "数量": 1})),
            records.insert_row(table, records.clean_row(table, {"品名": "乙", "数量": 2})),
        ]
        updates = {row_id: records.clean_row(table, {"数量": 99}, partial=True) for row_id in ids}
        assert records.update_rows(table, updates) == 2
        rows = records.fetch_rows_by_ids(table, ids)
        assert all(row["数量"] == Decimal("99") for row in rows)

    def test_missing_id_counts_as_miss(self, table: DataTable) -> None:
        """不存在的 id 计入未命中，不影响其余行."""
        row_id = records.insert_row(table, records.clean_row(table, {"品名": "甲"}))
        updates = {
            row_id: records.clean_row(table, {"数量": 5}, partial=True),
            99999: records.clean_row(table, {"数量": 6}, partial=True),
        }
        assert records.update_rows(table, updates) == 1
        row = records.fetch_row(table, row_id)
        assert row is not None
        assert row["数量"] == Decimal("5")


class TestDeleteRows:
    """批量删除（服务层）."""

    def test_delete_and_dedupe(self, table: DataTable) -> None:
        """IN 删除并对重复 id 去重."""
        ids = [
            records.insert_row(table, records.clean_row(table, {"品名": "甲"})),
            records.insert_row(table, records.clean_row(table, {"品名": "乙"})),
        ]
        assert records.delete_rows(table, [*ids, ids[0]]) == 2
        assert records.count_rows(table, query.RowQuery()) == 0

    def test_empty_ids(self, table: DataTable) -> None:
        """空列表返回 0."""
        assert records.delete_rows(table, []) == 0


class TestFetchRowsByIds:
    """按主键集合读取."""

    def test_order_and_skip_missing(self, table: DataTable) -> None:
        """按传入顺序返回，不存在的主键跳过."""
        ids = [
            records.insert_row(table, records.clean_row(table, {"品名": "甲"})),
            records.insert_row(table, records.clean_row(table, {"品名": "乙"})),
        ]
        rows = records.fetch_rows_by_ids(table, [ids[1], 99999, ids[0]])
        assert [row["id"] for row in rows] == [ids[1], ids[0]]

    def test_empty_ids(self, table: DataTable) -> None:
        """空列表返回空."""
        assert records.fetch_rows_by_ids(table, []) == []


class TestBulkAPI:
    """批量接口."""

    def _url(self, workspace: Workspace, table: DataTable) -> str:
        """批量操作地址."""
        return f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/bulk/"

    def test_bulk_create(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """批量创建返回按提交顺序的完整行."""
        response = auth_client.post(
            self._url(workspace, table),
            [{"品名": "苹果", "数量": 10}, {"品名": "梨"}],
            format="json",
        )
        assert response.status_code == 201
        rows = response.data
        assert isinstance(rows, list) and len(rows) == 2
        assert rows[0]["品名"] == "苹果"
        assert rows[1]["数量"] is None

    def test_bulk_create_invalid_row_rejected_wholly(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """任一行非法则整批拒绝（含必填缺失）."""
        response = auth_client.post(
            self._url(workspace, table),
            [{"品名": "苹果"}, {"数量": 5}],
            format="json",
        )
        assert response.status_code == 400
        assert records.count_rows(table, query.RowQuery()) == 0

    def test_bulk_create_non_array_rejected(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """请求体非数组或空数组返回 400."""
        response = auth_client.post(self._url(workspace, table), {"品名": "苹果"}, format="json")
        assert response.status_code == 400
        response = auth_client.post(self._url(workspace, table), [], format="json")
        assert response.status_code == 400

    def test_bulk_create_over_limit_rejected(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """超过单批上限返回 400."""
        payload = [{"品名": f"品{i}"} for i in range(201)]
        response = auth_client.post(self._url(workspace, table), payload, format="json")
        assert response.status_code == 400

    def test_bulk_update(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """批量局部更新返回更新后的行."""
        ids = [
            records.insert_row(table, records.clean_row(table, {"品名": "甲", "数量": 1})),
            records.insert_row(table, records.clean_row(table, {"品名": "乙", "数量": 2})),
        ]
        response = auth_client.patch(
            self._url(workspace, table),
            [{"id": ids[0], "数量": 50}, {"id": ids[1], "品名": "乙改"}],
            format="json",
        )
        assert response.status_code == 200
        assert response.data[0]["数量"] == Decimal("50")
        assert response.data[1]["品名"] == "乙改"

    def test_bulk_update_duplicate_id_rejected(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """重复 id 返回 400."""
        row_id = records.insert_row(table, records.clean_row(table, {"品名": "甲"}))
        response = auth_client.patch(
            self._url(workspace, table),
            [{"id": row_id, "数量": 1}, {"id": row_id, "数量": 2}],
            format="json",
        )
        assert response.status_code == 400

    def test_bulk_update_missing_id_rejected(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """元素缺整数 id 返回 400."""
        response = auth_client.patch(self._url(workspace, table), [{"品名": "甲"}], format="json")
        assert response.status_code == 400

    def test_bulk_update_partial_missing_returns_404(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """部分行不存在返回 404 且已存在的行未被改动."""
        row_id = records.insert_row(table, records.clean_row(table, {"品名": "甲", "数量": 1}))
        response = auth_client.patch(
            self._url(workspace, table),
            [{"id": row_id, "数量": 99}, {"id": 88888, "数量": 1}],
            format="json",
        )
        assert response.status_code == 404
        row = records.fetch_row(table, row_id)
        assert row is not None
        assert row["数量"] == Decimal("1")

    def test_bulk_delete(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """批量删除返回删除行数."""
        ids = [
            records.insert_row(table, records.clean_row(table, {"品名": "甲"})),
            records.insert_row(table, records.clean_row(table, {"品名": "乙"})),
            records.insert_row(table, records.clean_row(table, {"品名": "丙"})),
        ]
        response = auth_client.delete(self._url(workspace, table), {"ids": ids[:2]}, format="json")
        assert response.status_code == 200
        assert response.data["deleted"] == 2
        assert records.count_rows(table, query.RowQuery()) == 1

    def test_bulk_delete_invalid_ids_rejected(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """ids 非法（非数组/空/非整数）返回 400."""
        url = self._url(workspace, table)
        assert auth_client.delete(url, {"ids": "1,2"}, format="json").status_code == 400
        assert auth_client.delete(url, {"ids": []}, format="json").status_code == 400
        assert auth_client.delete(url, {"ids": ["a"]}, format="json").status_code == 400
        assert auth_client.delete(url, [1, 2], format="json").status_code == 400

    def test_viewer_cannot_bulk_create(
        self, api: APIClient, viewer: User, workspace: Workspace, table: DataTable
    ) -> None:
        """只读成员批量写操作返回 403."""
        api.force_authenticate(user=viewer)
        response = api.post(self._url(workspace, table), [{"品名": "甲"}], format="json")
        assert response.status_code == 403

    def test_viewer_cannot_bulk_delete(
        self, api: APIClient, viewer: User, workspace: Workspace, table: DataTable
    ) -> None:
        """只读成员批量删除返回 403."""
        api.force_authenticate(user=viewer)
        response = api.delete(self._url(workspace, table), {"ids": [1]}, format="json")
        assert response.status_code == 403
