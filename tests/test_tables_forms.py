"""表单视图定义测试：slug 生成、form_options 校验与序列化."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from cndb.accounts.models import User
from cndb.tables.models import DataTable, DataView
from cndb.tables.view_rules import InvalidViewError, ViewRules, normalize_view
from cndb.workspaces.models import Workspace


def _table_with_fields(workspace: Workspace, names: list[str]) -> DataTable:
    """建一张带 text 字段的表（走服务层保证物理表同步创建）."""
    from cndb.tables import services

    return services.create_table(
        workspace=workspace,  # type: ignore[arg-type]
        name=f"表单表-{names[0]}",
        field_defs=[{"name": name, "field_type": "text"} for name in names],
    )


@pytest.fixture
def table(workspace: Workspace) -> DataTable:
    """带单个 text 字段（标题）的数据表."""
    return _table_with_fields(workspace, ["标题"])


class TestFormSlug:
    """slug 生成：仅表单视图持有，系统生成不可预测."""

    def test_form_view_gets_slug(self, workspace: Workspace) -> None:
        """表单视图保存时自动生成 form_ 前缀 slug."""
        table = _table_with_fields(workspace, ["姓名"])
        view = DataView.objects.create(table=table, name="报名表", view_type=DataView.ViewType.FORM)
        assert view.slug is not None
        assert view.slug.startswith("form_")
        assert len(view.slug) == len("form_") + 16

    def test_slug_stable_across_saves(self, workspace: Workspace) -> None:
        """再次保存不重置 slug."""
        table = _table_with_fields(workspace, ["姓名"])
        view = DataView.objects.create(table=table, name="报名表", view_type=DataView.ViewType.FORM)
        original = view.slug
        view.name = "报名表改"
        view.save()
        view.refresh_from_db()
        assert view.slug == original

    def test_other_types_have_no_slug(self, workspace: Workspace) -> None:
        """非表单视图 slug 为 None（多视图共存不触发唯一约束）."""
        table = _table_with_fields(workspace, ["姓名"])
        DataView.objects.create(table=table, name="表格A")
        DataView.objects.create(table=table, name="表格B")
        assert not DataView.objects.filter(table=table, slug__isnull=False).exists()


class TestFormOptionsRules:
    """form_options 校验矩阵：结构/字段引用/必填约束."""

    def test_defaults_normalized(self, workspace: Workspace) -> None:
        """空配置归一化为默认文案与空字段集."""
        table = _table_with_fields(workspace, ["姓名"])
        normalized = normalize_view(table, ViewRules(view_type="form", form_options={}))
        assert normalized["form_options"] == {"title": "", "description": "", "submit_text": "提交", "fields": {}}

    def test_valid_options(self, workspace: Workspace) -> None:
        """合法配置原样归一化，缺省键补全."""
        table = _table_with_fields(workspace, ["姓名", "电话"])
        normalized = normalize_view(
            table,
            ViewRules(
                view_type="form",
                form_options={
                    "title": "活动报名",
                    "fields": {"姓名": {"enabled": True, "required": True}, "电话": {"enabled": True}},
                },
            ),
        )
        options = normalized["form_options"]
        assert options["title"] == "活动报名"
        assert options["submit_text"] == "提交"
        assert options["fields"]["姓名"] == {"enabled": True, "required": True}
        assert options["fields"]["电话"] == {"enabled": True, "required": False}

    @pytest.mark.parametrize(
        "form_options",
        [
            "不是对象",
            {"title": 123},
            {"fields": []},
            {"fields": {"不存在": {"enabled": True}}},
            {"fields": {"姓名": "不是对象"}},
            {"fields": {"姓名": {"enabled": "yes"}}},
            {"fields": {"姓名": {"enabled": False, "required": True}}},
        ],
    )
    def test_invalid_rejected(self, workspace: Workspace, form_options: Any) -> None:
        """非法配置统一拒绝."""
        table = _table_with_fields(workspace, ["姓名"])
        with pytest.raises(InvalidViewError):
            normalize_view(table, ViewRules(view_type="form", form_options=form_options))


class TestFormViewAPI:
    """表单视图 API：创建/更新携带 form_options，slug 只读暴露."""

    def test_create_form_view(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """建表单视图返回 201，slug 非空、form_options 归一化回显."""
        response = auth_client.post(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/views/",
            {
                "name": "调研表",
                "view_type": "form",
                "form_options": {"title": "满意度调研", "fields": {"标题": {"enabled": True, "required": True}}},
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.data["slug"].startswith("form_")
        assert response.data["form_options"]["title"] == "满意度调研"
        assert response.data["form_options"]["fields"]["标题"] == {"enabled": True, "required": True}

    def test_update_form_options(self, auth_client: APIClient, workspace: Workspace, table: DataTable) -> None:
        """PATCH 更新表单配置成功，未知字段引用 400."""
        created = auth_client.post(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/views/",
            {"name": "更新表", "view_type": "form"},
            format="json",
        )
        assert created.status_code == 201
        view_id = created.data["id"]
        ok = auth_client.patch(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/views/{view_id}/",
            {"form_options": {"fields": {"标题": {"enabled": True}}}},
            format="json",
        )
        assert ok.status_code == 200
        assert ok.data["form_options"]["fields"]["标题"]["enabled"] is True
        bad = auth_client.patch(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/views/{view_id}/",
            {"form_options": {"fields": {"不存在": {"enabled": True}}}},
            format="json",
        )
        assert bad.status_code == 400

    def test_slug_read_only(self, auth_client: APIClient, workspace: Workspace, table: DataTable, user: User) -> None:
        """slug 为系统生成只读字段：传入自定义值被忽略."""
        response = auth_client.post(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/views/",
            {"name": "只读表", "view_type": "form", "slug": "form_custom"},
            format="json",
        )
        assert response.status_code == 201
        assert response.data["slug"] != "form_custom"
        assert response.data["slug"].startswith("form_")


def _public_form(api: APIClient, workspace: Workspace, table: DataTable, **options: Any) -> str:
    """创建并公开一张表单视图，返回其 slug."""
    created = api.post(
        f"/api/workspaces/{workspace.pk}/tables/{table.pk}/views/",
        {"name": "公开表", "view_type": "form", "public": True, "form_options": options or {}},
        format="json",
    )
    assert created.status_code == 201
    return str(created.data["slug"])


class TestPublicFormDefinition:
    """匿名读取表单定义：公开可见性与字段元信息."""

    def test_definition_anonymous(
        self, api: APIClient, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """匿名读取公开表单定义：文案与启用字段元信息."""
        slug = _public_form(
            auth_client,
            workspace,
            table,
            title="报名表",
            description="请填写",
            submit_text="递交",
            fields={"标题": {"enabled": True, "required": True}},
        )
        response = api.get(f"/api/forms/{slug}/")
        assert response.status_code == 200
        assert response.data["title"] == "报名表"
        assert response.data["submit_text"] == "递交"
        assert len(response.data["fields"]) == 1
        field = response.data["fields"][0]
        assert field["name"] == "标题"
        assert field["field_type"] == "text"
        assert field["required"] is True

    def test_private_form_404(
        self, api: APIClient, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """未公开（public=False）的表单定义 404，不泄露存在性."""
        created = auth_client.post(
            f"/api/workspaces/{workspace.pk}/tables/{table.pk}/views/",
            {"name": "私有表", "view_type": "form"},
            format="json",
        )
        slug = created.data["slug"]
        assert api.get(f"/api/forms/{slug}/").status_code == 404
        assert api.post(f"/api/forms/{slug}/submit/", {"标题": "x"}, format="json").status_code == 404

    def test_unknown_slug_404(self, api: APIClient, db: object) -> None:
        """未知 slug 404."""
        assert api.get("/api/forms/form_nope/").status_code == 404

    def test_disabled_field_hidden(
        self, api: APIClient, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """未启用字段不出现在表单定义中."""
        slug = _public_form(auth_client, workspace, table, fields={"标题": {"enabled": False}})
        response = api.get(f"/api/forms/{slug}/")
        assert response.status_code == 200
        assert response.data["fields"] == []


class TestPublicFormSubmit:
    """匿名提交：字段启用约束、必填校验与值校验."""

    def test_submit_success(
        self, api: APIClient, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """匿名提交成功：行入库、返回提交文案."""
        slug = _public_form(
            auth_client,
            workspace,
            table,
            submit_text="已收到",
            fields={"标题": {"enabled": True}},
        )
        response = api.post(f"/api/forms/{slug}/submit/", {"标题": "访客提交"}, format="json")
        assert response.status_code == 201
        assert response.data["detail"] == "已收到"
        from cndb.tables import records

        row = records.fetch_row(table, 1, scope=None)
        assert row is not None
        assert row["标题"] == "访客提交"

    def test_submit_rejects_disabled_field(
        self, api: APIClient, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """提交未启用字段返回 400 且不落库."""
        slug = _public_form(auth_client, workspace, table, fields={})
        response = api.post(f"/api/forms/{slug}/submit/", {"标题": "偷偷写"}, format="json")
        assert response.status_code == 400
        assert "未启用" in response.data["detail"]

    def test_submit_required_missing(
        self, api: APIClient, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """必填字段缺失返回 400."""
        slug = _public_form(auth_client, workspace, table, fields={"标题": {"enabled": True, "required": True}})
        response = api.post(f"/api/forms/{slug}/submit/", {}, format="json")
        assert response.status_code == 400
        assert "必填" in response.data["detail"]

    def test_submit_invalid_value(
        self, api: APIClient, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """值非法（超出 max_length）返回 400，校验复用行数据口径."""
        slug = _public_form(auth_client, workspace, table, fields={"标题": {"enabled": True}})
        response = api.post(f"/api/forms/{slug}/submit/", {"标题": "长" * 300}, format="json")
        assert response.status_code == 400

    def test_submit_with_session_cookie(
        self, api: APIClient, auth_client: APIClient, workspace: Workspace, table: DataTable, user: User
    ) -> None:
        """携带平台会话的访客提交不受 CSRF 阻断（公开端点跳过认证）."""
        slug = _public_form(auth_client, workspace, table, fields={"标题": {"enabled": True}})
        api.force_login(user)
        response = api.post(f"/api/forms/{slug}/submit/", {"标题": "会话用户提交"}, format="json")
        assert response.status_code == 201

    def test_submit_non_object_rejected(
        self, api: APIClient, auth_client: APIClient, workspace: Workspace, table: DataTable
    ) -> None:
        """提交非对象（数组）返回 400."""
        slug = _public_form(auth_client, workspace, table, fields={"标题": {"enabled": True}})
        response = api.post(f"/api/forms/{slug}/submit/", ["标题"], format="json")
        assert response.status_code == 400
