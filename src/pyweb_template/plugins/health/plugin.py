"""健康检查插件（内置）.

用途：
- 启动时自动注册，提供 `/api/v1/health/ping` 端点
- 演示 PluginBase 最简实现（无 models / 无 navigation）
"""

from __future__ import annotations

import datetime as dt
import platform
import sys
from typing import override

from fastapi import APIRouter

from pyweb_template.plugins.base import PluginBase


class HealthPlugin(PluginBase):
    """基础健康检查插件."""

    name = "health"
    version = "0.1.0"
    description = "服务健康检查与运行环境探针"
    icon = "HeartOutlined"

    @override
    def register_routes(self, router: APIRouter) -> None:
        @router.get("/ping")
        def ping() -> dict[str, object]:
            """服务存活探针."""
            return {
                "status": "pong",
                "timestamp": dt.datetime.now(dt.UTC).isoformat(),
                "python": sys.version,
                "platform": platform.platform(),
            }

        @router.get("/ready")
        def readiness() -> dict[str, object]:
            """就绪探针."""
            return {"status": "ready"}
