"""cndb FastAPI 应用入口.

职责：
- 组装 FastAPI app（配置/中间件/lifespan）
- 启动时自动发现并挂载所有插件
- 暴露框架级元路由（/api/health /api/plugins /api/navigation）
- 不承载业务逻辑，业务由 plugins 按需挂载
- 使用 FastAPIOffline，Swagger UI / ReDoc 静态资源从本地加载，避免外网依赖

启动方式：
- cndb serve（CLI 入口，见 runner.py）
- uvicorn cndb.app:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi_offline import FastAPIOffline

from cndb.core.config import settings
from cndb.core.plugin_registry import plugin_registry
from cndb.plugins.tables.routers.public import router as public_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """应用生命周期管理."""

    yield


app = FastAPIOffline(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="cndb - FastAPI + SQLAlchemy + Plugin 架构脚手架",
    lifespan=lifespan,
)


# ── 启动时自动发现并挂载插件（模块加载时执行，避免依赖 TestClient lifespan）──
if settings.PLUGINS_AUTO_DISCOVER:
    plugin_registry.discover_and_load()
plugin_registry.mount_routes(app)

# tables 插件全局公开路由
app.include_router(public_router)


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


# ── 前端静态资源（Vite build 产物挂 src/cndb/static/）─────────────
from collections.abc import Awaitable, Callable  # noqa: E402

from starlette.requests import Request  # noqa: E402
from starlette.responses import Response  # noqa: E402


def should_spa_fallback(path: str, accept_header: str) -> bool:
    """判断是否应该对 404 请求回退 index.html.

    Args:
        path: 请求路径（如 ``"/w/1/tables"``）.
        accept_header: HTTP Accept 头的值.

    Returns:
        ``True`` 表示应该回退到 index.html.
    """
    # API 路由不走前端
    if path.startswith("/api/"):
        return False
    # /assets/ 下的静态资源直接返回 404，避免把不存在的 JS chunk 回成 HTML
    if path.startswith("/assets/"):
        return False
    # 仅对浏览器页面请求回退（Accept 包含 text/html）
    return "text/html" in accept_header


_STATIC = Path(__file__).resolve().parent / "static"
if _STATIC.is_dir():
    # 挂载 /assets 为独立静态目录（带 hash 的产物，可长缓存）
    app.mount("/assets", StaticFiles(directory=str(_STATIC / "assets")), name="assets")

    @app.middleware("http")
    async def _spa_fallback(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """SPA 路由 fallback 中间件.

        仅对以下条件同时满足的 404 请求回退到 index.html：
        1. 非 /api/ 开头（API 路由不走前端）
        2. 非 /assets/ 开头（不存在的 chunk 文件直接返回 404，不要回 HTML）
        3. Accept 头包含 text/html（浏览器请求页面才 fallback，JS/CSS/XHR 请求不回）
        """
        response = await call_next(request)
        if response.status_code != 404:
            return response
        path = request.url.path
        # 优先尝试直接命中静态文件（favicon.svg 等顶层资源）
        fp = _STATIC / path.lstrip("/")
        if fp.is_file():
            return FileResponse(str(fp))
        # 用纯函数判断是否需要 fallback
        if should_spa_fallback(path, request.headers.get("accept", "")):
            return FileResponse(str(_STATIC / "index.html"))
        return response
