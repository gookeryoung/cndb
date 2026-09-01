"""公开表单视图：匿名读取表单定义与提交行数据.

公开端点不走任何认证（authentication_classes 置空）——
SessionAuthentication 对携带平台会话 cookie 的提交会强制 CSRF 校验，
而公开表单的提交方通常是未登录访客，必须与平台会话完全解耦。
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cndb.tables import records
from cndb.tables.models import DataView


def _public_form(slug: str) -> DataView:
    """按 slug 取公开表单视图：非表单/未公开一律 404，不泄露存在性."""
    return get_object_or_404(
        DataView.objects.select_related("table"),
        slug=slug,
        view_type=DataView.ViewType.FORM,
        public=True,
    )


def _enabled_fields(view: DataView) -> dict[str, bool]:
    """返回表单启用字段的必填映射，仅保留当前仍有效的字段（已回收字段剔除）."""
    active_names = {str(field.name) for field in view.table.active_fields()}
    return {
        name: bool(options.get("required"))
        for name, options in (view.form_options.get("fields", {})).items()
        if options.get("enabled") and name in active_names
    }


class PublicFormView(APIView):
    """公开表单定义：标题/描述/提交文案与启用字段元信息（供外部渲染）."""

    permission_classes = [permissions.AllowAny]
    authentication_classes: list[type[object]] = []

    def get(self, _request: Request, slug: str) -> Response:
        """返回表单定义：启用字段的名称/类型/必填/配置."""
        view = _public_form(slug)
        required_by_name = _enabled_fields(view)
        fields = [
            {
                "name": str(field.name),
                "field_type": str(field.field_type),
                "required": required_by_name[str(field.name)],
                "config": field.config,
            }
            for field in view.table.active_fields()
            if str(field.name) in required_by_name
        ]
        options = view.form_options
        return Response(
            {
                "title": options.get("title", ""),
                "description": options.get("description", ""),
                "submit_text": options.get("submit_text", "提交"),
                "fields": fields,
            }
        )


class PublicFormSubmitView(APIView):
    """公开表单提交：匿名写入一行，仅启用字段可写、必填与值校验同构行数据."""

    permission_classes = [permissions.AllowAny]
    authentication_classes: list[type[object]] = []

    def post(self, request: Request, slug: str) -> Response:
        """提交行数据：未启用字段 400、必填缺失 400、值非法 400，成功 201."""
        view = _public_form(slug)
        table = view.table
        required_by_name = _enabled_fields(view)
        data = request.data
        if not isinstance(data, dict):
            return Response({"detail": "提交数据必须是对象"}, status=400)
        for name in data:
            if name not in required_by_name:
                return Response({"detail": f"字段未启用: {name}"}, status=400)
        for name, required in required_by_name.items():
            if required and data.get(name) is None:
                return Response({"detail": f"必填字段缺失: {name}"}, status=400)
        try:
            cleaned = records.clean_row(table, data, partial=True)
        except records.InvalidRowError as exc:
            return Response({"detail": str(exc)}, status=400)
        records.insert_row(table, cleaned)
        return Response({"detail": view.form_options.get("submit_text", "提交")}, status=201)
