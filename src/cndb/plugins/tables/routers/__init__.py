"""tables 插件路由聚合."""

from __future__ import annotations

from fastapi import APIRouter

from cndb.plugins.tables.routers.audit import router as audit_router
from cndb.plugins.tables.routers.bulk import router as bulk_router
from cndb.plugins.tables.routers.comments import router as comments_router
from cndb.plugins.tables.routers.fields import router as fields_router
from cndb.plugins.tables.routers.files import router as files_router
from cndb.plugins.tables.routers.import_api import router as import_api_router
from cndb.plugins.tables.routers.import_csv import compat_router as import_csv_router
from cndb.plugins.tables.routers.import_csv import router as import_file_router
from cndb.plugins.tables.routers.members import router as members_router
from cndb.plugins.tables.routers.permissions import router as permissions_router
from cndb.plugins.tables.routers.public import router as public_router  # noqa: F401 — 全局公开路由，由 app.py 直接挂载
from cndb.plugins.tables.routers.records import router as records_router
from cndb.plugins.tables.routers.tables import router as tables_router
from cndb.plugins.tables.routers.trash import router as trash_router
from cndb.plugins.tables.routers.views import router as views_router

router = APIRouter()
router.include_router(tables_router)
router.include_router(views_router)
router.include_router(permissions_router)
router.include_router(members_router)
router.include_router(comments_router)
router.include_router(audit_router)
router.include_router(trash_router)
router.include_router(bulk_router)
router.include_router(fields_router)
router.include_router(files_router)
router.include_router(records_router)
router.include_router(import_csv_router)
router.include_router(import_file_router)
router.include_router(import_api_router)

__all__ = ["router"]
