"""webui 路由."""

from __future__ import annotations

from django.urls import path

from cndb.webui.views import app_page, login_page

urlpatterns = [
    path("", app_page, name="webui-app"),
    path("login/", login_page, name="webui-login"),
]
