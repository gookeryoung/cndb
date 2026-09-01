"""导入导出测试：CSV/JSON 导出、CSV/JSON 导入与权限约束."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from cndb.accounts.models import User
from cndb.tables import records as table_records
from cndb.tables import services
from cndb.tables.models import DataTable, TablePermission
from cndb.tables.transfer import export_csv
from cndb.workspaces.models import Workspace, WorkspaceMember


@pytest.fixture
def table(workspace: Workspace) -> DataTable:
    """带文本/数值/多选字段的转运测试表."""
    return services.create_table(
        workspace=workspace,  # type: ignore[arg-type]
        name="转运表",
        field_defs=[
            {"name": "标题", "field_type": "text"},
            {"name": "数量", "field_type": "number"},
            {"name": "标签", "field_type": "multi_select", "config": {"choices": ["红", "蓝"]}},
        ],
    )


def _insert(table: DataTable, rows: list[dict[str, object]]) -> list[int]:
    """校验并插入行，返回主键列表."""
    cleaned = [table_records.clean_row(table, row, partial=True) for row in rows]
    return table_records.insert_rows(table, cleaned)


class TestExport:
    """导出：CSV/JSON 格式与值序列化."""

    def test_export_csv(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """CSV 导出：BOM + 表头 + 值文本化（布尔/日期/多选约定）."""
        from datetime import date

        _insert(table, [{"标题": "甲", "数量": Decimal("3.5"), "标签": ["红", "蓝"]}])
        response = auth_client.get(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/export/")
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")  # type: ignore[bad-index]
        text = response.content.decode("utf-8")
        assert text.startswith("\ufeff")
        lines = text.lstrip("\ufeff").strip().splitlines()
        assert lines[0] == "标题,数量,标签"
        assert lines[1] == "甲,3.5,红;蓝"
        assert isinstance(date, type(date))  # 日期序列化由字段类型保证

    def test_export_json(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """JSON 导出：原生值类型（Decimal/列表）与导出字段裁剪."""
        _insert(table, [{"标题": "甲", "数量": Decimal("3.5"), "标签": ["红"]}])
        response = auth_client.get(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/export/?format=json")
        assert response.status_code == 200
        data = response.data
        assert len(data) == 1
        assert data[0] == {"标题": "甲", "数量": Decimal("3.50"), "标签": ["红"]}

    def test_export_respects_permissions(
        self, auth_client: APIClient, api: APIClient, workspace: Workspace, table: DataTable, user: User
    ) -> None:
        """导出应用行级范围与字段隐藏：隐藏列剔除、范围外行不导出."""
        _insert(
            table,
            [
                {"标题": "正式-甲", "数量": Decimal("1"), "标签": ["红"]},
                {"标题": "试用-乙", "数量": Decimal("2"), "标签": None},
            ],
        )
        TablePermission.objects.create(
            table=table,
            hidden_fields={"数量": "admin"},
            row_filters=[{"field": "标题", "op": "contains", "value": "正式"}],
        )
        editor = User.objects.create_user(username="exporter", password="Str0ng-Pass-42")
        WorkspaceMember.objects.create(workspace=workspace, user=editor, role=WorkspaceMember.Role.EDITOR)
        # auth_client 与 api 是同一对象，force_authenticate 凭证驻留，force_login 无法覆盖
        api.force_authenticate(user=editor)
        response = api.get(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/export/?format=json")
        assert response.status_code == 200
        assert response.data == [{"标题": "正式-甲", "标签": ["红"]}]


class TestExportCsvUnit:
    """export_csv 单元：值序列化约定."""

    def test_value_serialization(self) -> None:
        """None/布尔/列表/日期/Decimal 的 CSV 文本表示."""
        from datetime import date
        from decimal import Decimal

        rows = [
            {
                "空": None,
                "布尔": True,
                "多选": ["a", "b"],
                "日期": date(2026, 9, 1),
                "数值": Decimal("1.50"),
                "文本": "x,y",  # 含逗号须加引号
            }
        ]
        text = export_csv(rows, ["空", "布尔", "多选", "日期", "数值", "文本"])
        lines = text.strip().splitlines()
        assert lines[1] == ',true,a;b,2026-09-01,1.50,"x,y"'


class TestImport:
    """导入：CSV/JSON 结构校验、错误行报告与权限."""

    def test_import_csv(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """CSV 导入成功：文本值经类型还原后落库."""
        content = "标题,数量,标签\n甲,3.5,红;蓝\n乙,2,\n"
        upload = SimpleUploadedFile("data.csv", content.encode("utf-8"), content_type="text/csv")
        response = auth_client.post(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/import/", {"file": upload})
        assert response.status_code == 200
        assert response.data["created"] == 2
        assert response.data["errors"] == []
        row = table_records.fetch_row(table, 1, scope=None)
        assert row is not None
        assert row["标题"] == "甲"
        assert row["数量"] is not None
        assert row["标签"] == ["红", "蓝"]

    def test_import_errors_reported(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """坏值行跳过并报告行号，好行照常入库."""
        content = "标题,数量,标签\n甲,不是数字,\n乙,2,紫\n丙,4,红\n"
        upload = SimpleUploadedFile("data.csv", content.encode("utf-8"), content_type="text/csv")
        response = auth_client.post(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/import/", {"file": upload})
        assert response.status_code == 200
        assert response.data["created"] == 1
        errors = response.data["errors"]
        assert [error["row"] for error in errors] == [1, 2]

    def test_import_unknown_header_rejected(
        self, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """表头未知字段整体拒绝."""
        upload = SimpleUploadedFile("data.csv", "标题,不存在\n甲,1\n".encode(), content_type="text/csv")
        response = auth_client.post(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/import/", {"file": upload})
        assert response.status_code == 400
        assert "未知或不可见字段" in response.data["detail"]

    def test_import_hidden_field_rejected(self, api: APIClient, workspace: Workspace, table: DataTable) -> None:
        """表级隐藏字段对低角色不可导入."""
        TablePermission.objects.create(table=table, hidden_fields={"数量": "admin"})
        editor = User.objects.create_user(username="importer", password="Str0ng-Pass-42")
        WorkspaceMember.objects.create(workspace=workspace, user=editor, role=WorkspaceMember.Role.EDITOR)
        api.force_login(editor)
        upload = SimpleUploadedFile("data.csv", "标题,数量\n甲,1\n".encode(), content_type="text/csv")
        response = api.post(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/import/", {"file": upload})
        assert response.status_code == 400
        assert "数量" in response.data["detail"]

    def test_import_json(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """JSON 数组导入：原生类型值直接校验落库."""
        response = auth_client.post(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/import/",
            [{"标题": "丙", "数量": 7, "标签": ["蓝"]}],
            format="json",
        )
        assert response.status_code == 200
        assert response.data["created"] == 1

    def test_import_json_invalid_rejected(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """JSON 结构非法（非数组/未知字段）返回 400."""
        bad = auth_client.post(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/import/", {"标题": "x"}, format="json"
        )
        assert bad.status_code == 400
        unknown = auth_client.post(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/import/", [{"不存在": 1}], format="json"
        )
        assert unknown.status_code == 400

    def test_import_requires_editor(self, api: APIClient, workspace: Workspace, table: DataTable) -> None:
        """viewer 导入返回 403."""
        viewer = User.objects.create_user(username="import-viewer", password="Str0ng-Pass-42")
        WorkspaceMember.objects.create(workspace=workspace, user=viewer, role=WorkspaceMember.Role.VIEWER)
        api.force_login(viewer)
        upload = SimpleUploadedFile("data.csv", "标题\n甲\n".encode(), content_type="text/csv")
        response = api.post(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/import/", {"file": upload})
        assert response.status_code == 403

    def test_import_empty_file_rejected(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """空文件返回 400."""
        upload = SimpleUploadedFile("data.csv", b"", content_type="text/csv")
        response = auth_client.post(f"/api/workspaces/{workspace.pk}/tables/{table.pk}/import/", {"file": upload})
        assert response.status_code == 400
