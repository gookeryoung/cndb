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

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi_offline import FastAPIOffline

from cndb.core.config import settings
from cndb.core.errors import CndbError
from cndb.core.migrations import ensure_db_migrated
from cndb.core.plugin_registry import plugin_registry
from cndb.core.system_api import register_system_routes
from cndb.plugins.tables.routers.public import router as public_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """应用生命周期管理.

    启动时自动执行数据库迁移（alembic upgrade head），
    确保 schema 处于最新版本。首次运行的全新数据库会自动 create_all。
    迁移失败时给出可操作指引（备份恢复/重建），而非裸 traceback。
    """
    try:
        ensure_db_migrated()
    except Exception as exc:
        logger.critical("数据库初始化失败，服务无法启动: %s", exc, exc_info=True)
        raise RuntimeError(
            "数据库初始化失败，服务无法启动。\n"
            "  处理建议：\n"
            "  1. 检查数据库文件所在目录是否可写（默认 data/ 下 cndb.db）；\n"
            "  2. 使用 cndb restore 从最近备份恢复（推荐，可自动对齐 schema）；\n"
            "  3. 确认无可用备份后再考虑备份后删除数据库文件重建（会丢数据）。\n"
            f"  原始错误：{exc}"
        ) from exc

    yield


app = FastAPIOffline(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="cndb - FastAPI + SQLAlchemy + Plugin 架构脚手架",
    lifespan=lifespan,
)


# ── 启动时自动发现并挂载插件（模块加载时执行，避免依赖 TestClient lifespan）──
if settings.PLUGINS_AUTO_DISCOVER:  # pragma: no cover - 配置开关
    plugin_registry.discover_and_load()
plugin_registry.mount_routes(app)

# tables 插件全局公开路由
app.include_router(public_router)

# 系统管理级路由（backup/restore/info）— 需 superuser 权限
register_system_routes(app)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# gzip 压缩（注册在 CORS 之后成为最外层）：静态资源与 API JSON 统一压缩，
# 1KB 以下小响应不压缩（压缩收益低于开销）
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.get("/api/health", tags=["framework"])
def health_check() -> dict[str, object]:
    """框架级健康检查（liveness：仅表明进程存活，不探测依赖）."""
    return {"status": "ok", "version": settings.APP_VERSION, "app": settings.APP_NAME}


@app.get("/api/health/ready", tags=["framework"])
def health_ready() -> JSONResponse:
    """就绪探测（readiness）：探测 DB 可达性与迁移状态.

    DB 不可达返回 503（部署层可据此摘除实例）；alembic_version 缺失
    仅在 payload 中标注 migration_current=null，不影响就绪判定。
    """
    from cndb.core.database import db_readiness

    snapshot = db_readiness()
    if not snapshot["db"]:
        return JSONResponse(
            status_code=503,
            content={"status": "unready", "version": settings.APP_VERSION, **snapshot},
        )
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "version": settings.APP_VERSION, **snapshot},
    )


# ── 统一错误契约（core/errors.py）─────────────────────────────────


@app.exception_handler(CndbError)
async def _cndb_error_handler(request: Request, exc: CndbError) -> Response:
    """业务异常 → 统一错误响应体 ``{"detail", "code"}``.

    服务层抛出的 CndbError 族在此统一映射，路由层无需逐个 try/except。
    """
    logger.warning(
        "业务异常 [%s] %s %s: %s (context=%s)",
        exc.code,
        request.method,
        request.url.path,
        exc.detail,
        exc.context,
    )
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


@app.exception_handler(Exception)
async def _unhandled_error_handler(request: Request, exc: Exception) -> Response:
    """未捕获异常 → 500 统一响应体 + 完整堆栈日志.

    注意：ServerErrorMiddleware 发送本响应后仍会重抛异常（由 uvicorn 记录），
    本 handler 的职责是保证客户端拿到统一 JSON 形状而非空白 500。
    """
    logger.exception("未处理异常 %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "内部服务器错误", "code": "internal_error"},
    )


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
_ASSETS_DIR = _STATIC / "assets"
_INDEX_HTML = _STATIC / "index.html"
# 仅当下目录结构完整时才挂载 SPA 静态资源；前端未 build 时（如 CI、纯后端测试）跳过，
# 避免 StaticFiles 构造器因目录不存在抛 RuntimeError
_SPA_READY = _STATIC.is_dir() and _ASSETS_DIR.is_dir() and _INDEX_HTML.is_file()

if _SPA_READY:  # pragma: no cover - 需要前端构建产物
    # 挂载 /assets 为独立静态目录（带 hash 的产物，可长缓存）
    app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="assets")

    @app.middleware("http")
    async def _spa_fallback(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """SPA 路由 fallback + 缓存策略中间件.

        缓存策略：
        - index.html 及其它顶层 HTML：Cache-Control: no-cache（每次协商获取最新版本）
          原因：Vite 构建产物文件名带 hash，index.html 是唯一引用入口，必须及时刷新
        - /assets/*：Cache-Control: public, max-age=31536000, immutable
          原因：Vite 输出带内容 hash，内容永不变化，可长缓存

        fallback 逻辑：
        仅对以下条件同时满足的 404 请求回退到 index.html：
        1. 非 /api/ 开头（API 路由不走前端）
        2. 非 /assets/ 开头（不存在的 chunk 文件直接返回 404，不要回 HTML）
        3. Accept 头包含 text/html（浏览器请求页面才 fallback，JS/CSS/XHR 请求不回）
        """
        response = await call_next(request)
        path = request.url.path

        # /assets/ 下带 hash 的产物 —— 一年长缓存 + immutable
        if path.startswith("/assets/") and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

        # HTML 页面 —— 禁止缓存，确保每次都拿到最新 index.html
        is_html_path = path == "/" or path.endswith(".html")
        if is_html_path and response.status_code == 200:
            response.headers["Cache-Control"] = "no-cache, must-revalidate"

        if response.status_code != 404:
            return response

        # 404 路径 —— 优先尝试直接命中静态文件（favicon.svg 等顶层资源）
        fp = _STATIC / path.lstrip("/")
        if fp.is_file():
            return FileResponse(str(fp))
        # 用纯函数判断是否需要 fallback
        if should_spa_fallback(path, request.headers.get("accept", "")):
            return FileResponse(
                str(_STATIC / "index.html"),
                headers={"Cache-Control": "no-cache, must-revalidate"},
            )
        return response
