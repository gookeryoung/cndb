"""datasource 路由：providers（适配器清单） + sync-jobs（任务 / 运行 / 预览）."""

from __future__ import annotations

from fastapi import APIRouter

from cndb.plugins.datasource.routers.providers import router as providers_router
from cndb.plugins.datasource.routers.sync_jobs import router as sync_jobs_router

router = APIRouter()
router.include_router(providers_router)
router.include_router(sync_jobs_router)

__all__ = ["router"]
