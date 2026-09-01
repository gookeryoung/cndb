"""公开表单路由：挂载在 /api/forms/ 之下（匿名可访问）."""

from __future__ import annotations

from django.urls import path

from cndb.tables.form_views import PublicFormSubmitView, PublicFormView

urlpatterns = [
    path("<str:slug>/", PublicFormView.as_view(), name="public-form"),
    path("<str:slug>/submit/", PublicFormSubmitView.as_view(), name="public-form-submit"),
]
