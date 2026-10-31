"""pipeline 路由门面：定义路由 + 运行 / 发现物路由."""

from __future__ import annotations

from cndb.plugins.pipeline.routers.workflows import router as workflows_router
from cndb.plugins.pipeline.routers.workflows import runs_router

__all__ = ["runs_router", "workflows_router"]
