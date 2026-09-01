"""tokens 应用配置."""

from __future__ import annotations

from django.apps import AppConfig


class TokensConfig(AppConfig):
    """API 令牌应用配置."""

    name = "cndb.tokens"
    verbose_name = "API 令牌"
