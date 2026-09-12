"""workflows 插件路由聚合."""

from __future__ import annotations

from fastapi import APIRouter

from cndb.plugins.workflows.routers.workflows import router as workflows_router

router = APIRouter()
router.include_router(workflows_router)

__all__ = ["router"]
