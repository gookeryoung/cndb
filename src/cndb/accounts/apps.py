"""accounts 应用配置."""

from __future__ import annotations

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """用户与认证应用配置."""

    name = "cndb.accounts"
    verbose_name = "用户"
