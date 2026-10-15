"""请求观测：request_id 贯穿 + 访问耗时日志.

设计取舍：

- **纯 ASGI 中间件**（而非 ``BaseHTTPMiddleware``）：导出/下载等流式响应不会被缓冲，
  且能在 ``finally`` 里拿到真实总耗时；
- **X-Request-ID**：客户端可传（便于跨系统串联），缺省生成；响应头回传，用户报错时可直接对日志；
- **访问日志**：默认 INFO（``ACCESS_LOG_ENABLED`` 可关）；超过 ``SLOW_REQUEST_MS`` 升为 WARNING
  并带 ``slow=true``；健康检查 / 静态资源降为 DEBUG，避免探针刷屏；
- **关联**：request_id 放进 ContextVar；同步端点跑在线程池时上下文会被复制，因此
  ``core/database.py`` 的既有慢查询日志（阈值 ``settings.SLOW_QUERY_MS``）也能带上同一个
  request_id。``user_id`` 由 ``get_current_user`` 写入 ``request.state``，中间件在响应后读取。

慢查询日志本身沿用 ``core/database.py`` 里的既有实现（它已归一化语句、截断且不记录参数），
本模块只负责把 request_id 关联过去，避免重复造第二套监听。
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger("cndb.access")

# 当前请求 id（未在请求上下文内时为空串）
_request_id_var: ContextVar[str] = ContextVar("cndb_request_id", default="")

# 这些前缀只记 DEBUG（探针 / 静态资源），避免 INFO 日志被刷满
_QUIET_PREFIXES: tuple[str, ...] = ("/api/health", "/assets/", "/favicon")


_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(*, access_log: bool | None = None) -> None:
    """给 ``cndb`` 命名空间配置级别与处理器（幂等）.

    背景：项目原先没有任何 logging 配置，root 默认 WARNING —— 应用里的 INFO 日志（含访问日志）
    根本不会输出，只有 WARNING+ 靠 Python 的 lastResort 打到 stderr。这里只动
    ``cndb`` 命名空间：没有处理器时挂一个 stderr 处理器，级别默认 INFO（``ACCESS_LOG_ENABLED``
    为假时降到 WARNING，只保留慢请求/慢 SQL 等告警）；``propagate`` 保持 True，便于 pytest caplog 捕获。
    """
    enabled = settings_access_log() if access_log is None else access_log
    pkg_logger = logging.getLogger("cndb")
    if not pkg_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        pkg_logger.addHandler(handler)
    pkg_logger.setLevel(logging.INFO if enabled else logging.WARNING)


def settings_access_log() -> bool:
    """读取访问日志开关（延迟导入 settings，避免与 core.config 的循环依赖）."""
    from cndb.core.config import settings

    return bool(settings.ACCESS_LOG_ENABLED)


def get_request_id() -> str:
    """返回当前请求的 request_id（不在请求上下文时为空串）."""
    return _request_id_var.get()


@contextmanager
def bind_request_id(request_id: str) -> Iterator[None]:
    """在代码块内绑定 request_id（后台任务 / 测试复用同一关联值）."""
    token = _request_id_var.set(request_id)
    try:
        yield
    finally:
        _request_id_var.reset(token)


def set_actor_ids(request_state: Any, *, user_id: int | None, username: str | None = None) -> None:
    """把当前用户写入 ``request.state``，供访问日志关联（失败静默，绝不影响业务）."""
    try:
        request_state.user_id = user_id
        request_state.username = username
    except Exception:
        pass


class RequestObservabilityMiddleware:
    """记录每个 HTTP 请求的耗时、状态码与 request_id，并回写 X-Request-ID 响应头."""

    def __init__(
        self,
        app: Callable[
            [MutableMapping[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]], Awaitable[None]
        ],
        *,
        slow_ms: int = 500,
        access_log: bool = True,
    ) -> None:
        self.app = app
        self.slow_ms = max(0, slow_ms)
        self.access_log = access_log

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[..., Awaitable[Any]],
        send: Callable[..., Awaitable[Any]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # 客户端可传 request id（便于跨系统串联），缺省生成
        headers = {k.lower(): v for k, v in (scope.get("headers") or [])}
        incoming = (headers.get(b"x-request-id") or b"").decode("latin-1").strip()
        request_id = incoming or uuid.uuid4().hex
        token = _request_id_var.set(request_id)

        status_holder: dict[str, int] = {"status": 500}

        async def _send(message: MutableMapping[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                status_holder["status"] = int(message.get("status", 500))
                from starlette.datastructures import MutableHeaders

                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        started = time.perf_counter()
        try:
            await self.app(scope, receive, _send)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            try:
                self._log_request(scope, status_holder["status"], duration_ms, request_id)
            finally:
                _request_id_var.reset(token)

    def _log_request(
        self,
        scope: MutableMapping[str, Any],
        status: int,
        duration_ms: float,
        request_id: str,
    ) -> None:
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "")
        actor = (scope.get("state") or {}).get("user_id")
        is_slow = duration_ms >= self.slow_ms
        message = (
            f"method={method} path={path} status={status} "
            f"duration_ms={duration_ms:.1f} request_id={request_id}"
            + (f" user_id={actor}" if actor is not None else "")
            + (" slow=true" if is_slow else "")
        )

        if is_slow:
            # 慢请求始终记录（即使关闭访问日志），否则失去排障价值
            logger.warning(message)
            return
        if not self.access_log:
            return
        if path.startswith(_QUIET_PREFIXES):
            logger.debug(message)
            return
        logger.info(message)


__all__ = [
    "RequestObservabilityMiddleware",
    "bind_request_id",
    "configure_logging",
    "get_request_id",
    "set_actor_ids",
]
