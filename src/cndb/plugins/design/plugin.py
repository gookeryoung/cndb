"""design 插件 —— 【设计】模块注册入口（ADR 0079）."""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase


class DesignPlugin(PluginBase):
    """设计插件：结构 DSL 描述产品结构设计，3D 实时预览与生成."""

    name = "design"
    version = "0.1.0"
    description = "设计模块：结构 DSL（.cnmd）描述产品结构设计，3D 实时预览与网格模型生成"
    icon = "ToolOutlined"
    route_prefix = "workspaces"

    @override
    def register_models(self) -> None:
        """导入 models 确保 Base.metadata 包含 design_* 两表."""
        from cndb.plugins.design import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """挂载 design 路由：设计 CRUD / 即时编译 / 版本；复用模块库 API（ADR 0118 §6）."""
        from cndb.plugins.design.routers import library_router
        from cndb.plugins.design.routers import router as designs_router

        router.include_router(designs_router)
        router.include_router(library_router)


plugin = DesignPlugin()

__all__ = ["DesignPlugin", "plugin"]
