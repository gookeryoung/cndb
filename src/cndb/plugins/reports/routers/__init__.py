"""reports 插件路由聚合."""

from __future__ import annotations

from fastapi import APIRouter

from cndb.plugins.reports.routers.reports import router as reports_router

router = APIRouter()
router.include_router(reports_router)

__all__ = ["router"]
