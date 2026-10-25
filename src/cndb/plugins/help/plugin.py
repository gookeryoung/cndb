"""help 插件 —— 帮助文档的典型示例清单与 CSV 下载."""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase
from cndb.plugins.help.routers.examples import router as examples_router


class HelpPlugin(PluginBase):
    """帮助文档插件：静态示例清单 + 白名单 CSV 下载（无数据库、无迁移）."""

    name = "help"
    version = "0.1.0"
    description = "帮助文档：典型示例清单与 CSV 下载"
    icon = "QuestionCircleOutlined"

    @override
    def register_routes(self, router: APIRouter) -> None:
        """挂载 /api/v1/help/examples 路由."""
        router.include_router(examples_router)


plugin = HelpPlugin()

__all__ = ["HelpPlugin", "plugin"]
