"""webui 路由."""

from __future__ import annotations

from django.urls import path

from cndb.webui.views import app_page, form_page, login_page, share_page

urlpatterns = [
    path("", app_page, name="webui-app"),
    path("login/", login_page, name="webui-login"),
    path("forms/<str:slug>/", form_page, name="webui-form"),
    path("share/<str:slug>/", share_page, name="webui-share"),
]
