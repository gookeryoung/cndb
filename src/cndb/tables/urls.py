"""tables 路由：挂载在工作区之下（/api/workspaces/<pk>/tables/...）."""

from __future__ import annotations

from django.urls import path

from cndb.tables.permission_views import PermissionDetailView
from cndb.tables.record_views import RecordBulkView, RecordDetailView, RecordListCreateView
from cndb.tables.view_views import (
    ViewAggregationsView,
    ViewDetailView,
    ViewListCreateView,
    ViewRowsView,
)
from cndb.tables.views import (
    FieldDetailView,
    FieldListCreateView,
    TableDetailView,
    TableListCreateView,
)

urlpatterns = [
    path("", TableListCreateView.as_view(), name="tables"),
    path("<int:pk>/", TableDetailView.as_view(), name="table-detail"),
    path("<int:table_pk>/fields/", FieldListCreateView.as_view(), name="table-fields"),
    path("<int:table_pk>/fields/<int:pk>/", FieldDetailView.as_view(), name="table-field"),
    path("<int:table_pk>/records/", RecordListCreateView.as_view(), name="table-records"),
    path("<int:table_pk>/records/bulk/", RecordBulkView.as_view(), name="table-records-bulk"),
    path("<int:table_pk>/records/<int:row_id>/", RecordDetailView.as_view(), name="table-record"),
    path("<int:table_pk>/views/", ViewListCreateView.as_view(), name="table-views"),
    path("<int:table_pk>/views/<int:pk>/", ViewDetailView.as_view(), name="table-view"),
    path("<int:table_pk>/views/<int:pk>/rows/", ViewRowsView.as_view(), name="table-view-rows"),
    path("<int:table_pk>/views/<int:pk>/aggregations/", ViewAggregationsView.as_view(), name="table-view-aggregations"),
    path("<int:table_pk>/permission/", PermissionDetailView.as_view(), name="table-permission"),
]
