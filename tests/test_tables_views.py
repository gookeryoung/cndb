"""数据表 API 测试：建表/改表/删表与字段管理的接口行为."""

from __future__ import annotations

from typing import Any

from django.db import connection
from rest_framework.test import APIClient

from cndb.accounts.models import User
from cndb.tables.models import DataTable
from cndb.workspaces.models import Workspace, WorkspaceMember


def _table_columns(table_name: object) -> list[str]:
    """返回物理表的列名列表."""
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, str(table_name))
    return [column.name for column in description]


CREATE_PAYLOAD = {
    "name": "项目表",
    "fields": [
        {"name": "名称", "field_type": "text", "config": {"max_length": 100}, "required": True},
        {"name": "金额", "field_type": "number", "config": {"precision": 10, "scale": 2}},
    ],
}


def _create_table(api: APIClient, workspace: Workspace) -> dict[str, Any]:
    """通过 API 建表并返回响应数据."""
    response = api.post(f"/api/workspaces/{workspace.pk}/tables/", CREATE_PAYLOAD, format="json")
    assert response.status_code == 201
    return response.data  # type: ignore[no-any-return]


class TestTableAPI:
    """表级接口."""

    def test_create_table(self, auth_client: APIClient, workspace: Workspace) -> None:
        """建表返回 201，响应含字段元数据与物理列名，物理表真实存在."""
        data = _create_table(auth_client, workspace)
        assert data["name"] == "项目表"
        assert len(data["fields"]) == 2
        assert data["fields"][0]["db_column_name"].startswith("field_")
        table = DataTable.objects.get(pk=data["id"])
        with connection.cursor() as cursor:
            assert table.db_table_name in connection.introspection.table_names(cursor)

    def test_create_table_invalid_field_type(self, auth_client: APIClient, workspace: Workspace) -> None:
        """未注册字段类型返回 400，且不产生元数据."""
        payload = {"name": "坏表", "fields": [{"name": "坏", "field_type": "no_such"}]}
        response = auth_client.post(f"/api/workspaces/{workspace.pk}/tables/", payload, format="json")
        assert response.status_code == 400
        assert not DataTable.objects.filter(name="坏表").exists()

    def test_create_table_requires_editor(self, api: APIClient, viewer: User, workspace: Workspace) -> None:
        """只读成员建表返回 403."""
        api.force_authenticate(user=viewer)
        response = api.post(f"/api/workspaces/{workspace.pk}/tables/", CREATE_PAYLOAD, format="json")
        assert response.status_code == 403

    def test_non_member_cannot_list(self, auth_client: APIClient, workspace: Workspace, user: User) -> None:
        """非成员访问返回 403."""
        WorkspaceMember.objects.filter(workspace=workspace, user=user).delete()
        response = auth_client.get(f"/api/workspaces/{workspace.pk}/tables/")
        assert response.status_code == 403

    def test_list_tables(self, auth_client: APIClient, workspace: Workspace) -> None:
        """列表返回当前工作区的表与内嵌字段."""
        _create_table(auth_client, workspace)
        response = auth_client.get(f"/api/workspaces/{workspace.pk}/tables/")
        assert response.status_code == 200
        results = response.data["results"]  # type: ignore[index]
        assert len(results) == 1
        assert len(results[0]["fields"]) == 2

    def test_rename_table(self, auth_client: APIClient, workspace: Workspace) -> None:
        """改表名仅动元数据，物理表不变."""
        data = _create_table(auth_client, workspace)
        table = DataTable.objects.get(pk=data["id"])
        physical = table.db_table_name
        response = auth_client.patch(
            f"/api/workspaces/{workspace.pk}/tables/{data['id']}/", {"name": "新表名"}, format="json"
        )
        assert response.status_code == 200
        table.refresh_from_db()
        assert table.name == "新表名"
        assert table.db_table_name == physical

    def test_delete_table(self, auth_client: APIClient, workspace: Workspace) -> None:
        """删表后元数据与物理表均消失."""
        data = _create_table(auth_client, workspace)
        table = DataTable.objects.get(pk=data["id"])
        response = auth_client.delete(f"/api/workspaces/{workspace.pk}/tables/{data['id']}/")
        assert response.status_code == 204
        assert not DataTable.objects.filter(pk=data["id"]).exists()
        with connection.cursor() as cursor:
            assert table.db_table_name not in connection.introspection.table_names(cursor)


class TestFieldAPI:
    """字段级接口."""

    def test_add_field(self, auth_client: APIClient, workspace: Workspace) -> None:
        """加字段后物理表出现对应列."""
        table = _create_table(auth_client, workspace)
        payload = {"name": "备注", "field_type": "long_text"}
        response = auth_client.post(
            f"/api/workspaces/{workspace.pk}/tables/{table['id']}/fields/", payload, format="json"
        )
        assert response.status_code == 201
        assert response.data["db_column_name"] in _table_columns(DataTable.objects.get(pk=table["id"]).db_table_name)

    def test_update_field_config_applies_ddl(self, auth_client: APIClient, workspace: Workspace) -> None:
        """改字段配置（max_length）后物理列类型同步变化."""
        table = _create_table(auth_client, workspace)
        field = DataTable.objects.get(pk=table["id"]).fields.get(name="名称")
        response = auth_client.patch(
            f"/api/workspaces/{workspace.pk}/tables/{table['id']}/fields/{field.pk}/",
            {"config": {"max_length": 50}},
            format="json",
        )
        assert response.status_code == 200
        field.refresh_from_db()
        assert field.config == {"max_length": 50}
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=%s",
                [field.table.db_table_name],
            )
            create_sql = cursor.fetchone()[0]
        assert "varchar(50)" in create_sql

    def test_update_field_invalid_config_returns_400(self, auth_client: APIClient, workspace: Workspace) -> None:
        """非法配置返回 400."""
        table = _create_table(auth_client, workspace)
        field = DataTable.objects.get(pk=table["id"]).fields.get(name="名称")
        response = auth_client.patch(
            f"/api/workspaces/{workspace.pk}/tables/{table['id']}/fields/{field.pk}/",
            {"config": {"max_length": "很多"}},
            format="json",
        )
        assert response.status_code == 400

    def test_delete_field(self, auth_client: APIClient, workspace: Workspace) -> None:
        """删字段后物理列与元数据均消失."""
        table = _create_table(auth_client, workspace)
        field = DataTable.objects.get(pk=table["id"]).fields.get(name="金额")
        response = auth_client.delete(f"/api/workspaces/{workspace.pk}/tables/{table['id']}/fields/{field.pk}/")
        assert response.status_code == 204
        columns = _table_columns(field.table.db_table_name)
        assert field.db_column_name not in columns
        assert len([c for c in columns if c.startswith("field_")]) == 1

    def test_viewer_cannot_modify_field(
        self, api: APIClient, viewer: User, auth_client: APIClient, workspace: Workspace
    ) -> None:
        """只读成员改字段返回 403，但可查看字段列表."""
        table = _create_table(auth_client, workspace)
        field = DataTable.objects.get(pk=table["id"]).fields.get(name="名称")
        api.force_authenticate(user=viewer)
        list_response = api.get(f"/api/workspaces/{workspace.pk}/tables/{table['id']}/fields/")
        assert list_response.status_code == 200
        patch_response = api.patch(
            f"/api/workspaces/{workspace.pk}/tables/{table['id']}/fields/{field.pk}/",
            {"name": "改名"},
            format="json",
        )
        assert patch_response.status_code == 403
