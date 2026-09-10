"""pyweb_template FastAPI 应用入口.

职责：
- 组装 FastAPI app（配置/中间件/lifespan）
- 启动时自动发现并挂载所有插件
- 暴露框架级元路由（/api/health /api/plugins /api/navigation）
- 不承载业务逻辑，业务由 plugins 按需挂载
- 使用 FastAPIOffline，Swagger UI / ReDoc 静态资源从本地加载，避免外网依赖

启动方式：
- pywt serve（CLI 入口，见 runner.py）
- uvicorn pyweb_template.app:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_offline import FastAPIOffline

from pyweb_template.core.config import settings
from pyweb_template.core.plugin_registry import plugin_registry


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """应用生命周期管理."""

    yield


app = FastAPIOffline(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="pyweb-template - FastAPI + SQLAlchemy + Plugin 架构脚手架",
    lifespan=lifespan,
)


# ── 启动时自动发现并挂载插件（模块加载时执行，避免依赖 TestClient lifespan）──
if settings.PLUGINS_AUTO_DISCOVER:
    plugin_registry.discover_and_load()
plugin_registry.mount_routes(app)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["framework"])
def health_check() -> dict[str, object]:
    """框架级健康检查（最简版）."""
    return {"status": "ok", "version": settings.APP_VERSION, "app": settings.APP_NAME}


@app.get("/api/plugins", tags=["framework"])
def list_plugins() -> dict[str, object]:
    """获取已加载插件列表."""
    return {"plugins": plugin_registry.get_plugin_info_list()}


@app.get("/api/navigation", tags=["framework"])
def get_navigation() -> dict[str, object]:
    """汇总所有插件注册的侧边栏导航项."""
    return {"navigation": plugin_registry.get_all_navigation()}
