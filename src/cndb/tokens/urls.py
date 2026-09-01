"""tokens 路由：挂载在 /api/tokens/ 之下."""

from __future__ import annotations

from django.urls import path

from cndb.tokens.views import TokenDetailView, TokenListCreateView

urlpatterns = [
    path("", TokenListCreateView.as_view(), name="tokens"),
    path("<int:pk>/", TokenDetailView.as_view(), name="token-detail"),
]
