"""documents 插件路由包."""

from __future__ import annotations

from .documents import router
from .public import public_router

__all__ = ["public_router", "router"]
