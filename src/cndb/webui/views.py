"""webui 页面视图：登录页、主应用页、公开表单页与共享视图页."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from cndb.tables.models import DataView


def login_page(request: HttpRequest) -> HttpResponse:
    """登录/注册页：已登录用户直接进入主应用."""
    if request.user.is_authenticated:
        return render(request, "webui/index.html", {"nickname": _nickname(request)})
    return render(request, "webui/login.html")


def _nickname(request: HttpRequest) -> str:
    """取当前用户显示昵称（无昵称回退用户名）."""
    user = request.user
    return getattr(user, "nickname", "") or user.get_username()


@login_required
def app_page(request: HttpRequest) -> HttpResponse:
    """主应用页：工作区/表/视图与 Grid."""
    return render(request, "webui/index.html", {"nickname": _nickname(request)})


def form_page(request: HttpRequest, slug: str) -> HttpResponse:
    """公开表单页：匿名渲染表单定义（非表单/未公开 404）."""
    view = get_object_or_404(
        DataView.objects.select_related("table"),
        slug=slug,
        view_type=DataView.ViewType.FORM,
        public=True,
    )
    options = view.form_options or {}
    enabled = options.get("fields", {})
    required_by_name = {name: bool(item.get("required")) for name, item in enabled.items() if item.get("enabled")}
    fields = [
        {
            "name": str(field.name),
            "field_type": str(field.field_type),
            "required": required_by_name.get(str(field.name), False),
            "config": field.config or {},
        }
        for field in view.table.active_fields()
        if str(field.name) in required_by_name
    ]
    return render(
        request,
        "webui/form.html",
        {
            "slug": slug,
            "title": options.get("title") or view.name,
            "description": options.get("description", ""),
            "submit_text": options.get("submit_text", "提交"),
            "form_fields": fields,
        },
    )


def share_page(request: HttpRequest, slug: str) -> HttpResponse:
    """共享视图页：匿名只读 Grid（非 grid/未公开 404）."""
    view = get_object_or_404(
        DataView.objects.select_related("table"),
        slug=slug,
        view_type=DataView.ViewType.GRID,
        public=True,
    )
    options = view.field_options or {}
    fields = [
        {"name": str(field.name), "width": (options.get(str(field.name)) or {}).get("width", 0)}
        for field in view.table.active_fields()
        if not (options.get(str(field.name)) or {}).get("hidden")
    ]
    return render(
        request,
        "webui/share.html",
        {"slug": slug, "view_name": view.name, "fields": fields},
    )
