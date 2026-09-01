"""根 URL 路由."""

from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("cndb.webui.urls")),
    path("admin/", admin.site.urls),
    path("api/auth/", include("cndb.accounts.urls")),
    path("api/tokens/", include("cndb.tokens.urls")),
    path("api/forms/", include("cndb.tables.form_urls")),
    path("api/views/", include("cndb.tables.share_urls")),
    path("api/workspaces/", include("cndb.workspaces.urls")),
]
