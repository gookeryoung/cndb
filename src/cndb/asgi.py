"""ASGI 入口."""

from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cndb.settings.prod")

application = get_asgi_application()
