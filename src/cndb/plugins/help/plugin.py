"""help 插件 —— 帮助文档的典型示例与图示例（ADR 0029 / 0030）."""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase
from cndb.plugins.help.routers.examples import router as examples_router
from cndb.plugins.help.routers.figures import router as figures_router


class HelpPlugin(PluginBase):
    """帮助文档插件：示例清单 / CSV 下载 / 代码生成的图示例（无数据库、无迁移）."""

    name = "help"
    version = "0.2.0"
    description = "帮助文档：典型示例、CSV 下载与图示例"
    icon = "QuestionCircleOutlined"

    @override
    def register_routes(self, router: APIRouter) -> None:
        """挂载 /api/v1/help/examples 与 /api/v1/help/figures 路由."""
        router.include_router(examples_router)
        router.include_router(figures_router)


plugin = HelpPlugin()

__all__ = ["HelpPlugin", "plugin"]
