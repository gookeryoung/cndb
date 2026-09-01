"""共享视图路由：挂载在 /api/views/ 之下（匿名可访问）."""

from __future__ import annotations

from django.urls import path

from cndb.tables.share_views import PublicViewRowsView

urlpatterns = [
    path("<str:slug>/rows/", PublicViewRowsView.as_view(), name="public-view-rows"),
]
