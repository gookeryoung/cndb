"""llm 插件路由聚合（``/api/v1/llm``）：个人连接 / 能力目录 / 调用记录."""

from __future__ import annotations

from fastapi import APIRouter

from cndb.plugins.llm.routers.actions import router as actions_router
from cndb.plugins.llm.routers.config import router as config_router
from cndb.plugins.llm.routers.runs import router as runs_router

router = APIRouter()
router.include_router(config_router)
router.include_router(actions_router)
router.include_router(runs_router)

__all__ = ["router"]
