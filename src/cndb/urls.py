"""根 URL 路由."""

from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("cndb.accounts.urls")),
    path("api/workspaces/", include("cndb.workspaces.urls")),
]
