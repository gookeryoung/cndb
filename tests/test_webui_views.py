"""webui 页面测试：登录页渲染、登录重定向与主应用渲染."""

from __future__ import annotations

import pytest
from django.test import Client

from cndb.accounts.models import User

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
        assert "/static/webui/app.js" in content

    def test_nickname_fallback_to_username(self, client: Client, db: object) -> None:
        """昵称为空时回退显示用户名."""
        plain = User.objects.create_user(username="carol", password="Str0ng-Pass-42")
        client.force_login(plain)
        response = client.get("/")
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "carol" in content
        assert 'id="user-nickname"' in content
