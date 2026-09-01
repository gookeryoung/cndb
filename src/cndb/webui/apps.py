"""webui 应用配置."""

from __future__ import annotations

from django.apps import AppConfig


class WebuiConfig(AppConfig):
    """前端页面应用配置."""

    name = "cndb.webui"
    verbose_name = "前端页面"
