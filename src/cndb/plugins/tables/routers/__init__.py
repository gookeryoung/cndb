"""tables 插件路由聚合."""

from __future__ import annotations

from fastapi import APIRouter

from cndb.plugins.tables.routers.bulk import router as bulk_router
from cndb.plugins.tables.routers.fields import router as fields_router
from cndb.plugins.tables.routers.permissions import router as permissions_router
from cndb.plugins.tables.routers.public import router as public_router  # noqa: F401 — 全局公开路由，由 app.py 直接挂载
from cndb.plugins.tables.routers.records import router as records_router
from cndb.plugins.tables.routers.tables import router as tables_router
from cndb.plugins.tables.routers.views import router as views_router

router = APIRouter()
router.include_router(tables_router)
router.include_router(views_router)
router.include_router(permissions_router)
router.include_router(bulk_router)
router.include_router(fields_router)
router.include_router(records_router)

__all__ = ["router"]
