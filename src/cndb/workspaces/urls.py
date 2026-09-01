"""workspaces 路由."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from cndb.workspaces.views import (
    MemberCandidatesView,
    MemberDetailView,
    MemberListCreateView,
    WorkspaceViewSet,
)

router = DefaultRouter()
router.register("", WorkspaceViewSet, basename="workspaces")

urlpatterns = [
    path("<int:workspace_pk>/members/", MemberListCreateView.as_view(), name="workspace-members"),
    path("<int:workspace_pk>/members/candidates/", MemberCandidatesView.as_view(), name="workspace-member-candidates"),
    path("<int:workspace_pk>/members/<int:pk>/", MemberDetailView.as_view(), name="workspace-member"),
    path("<int:workspace_pk>/tables/", include("cndb.tables.urls")),
    path("", include(router.urls)),
]
