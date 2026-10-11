"""forms 插件路由聚合（facade —— 只做导入导出）."""

from __future__ import annotations

from fastapi import APIRouter

from cndb.plugins.forms.routers.forms import router as forms_router

router = APIRouter()
router.include_router(forms_router)

__all__ = ["router"]
