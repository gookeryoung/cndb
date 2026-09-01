"""生产环境配置."""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *


def _require_secret_key() -> str:
    """生产环境必须通过环境变量提供密钥，缺失即拒绝启动。"""
    key = os.environ.get("CNDB_SECRET_KEY")
    if not key:
        raise ImproperlyConfigured("生产环境必须设置环境变量 CNDB_SECRET_KEY")
    return key


SECRET_KEY = _require_secret_key()

ALLOWED_HOSTS = [h for h in os.environ.get("CNDB_ALLOWED_HOSTS", "").split(",") if h]
