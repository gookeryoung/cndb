"""表级权限测试：角色覆盖、行级过滤、字段隐藏与权限配置 API."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from cndb.accounts.models import User
from cndb.tables import services
from cndb.tables.models import DataTable, TablePermission
from cndb.tables.permission_rules import InvalidPermissionError, PermissionRules, normalize_permission
from cndb.workspaces.models import Workspace, WorkspaceMember

pytestmark = pytest.mark.django_db


@pytest.fixture
def table(workspace: Workspace) -> DataTable:
    """测试表：文本字段"标题"与数值字段"薪资"."""
    return services.create_table(
        workspace=workspace,
        name="员工表",
        field_defs=[
            {"name": "标题", "field_type": "text"},
            {"name": "薪资", "field_type": "number"},
        ],
    )


def _member(workspace: Workspace, username: str, role: str) -> User:
    """创建指定角色成员."""
    user = User.objects.create_user(username=username, password="Str0ng-Pass-42")
    WorkspaceMember.objects.create(workspace=workspace, user=user, role=role)
    return user


def _insert_rows(table: DataTable, specs: list[dict[str, Any]]) -> list[int]:
    """直接经服务层插入行，返回 id 列表."""
    from cndb.tables import records

    cleaned = [records.clean_row(table, spec) for spec in specs]
    return records.insert_rows(table, cleaned)


def _perm_payload(**overrides: Any) -> dict[str, Any]:
    """权限配置请求体：默认空覆盖，按用例覆盖字段."""
    payload: dict[str, Any] = {
        "read_role": "",
        "edit_records_role": "",
        "edit_views_role": "",
        "edit_schema_role": "",
        "hidden_fields": {},
        "row_filters": [],
        "row_filter_type": "AND",
    }
    payload.update(overrides)
    return payload


class TestPermissionRules:
    """permission_rules 规则校验."""

    def test_valid_rules_normalized(self, table: DataTable) -> None:
        """合法规则归一化：角色保留、行级过滤结构与视图筛选一致."""
        rules = PermissionRules(
            read_role="editor",
            hidden_fields={"薪资": "admin"},
            row_filters=[{"field": "标题", "op": "contains", "value": "正式"}],
        )
        result = normalize_permission(table, rules)
        assert result["read_role"] == "editor"
        assert result["hidden_fields"] == {"薪资": "admin"}
        assert result["row_filters"] == [{"field": "标题", "op": "contains", "value": "正式"}]

    def test_invalid_role_rejected(self, table: DataTable) -> None:
        """非法角色值拒绝."""
        with pytest.raises(InvalidPermissionError):
            normalize_permission(table, PermissionRules(read_role="root"))

    def test_unknown_hidden_field_rejected(self, table: DataTable) -> None:
        """字段隐藏引用未知字段拒绝."""
        with pytest.raises(InvalidPermissionError):
            normalize_permission(table, PermissionRules(hidden_fields={"不存在": "admin"}))

    def test_bad_row_filters_rejected(self, table: DataTable) -> None:
        """行级过滤结构非法拒绝（未知操作符）."""
        with pytest.raises(InvalidPermissionError):
            normalize_permission(
                table,
                PermissionRules(row_filters=[{"field": "标题", "op": "bad_op", "value": "x"}]),
            )

    def test_bad_filter_type_rejected(self, table: DataTable) -> None:
        """非法条件组合方式拒绝."""
        with pytest.raises(InvalidPermissionError):
            normalize_permission(
                table,
                PermissionRules(row_filters=[{"field": "标题", "op": "eq", "value": "x"}], row_filter_type="XOR"),
            )


class TestRoleOverride:
    """表级角色覆盖：动作收紧后低角色拒绝，OWNER 豁免."""

    def test_edit_records_tightened(self, api: APIClient, workspace: Workspace, table: DataTable, user: User) -> None:
        """编辑行收紧到 admin：editor 写行 403，owner 仍可."""
        TablePermission.objects.create(table=table, edit_records_role="admin")
        editor = _member(workspace, "editor1", WorkspaceMember.Role.EDITOR)
        api.force_login(editor)
        response = api.post(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/",
            {"标题": "x"},
            format="json",
        )
        assert response.status_code == 403
        api.force_login(user)
        assert (
            api.post(
                f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/",
                {"标题": "y"},
                format="json",
            ).status_code
            == 201
        )

    def test_read_tightened(self, api: APIClient, workspace: Workspace, table: DataTable) -> None:
        """读取收紧到 editor：viewer 读行 403，editor 正常."""
        TablePermission.objects.create(table=table, read_role="editor")
        viewer = _member(workspace, "viewer1", WorkspaceMember.Role.VIEWER)
        api.force_login(viewer)
        url = f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/"
        assert api.get(url).status_code == 403
        editor = _member(workspace, "editor2", WorkspaceMember.Role.EDITOR)
        api.force_login(editor)
        assert api.get(url).status_code == 200

    def test_owner_exempt_from_override(
        self, api: APIClient, workspace: Workspace, table: DataTable, user: User
    ) -> None:
        """OWNER 豁免表级覆盖：读取收紧到 admin 后 owner 仍可读."""
        TablePermission.objects.create(table=table, read_role="admin")
        api.force_login(user)
        url = f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/"
        assert api.get(url).status_code == 200

    def test_uncovered_actions_unchanged(self, api: APIClient, workspace: Workspace, table: DataTable) -> None:
        """未覆盖动作回落默认：收紧 edit_records 不影响建视图."""
        TablePermission.objects.create(table=table, edit_records_role="admin")
        editor = _member(workspace, "editor3", WorkspaceMember.Role.EDITOR)
        api.force_login(editor)
        response = api.post(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/views/",
            {"name": "我的视图"},
            format="json",
        )
        assert response.status_code == 201


class TestRowScope:
    """行级过滤：读取只见范围内行，编辑范围外行 404，OWNER 全量."""

    def test_read_scoped(self, api: APIClient, workspace: Workspace, table: DataTable) -> None:
        """行级过滤后成员列表只含满足条件的行."""
        _insert_rows(table, [{"标题": "正式-张三"}, {"标题": "试用-李四"}, {"标题": "正式-王五"}])
        TablePermission.objects.create(
            table=table,
            row_filters=[{"field": "标题", "op": "contains", "value": "正式"}],
        )
        editor = _member(workspace, "editor4", WorkspaceMember.Role.EDITOR)
        api.force_login(editor)
        response = api.get(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/")
        assert response.status_code == 200
        titles = [row["标题"] for row in response.data["results"]]
        assert titles == ["正式-张三", "正式-王五"]

    def test_update_outside_scope_404(self, api: APIClient, workspace: Workspace, table: DataTable) -> None:
        """编辑范围外的行返回 404（存在但不可见）."""
        row_ids = _insert_rows(table, [{"标题": "正式-张三"}, {"标题": "试用-李四"}])
        TablePermission.objects.create(
            table=table,
            row_filters=[{"field": "标题", "op": "contains", "value": "正式"}],
        )
        editor = _member(workspace, "editor5", WorkspaceMember.Role.EDITOR)
        api.force_login(editor)
        response = api.patch(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/{row_ids[1]}/",
            {"标题": "改名"},
            format="json",
        )
        assert response.status_code == 404

    def test_owner_sees_all_rows(self, api: APIClient, workspace: Workspace, table: DataTable, user: User) -> None:
        """OWNER 不受行级过滤限制."""
        _insert_rows(table, [{"标题": "正式-张三"}, {"标题": "试用-李四"}])
        TablePermission.objects.create(
            table=table,
            row_filters=[{"field": "标题", "op": "contains", "value": "正式"}],
        )
        api.force_login(user)
        response = api.get(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/")
        assert response.data["count"] == 2

    def test_bulk_delete_scoped(self, api: APIClient, workspace: Workspace, table: DataTable) -> None:
        """批量删除只删范围内的行."""
        row_ids = _insert_rows(table, [{"标题": "正式-张三"}, {"标题": "试用-李四"}])
        TablePermission.objects.create(
            table=table,
            row_filters=[{"field": "标题", "op": "contains", "value": "正式"}],
        )
        editor = _member(workspace, "editor6", WorkspaceMember.Role.EDITOR)
        api.force_login(editor)
        response = api.delete(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/bulk/",
            {"ids": row_ids},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["deleted"] == 1


class TestHiddenFields:
    """字段级隐藏：低角色响应剔除字段，聚合隐藏字段 400."""

    def test_hidden_for_viewer(self, api: APIClient, workspace: Workspace, table: DataTable) -> None:
        """薪资字段设为 admin 可见：viewer 响应不含该键，admin 可见."""
        _insert_rows(table, [{"标题": "张三", "薪资": 100}])
        TablePermission.objects.create(table=table, hidden_fields={"薪资": "admin"})
        viewer = _member(workspace, "viewer2", WorkspaceMember.Role.VIEWER)
        api.force_login(viewer)
        response = api.get(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/")
        assert "薪资" not in response.data["results"][0]
        admin = _member(workspace, "admin1", WorkspaceMember.Role.ADMIN)
        api.force_login(admin)
        response = api.get(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/")
        assert "薪资" in response.data["results"][0]

    def test_aggregation_on_hidden_field_rejected(self, api: APIClient, workspace: Workspace, table: DataTable) -> None:
        """聚合隐藏字段返回 400."""
        from cndb.tables.models import DataView

        view = DataView.objects.create(table=table, name="权限视图")
        TablePermission.objects.create(table=table, hidden_fields={"薪资": "admin"})
        editor = _member(workspace, "editor8", WorkspaceMember.Role.EDITOR)
        api.force_login(editor)
        url = f"/api/workspaces/{workspace.pk}/tables/{table.pk}/views/{view.pk}/aggregations/?agg__薪资=sum"
        assert api.get(url).status_code == 400


class TestPermissionAPI:
    """表级权限配置 API：默认读取、配置写入与恢复默认."""

    def test_get_default(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """未配置时 GET 返回空覆盖默认结构."""
        response = auth_client.get(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/permission/")
        assert response.status_code == 200
        assert response.data["read_role"] == ""
        assert response.data["row_filters"] == []

    def test_put_then_effect(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """PUT 配置生效：读取收紧后 viewer 403."""
        response = auth_client.put(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/permission/",
            _perm_payload(read_role="editor"),
            format="json",
        )
        assert response.status_code == 200
        assert TablePermission.objects.filter(table=table).exists()
        viewer = _member(workspace, "viewer3", WorkspaceMember.Role.VIEWER)
        # force_authenticate 的凭证会驻留客户端，须再次调用覆盖为 viewer 身份
        auth_client.force_authenticate(user=viewer)
        assert auth_client.get(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/").status_code == 403

    def test_put_invalid_rejected(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """非法规则 PUT 返回 400 且不落库."""
        response = auth_client.put(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/permission/",
            _perm_payload(read_role="root"),
            format="json",
        )
        assert response.status_code == 400
        assert not TablePermission.objects.filter(table=table).exists()

    def test_editor_cannot_configure(self, api: APIClient, workspace: Workspace, table: DataTable) -> None:
        """EDITOR 配置权限返回 403（要求 ADMIN 及以上）."""
        editor = _member(workspace, "editor9", WorkspaceMember.Role.EDITOR)
        api.force_login(editor)
        response = api.put(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/permission/",
            _perm_payload(),
            format="json",
        )
        assert response.status_code == 403

    def test_delete_restores_default(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """DELETE 删除权限对象恢复默认：viewer 恢复可读."""
        TablePermission.objects.create(table=table, read_role="editor")
        response = auth_client.delete(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/permission/")
        assert response.status_code == 204
        assert not TablePermission.objects.filter(table=table).exists()
        viewer = _member(workspace, "viewer4", WorkspaceMember.Role.VIEWER)
        # force_authenticate 的凭证会驻留客户端，须再次调用覆盖为 viewer 身份
        auth_client.force_authenticate(user=viewer)
        assert auth_client.get(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/records/").status_code == 200
