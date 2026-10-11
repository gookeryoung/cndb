"""workflows 插件路由（facade —— 聚合子路由）."""

from __future__ import annotations

from fastapi import APIRouter

from cndb.plugins.workflows.routers.approvals import router as approvals_router
from cndb.plugins.workflows.routers.workflows import router as workflows_router

router = APIRouter()
router.include_router(workflows_router)
router.include_router(approvals_router)

__all__ = ["router"]
