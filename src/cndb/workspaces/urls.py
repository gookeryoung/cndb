"""workspaces 路由."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from cndb.workspaces.views import MemberDetailView, MemberListCreateView, WorkspaceViewSet

router = DefaultRouter()
router.register("", WorkspaceViewSet, basename="workspaces")

urlpatterns = [
    path("<int:workspace_pk>/members/", MemberListCreateView.as_view(), name="workspace-members"),
    path("<int:workspace_pk>/members/<int:pk>/", MemberDetailView.as_view(), name="workspace-member"),
    path("", include(router.urls)),
]
