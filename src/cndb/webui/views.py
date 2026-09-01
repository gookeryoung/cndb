"""webui 页面视图：登录页与主应用页."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def login_page(request: HttpRequest) -> HttpResponse:
    """登录/注册页：已登录用户直接进入主应用."""
    if request.user.is_authenticated:
        return render(request, "webui/index.html")
    return render(request, "webui/login.html")


@login_required
def app_page(request: HttpRequest) -> HttpResponse:
    """主应用页：工作区/表/视图与 Grid."""
    user = request.user
    nickname = getattr(user, "nickname", "") or user.get_username()
    return render(request, "webui/index.html", {"nickname": nickname})
