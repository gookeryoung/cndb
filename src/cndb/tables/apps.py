"""tables 应用配置."""

from __future__ import annotations

from django.apps import AppConfig


class TablesConfig(AppConfig):
    """数据表元数据应用配置."""

    name = "cndb.tables"
    verbose_name = "数据表"
