"""webui 页面测试：登录页、主应用页与公开表单/共享视图页."""

from __future__ import annotations

import pytest
from django.test import Client

from cndb.accounts.models import User
from cndb.tables import services
from cndb.tables.models import DataTable, DataView
from cndb.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


class TestLoginPage:
    """登录页：未登录可访问，已登录跳主应用."""

    def test_anonymous_gets_login_page(self, client: Client) -> None:
        """未登录访问登录页返回 200，渲染登录表单."""
        response = client.get("/login/")
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "auth-form" in content
        assert "/static/webui/auth.js" in content

    def test_authenticated_gets_app(self, client: Client, user: User) -> None:
        """已登录访问登录页直接渲染主应用."""
        client.force_login(user)
        response = client.get("/login/")
        assert response.status_code == 200
        assert "view-tabs" in response.content.decode("utf-8")


class TestAppPage:
    """主应用页：需登录，渲染侧栏与 Grid 骨架."""

    def test_anonymous_redirected_to_login(self, client: Client) -> None:
        """未登录访问主应用 302 跳登录页并带 next."""
        response = client.get("/")
        assert response.status_code == 302
        assert response.url == "/login/?next=/"

    def test_authenticated_renders_app(self, client: Client, user: User) -> None:
        """已登录渲染主应用：含昵称、工作区选择器与 Grid 容器."""
        client.force_login(user)
        response = client.get("/")
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "爱丽丝" in content
        assert 'id="workspace-select"' in content
        assert 'id="grid-body"' in content
        assert 'id="row-detail"' in content
        assert "/static/webui/app.js" in content
        assert "/static/webui/actions.js" in content
        # 编辑与管理入口
        for element_id in (
            "workspace-create-btn",
            "table-create-btn",
            "field-add-btn",
            "view-create-btn",
            "view-edit-btn",
            "export-btn",
            "import-btn",
            "member-btn",
            "modal-mask",
            "grid-foot",
            "row-detail-edit",
        ):
            assert f'id="{element_id}"' in content

    def test_nickname_fallback_to_username(self, client: Client, db: object) -> None:
        """昵称为空时回退显示用户名."""
        plain = User.objects.create_user(username="carol", password="Str0ng-Pass-42")
        client.force_login(plain)
        response = client.get("/")
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "carol" in content
        assert 'id="user-nickname"' in content


class TestStaticVersionTag:
    """static_v 标签：静态资源 URL 附加 mtime 版本参数破缓存."""

    def test_url_with_version(self, client: Client, user: User) -> None:
        """已登录页面静态资源带 ?v=<mtime> 版本参数."""
        client.force_login(user)
        content = client.get("/").content.decode("utf-8")
        assert "/static/webui/app.js?v=" in content
        assert "/static/webui/actions.js?v=" in content

    def test_unknown_path_plain_url(self) -> None:
        """finder 找不到的路径返回不带版本号的原始 URL."""
        from cndb.webui.templatetags.static_version import static_v

        url = static_v("webui/not-exists.js")
        assert url == "/static/webui/not-exists.js"


@pytest.fixture
def table(workspace: Workspace) -> DataTable:
    """带多类型字段的公开页测试表."""
    return services.create_table(
        workspace=workspace,  # type: ignore[arg-type]
        name="公开表",
        field_defs=[
            {"name": "标题", "field_type": "text"},
            {"name": "状态", "field_type": "single_select", "config": {"choices": ["待办", "完成"]}},
            {"name": "截止", "field_type": "date"},
        ],
    )


class TestFormPage:
    """公开表单页：匿名渲染启用字段，非表单/未公开 404."""

    def test_renders_enabled_fields(self, client: Client, table: DataTable) -> None:
        """公开表单页渲染标题、描述与启用字段控件."""
        view = DataView.objects.create(
            table=table,
            name="调研",
            view_type=DataView.ViewType.FORM,
            public=True,
            form_options={
                "title": "需求调研",
                "description": "请填写以下信息",
                "submit_text": "发送",
                "fields": {"标题": {"enabled": True, "required": True}, "状态": {"enabled": True}},
            },
        )
        response = client.get(f"/forms/{view.slug}/")
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "需求调研" in content
        assert "请填写以下信息" in content
        assert "发送" in content
        assert "标题" in content
        assert 'data-name="标题"' in content
        assert 'data-type="single_select"' in content
        assert "截止" not in content.split("<form")[1]  # 未启用字段不渲染

    def test_unknown_slug_404(self, client: Client, db: object) -> None:
        """未知 slug 返回 404."""
        assert client.get("/forms/form_0000000000000000/").status_code == 404

    def test_unshared_form_404(self, client: Client, table: DataTable) -> None:
        """未公开表单 404."""
        view = DataView.objects.create(table=table, name="私有表单", view_type=DataView.ViewType.FORM)
        assert client.get(f"/forms/{view.slug or ''}/").status_code == 404

    def test_grid_slug_not_form_page(self, client: Client, table: DataTable) -> None:
        """grid 视图 slug 不能经表单页访问."""
        view = DataView.objects.create(table=table, name="共享", public=True)
        assert client.get(f"/forms/{view.slug}/").status_code == 404


class TestSharePage:
    """共享视图页：匿名只读 Grid，非 grid/未公开 404."""

    def test_renders_view(self, client: Client, table: DataTable) -> None:
        """共享页渲染视图名与字段表头，携带 slug 供 JS 拉行."""
        view = DataView.objects.create(table=table, name="项目进度", public=True)
        response = client.get(f"/share/{view.slug}/")
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "项目进度" in content
        assert 'data-slug="' + str(view.slug) + '"' in content
        assert "标题" in content
        assert "share-body" in content

    def test_unknown_slug_404(self, client: Client, db: object) -> None:
        """未知 slug 返回 404."""
        assert client.get("/share/share_0000000000000000/").status_code == 404

    def test_form_slug_not_share_page(self, client: Client, table: DataTable) -> None:
        """表单视图 slug 不能经共享页访问."""
        view = DataView.objects.create(table=table, name="表单", view_type=DataView.ViewType.FORM, public=True)
        assert client.get(f"/share/{view.slug}/").status_code == 404
